"""Adapter tests for generate_product_content.

The real anthropic SDK client is used, but its HTTP transport is replaced by
an in-process mock transport, so no request leaves the test process.
"""

import json

import anthropic
import pytest

try:  # anthropic>=1.0 is built on httpx2, earlier releases on httpx
    import httpx2 as _httpx
except ImportError:  # pragma: no cover - depends on the installed SDK
    import httpx as _httpx

from src import enrichment
from src.enrichment import generate_product_content


class FakeSDK:
    """Stands in for anthropic.Anthropic and records how it was configured."""

    def __init__(self, handler):
        self._handler = handler
        self._real = anthropic.Anthropic
        self.client_kwargs = None
        self.requests = []

    def __call__(self, **kwargs):
        self.client_kwargs = kwargs

        def transport(request):
            self.requests.append(request)
            return self._handler(request)

        return self._real(
            **kwargs,
            http_client=_httpx.Client(transport=_httpx.MockTransport(transport)),
        )


def _message(content, stop_reason="end_turn"):
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "test-model",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
    }


def _text(text):
    return {"type": "text", "text": text}


def _reply(content, stop_reason="end_turn", status=200, headers=None):
    body = _message(content, stop_reason)

    def handler(request):
        return _httpx.Response(status, json=body, headers=headers)

    return handler


@pytest.fixture
def sdk(monkeypatch):
    def install(handler):
        fake = FakeSDK(handler)
        monkeypatch.setattr(enrichment.anthropic, "Anthropic", fake)
        return fake

    return install


def _call(**kwargs):
    return generate_product_content(
        product_name="Testsykkel",
        attributes={"colors": ["black"], "qty": 4},
        api_key="test-key",
        **kwargs,
    )


VALID = {"body_html": "<p>Rask sykkel.</p>", "tags": ["sykkel", "el"]}


# ── Valid responses ──────────────────────────────────────────────────────────


def test_valid_response_returns_documented_dict(sdk):
    fake = sdk(_reply([_text(json.dumps(VALID))]))
    assert _call() == {"body_html": "<p>Rask sykkel.</p>", "tags": "sykkel, el"}
    assert len(fake.requests) == 1


@pytest.mark.parametrize(
    "wrapped",
    [
        "```json\n{payload}\n```",
        "```JSON\n{payload}\n```",
        "```\n{payload}\n```",
        "  ```json\n{payload}\n```  \n",
        "```json{payload}```",
        "```json\n{payload}\n```\nHåper dette hjelper.",
        "```json\n{payload}",
    ],
)
def test_fenced_json_is_accepted(sdk, wrapped):
    sdk(_reply([_text(wrapped.replace("{payload}", json.dumps(VALID)))]))
    assert _call() == {"body_html": "<p>Rask sykkel.</p>", "tags": "sykkel, el"}


def test_fenced_json_with_backticks_inside_content(sdk):
    payload = {"body_html": "<p>Bruk ``` i kode.</p>", "tags": ["a"]}
    sdk(_reply([_text("```json\n" + json.dumps(payload) + "\n```")]))
    assert _call() == {"body_html": "<p>Bruk ``` i kode.</p>", "tags": "a"}


def test_text_block_after_thinking_block_is_used(sdk):
    sdk(
        _reply(
            [
                {"type": "thinking", "thinking": "", "signature": "sig"},
                _text(json.dumps(VALID)),
            ]
        )
    )
    assert _call() == {"body_html": "<p>Rask sykkel.</p>", "tags": "sykkel, el"}


def test_empty_tags_list_gives_empty_string(sdk):
    sdk(_reply([_text(json.dumps({"body_html": "<p>x</p>", "tags": []}))]))
    assert _call() == {"body_html": "<p>x</p>", "tags": ""}


# ── Invalid output after the model call: None, never an exception ────────────


