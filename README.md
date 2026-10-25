# nokto-ai-output-validator

Validates structured output from LLM calls before it reaches production. Catches malformed JSON, missing required fields, wrong types, enum violations, and unfilled `{{PLACEHOLDER}}` tokens.

Also includes a generic AI enrichment helper for generating product content via Claude.

## Installation

```bash
pip install -r requirements.txt
```

## Validate LLM output

```python
from src.validator import OutputSchema, FieldRule, validate_output, Status

schema = OutputSchema(
    required_fields=[
        FieldRule(name="body_html", type=str),
        FieldRule(name="tags",      type=list),
        FieldRule(name="status",    allowed_values=["COMPLETED", "BLOCKED"]),
    ],
    forbid_placeholders=True,
)

result = validate_output(llm_response_text, schema)

if result.status == Status.BLOCKED:
    print("Output contains unfilled placeholders — stopping.")
elif not result.ok:
    for error in result.errors:
        print(f"Validation error: {error}")
else:
    # safe to use
    ...
```

### Field semantics

- **Missing vs null.** A key listed in `required_fields` must be present.
  `nullable=True` only allows the value `null`; it does not make the key
  optional. Use `required=False` for a key that may be absent.
- **Numbers.** `type=int` / `type=float` reject `true`/`false` (Python treats
  `bool` as `int`). List `bool` or `object` explicitly to accept booleans.
  `type` may be a tuple, e.g. `(int, float)`.
- **Non-finite numbers.** `NaN`, `Infinity`, `-Infinity` and numbers that
  overflow to infinity (e.g. `1e400`) are invalid JSON and give `FAIL`.
  Oversized integers and too deeply nested JSON also give `FAIL` instead of
  raising.
- **Enums.** `allowed_values` keeps booleans and numbers apart: `true` does
  not match `1`, and `0` does not match `false`.
- **List items.** `item_type=str` requires a JSON array whose items all have
  that type, e.g. `FieldRule(name="tags", type=list, item_type=str)`.

These rules are stricter than before 2026-10. Migration: if you relied on
`nullable=True` accepting a missing key, add `required=False`; if a numeric
field may legitimately be a boolean, add `bool` to `type`. Null values on a
non-nullable field now report `Field '<name>' is null but not nullable.`
instead of `Missing required field '<name>'.`

### Quick check

```python
from src.validator import validate_json_output

result = validate_json_output(raw_json, required_keys=["title", "description"])
```

## Generate product content

```python
from src.enrichment import generate_product_content

content = generate_product_content(
    product_name="Example Bike Model XL",
    attributes={"colors": ["black", "red"], "qty": 4, "price_nok": 9999},
    api_key="sk-ant-...",
    timeout=60.0,      # optional, per-attempt seconds (default 60)
    max_retries=2,     # optional, SDK retry budget (default 2)
)
# content = {"body_html": "<p>...</p>", "tags": "tag1, tag2"}  or None
```

`generate_product_content` returns the dict above or `None`; it does not
raise for API errors, timeouts, rate limits, empty/refused/truncated
(`max_tokens`) responses, non-text content blocks, malformed bodies or
output that fails validation (including non-string `tags` items). Retries
for connection errors, 408, 409, 429 and 5xx are done by the `anthropic` SDK
using `max_retries`; `timeout` applies per attempt.

## Security boundaries

This is a validation helper, not a sandbox. It checks the *shape* of LLM
output (JSON validity, required fields, types, allowed values, unfilled
`{{PLACEHOLDER}}` tokens) — it does not sanitize content for injection, XSS,
or other downstream use. **Validation is not HTML sanitizing:** a `PASS`
means `body_html` is a string, not that it is safe HTML. Treat validated
fields such as `body_html` as untrusted and escape or sanitize them at the
consumer's rendering boundary before rendering or storing them. See [SECURITY.md](SECURITY.md)
for the full security model, known limitations, and how to report a
vulnerability.

## Tests

```bash
pytest tests/ -v
```

## Evidence

- `tests/test_validator.py` — 11 tests covering JSON parsing, placeholder
  detection, required-field/type/enum checks, and the `validate_json_output`
  convenience wrapper.
- `tests/test_validator_strict.py` — 55 tests for missing vs null, bool vs
  int/float, NaN/Infinity, type-aware enums, lists/objects and list item
  types.
- `tests/test_enrichment.py` — 40 adapter tests for
  `generate_product_content` using the real `anthropic` client with a mocked
  HTTP transport (no network): valid and fenced JSON, invalid tags, empty,
  non-text, truncated and refused responses, malformed bodies, rate limit,
  server error, timeout and the retry budget.
- CI (`.github/workflows/ci.yml`) runs `pytest tests/ -v` on every push and
  pull request.

## Known limitations

- The unfilled-placeholder check only matches `{{UPPER_SNAKE_CASE}}`. Other
  templating syntaxes are not detected.
- `generate_product_content` has no retry logic of its own; it relies on the
  `anthropic` SDK's built-in retries (`max_retries`). Worst-case wall time is
  roughly `timeout * (max_retries + 1)` plus SDK backoff.
- Item types are only checked for top-level list fields (`item_type`).
  Nested objects are not validated against a schema.

