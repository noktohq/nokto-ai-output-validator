"""
AI enrichment helper.

Calls an LLM to generate structured product content (description + tags),
then validates the output before returning it.

Requirements:
    pip install anthropic
"""

import json
import logging
from typing import Any

import anthropic

from .validator import OutputSchema, FieldRule, validate_output, Status

log = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-haiku-4-5-20251001"

_OUTPUT_SCHEMA = OutputSchema(
    required_fields=[
        FieldRule(name="body_html", type=str),
        FieldRule(name="tags", type=list),
    ],
    forbid_placeholders=True,
)


def generate_product_content(
    product_name: str,
    attributes: dict[str, Any],
    api_key: str,
    model: str = _DEFAULT_MODEL,
    language: str = "Norwegian",
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

    Returns:
        Dict with "body_html" (str) and "tags" (comma-separated str),
        or None if generation or validation fails.
    """
    client = anthropic.Anthropic(api_key=api_key)

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
        raw = message.content[0].text.strip()

        # Strip markdown code fence if present
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1].lstrip("json").strip() if len(parts) > 1 else raw

        result = validate_output(raw, _OUTPUT_SCHEMA)
        if not result.ok:
            log.warning(
                "AI output validation failed for '%s': %s",
                product_name,
                result.errors,
            )
            return None

        data = json.loads(raw)
        tags = data.get("tags", [])
        return {
            "body_html": data.get("body_html", ""),
            "tags": ", ".join(tags) if isinstance(tags, list) else tags,
        }

    except anthropic.APIError as exc:
        log.warning("Anthropic API error for '%s': %s", product_name, exc)
        return None