@pytest.mark.parametrize(
    "payload",
    [
        {"body_html": "<p>product</p>", "tags": [1]},
        {"body_html": "<p>product</p>", "tags": ["a", None]},
        {"body_html": "<p>product</p>", "tags": ["a", ["b"]]},
        {"body_html": "<p>product</p>", "tags": "a, b"},
        {"body_html": None, "tags": ["a"]},
        {"body_html": "<p>product</p>"},
        {"body_html": "<p>{{DESCRIPTION}}</p>", "tags": ["a"]},
    ],
)
def test_invalid_payload_returns_none(sdk, payload):
    sdk(_reply([_text(json.dumps(payload))]))
    assert _call() is None


@pytest.mark.parametrize(
    "content",
    [
        [],
        [_text("")],
        [_text("   \n")],
        [{"type": "tool_use", "id": "toolu_1", "name": "x", "input": {}}],
        [{"type": "thinking", "thinking": "", "signature": "sig"}],
        [_text("not json at all")],
        [_text('{"body_html": "<p>x</p>", "tags": [NaN]}')],
        [_text('{"body_html": "<p>x</p>", "tags": ["a"]')],
        [_text('```json\n{"body_html": "<p>x</p>", "tags": ["a"]')],
        [_text("Her er JSON:\n```json\n" + json.dumps(VALID) + "\n```")],
    ],
)
def test_unusable_content_returns_none(sdk, content):
    sdk(_reply(content))
    assert _call() is None


def test_truncated_response_returns_none_even_if_json_parses(sdk):
    sdk(_reply([_text(json.dumps(VALID))], stop_reason="max_tokens"))
    assert _call() is None


def test_refusal_returns_none(sdk):
    sdk(_reply([], stop_reason="refusal"))
    assert _call() is None


@pytest.mark.parametrize(
    "body, content_type",
    [
        (b"not json", "application/json"),
        (b"{}", "application/json"),
        (b'{"content": null}', "application/json"),
        (b"<html>proxy error</html>", "text/html"),
    ],
)
def test_malformed_http_body_returns_none(sdk, body, content_type):
    def handler(request):
        return _httpx.Response(200, content=body, headers={"content-type": content_type})

    sdk(handler)
    assert _call() is None


# ── Transport errors, timeout and retry budget ───────────────────────────────


def test_client_gets_explicit_timeout_and_retry_budget(sdk):
    fake = sdk(_reply([_text(json.dumps(VALID))]))
    _call()
    assert fake.client_kwargs["api_key"] == "test-key"
    assert fake.client_kwargs["timeout"] == enrichment.DEFAULT_TIMEOUT_SECONDS
    assert fake.client_kwargs["max_retries"] == enrichment.DEFAULT_MAX_RETRIES


def test_rate_limit_returns_none_after_configured_retries(sdk):
    def handler(request):
        return _httpx.Response(
            429,
            json={"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}},
            headers={"retry-after-ms": "1"},
        )

    fake = sdk(handler)
    assert _call(max_retries=1) is None
    assert len(fake.requests) == 2


def test_server_error_returns_none(sdk):
    def handler(request):
        return _httpx.Response(
            529,
            json={"type": "error", "error": {"type": "overloaded_error", "message": "x"}},
            headers={"retry-after-ms": "1"},
        )

    sdk(handler)
    assert _call(max_retries=0) is None


def test_timeout_returns_none(sdk):
    def handler(request):
        raise _httpx.ReadTimeout("timed out", request=request)

    fake = sdk(handler)
    assert _call(timeout=1.5, max_retries=0) is None
    assert fake.client_kwargs["timeout"] == 1.5
    assert len(fake.requests) == 1


def test_connection_error_returns_none(sdk):
    def handler(request):
        raise _httpx.ConnectError("refused", request=request)

    sdk(handler)
    assert _call(max_retries=0) is None


def test_positional_arguments_unchanged(sdk):
    sdk(_reply([_text(json.dumps(VALID))]))
    result = generate_product_content("Sykkel", {"qty": 1}, "test-key", "test-model", "English")
    assert result == {"body_html": "<p>Rask sykkel.</p>", "tags": "sykkel, el"}
