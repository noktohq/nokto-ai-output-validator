"""
AI enrichment helper.

Calls an LLM to generate structured product content (description + tags),
then validates the output before returning it.

Requirements:
    pip install anthropic
"""

import json
import logging
import re
from typing import Any

import anthropic

from .validator import OutputSchema, FieldRule, validate_output, _loads

log = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# Explicit budget for the SDK client. The SDK retries connection errors,
# 408, 409, 429 and >=500 itself (with backoff); each attempt gets `timeout`
# seconds. Worst case wall time is roughly timeout * (max_retries + 1) plus
# backoff. The SDK defaults are a 600 s timeout and 2 retries.
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_RETRIES = 2

_OUTPUT_SCHEMA = OutputSchema(
    required_fields=[
        FieldRule(name="body_html", type=str),
        FieldRule(name="tags", type=list, item_type=str),
    ],
    forbid_placeholders=True,
)

# Stop reasons where the text is incomplete or not an answer.
_UNUSABLE_STOP_REASONS = {"max_tokens", "refusal", "model_context_window_exceeded"}

_FENCE_OPEN_RE = re.compile(r"\A```[A-Za-z0-9_-]*")


def _response_text(message: Any) -> str | None:
    """Concatenate the text blocks of a Messages API response.

    Returns None when the response has no usable text (empty content,
    only non-text blocks, or a body that is not a message at all).
    """
    content = getattr(message, "content", None)
    if not isinstance(content, list):
        return None
    parts = [
        block.text
        for block in content
        if getattr(block, "type", None) == "text"
        and isinstance(getattr(block, "text", None), str)
    ]
    text = "".join(parts).strip()
    return text or None


def _strip_code_fence(text: str) -> str:
    """Remove a leading ```/```json fence and everything from the last ```.

    The result is still validated as JSON, so a truncated or ambiguous fence
    fails validation instead of being trusted.
    """
    if not text.startswith("```"):
        return text
    body = _FENCE_OPEN_RE.sub("", text, count=1)
    end = body.rfind("```")
    if end != -1:
        body = body[:end]
    return body.strip()


def generate_product_content(
    product_name: str,
    attributes: dict[str, Any],
    api_key: str,
    model: str = _DEFAULT_MODEL,
    language: str = "Norwegian",
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> dict[str, str] | None:
    """
    Generate a product description and tags for a Shopify product.

    Args:
        product_name: Display name of the product.
        attributes:   Dict of product attributes shown to the model
                      (e.g. {"colors": ["red"], "qty": 4, "price_nok": 499}).
        api_key:      Anthropic API key.
        model:        Claude model ID.
        language:     Language for generated text (default: Norwegian).
        timeout:      Per-attempt request timeout in seconds, passed to the SDK.
        max_retries:  SDK retry budget for connection errors, 408, 409, 429
                      and >=500. 0 disables retries.

    Returns:
        Dict with "body_html" (str) and "tags" (comma-separated str),
        or None if the API call fails, the response is empty, truncated,
        refused or malformed, or the output fails validation.
        `body_html` is model output, not sanitized HTML.
    """
    client = anthropic.Anthropic(
        api_key=api_key,
        timeout=timeout,
        max_retries=max_retries,
    )

    attr_lines = "\n".join(f"  {k}: {v}" for k, v in attributes.items())

    prompt = f"""You are a product copywriter. Write in {language}.

Product: {product_name}
Attributes:
{attr_lines}

Task:
1. Write a short product description (2-3 sentences). Be factual and specific.
2. Generate 5-10 relevant tags (lowercase, comma-separated).

Reply ONLY with valid JSON — no explanation:
{{
  "body_html": "<p>Description here.</p>",
  "tags": ["tag1", "tag2"]
}}"""

    try:
        message = client.messages.create(
            model=model,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as exc:
        log.warning("Anthropic API error for '%s': %s", product_name, exc)
        return None
    except json.JSONDecodeError:
        log.warning("Anthropic API returned a malformed body for '%s'", product_name)
        return None

    stop_reason = getattr(message, "stop_reason", None)
    if stop_reason in _UNUSABLE_STOP_REASONS:
        log.warning(
            "AI response for '%s' is unusable (stop_reason=%s)",
            product_name,
            stop_reason,
        )
        return None

    raw = _response_text(message)
    if raw is None:
        log.warning("AI response for '%s' has no text content", product_name)
        return None

    raw = _strip_code_fence(raw)

    result = validate_output(raw, _OUTPUT_SCHEMA)
    if not result.ok:
        log.warning(
            "AI output validation failed for '%s': %s",
            product_name,
            result.errors,
        )
        return None

    # The schema guarantees body_html is a str and tags is a list of str.
    data = _loads(raw)
    return {
        "body_html": data["body_html"],
        "tags": ", ".join(data["tags"]),
    }
