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
)
# content = {"body_html": "<p>...</p>", "tags": "tag1, tag2"}
```

## Security boundaries

This is a validation helper, not a sandbox. It checks the *shape* of LLM
output (JSON validity, required fields, types, allowed values, unfilled
`{{PLACEHOLDER}}` tokens) — it does not sanitize content for injection, XSS,
or other downstream use. Treat validated fields such as `body_html` as
untrusted before rendering or storing them. See [SECURITY.md](SECURITY.md)
for the full security model, known limitations, and how to report a
vulnerability.

## Tests

```bash
pytest tests/ -v
```

## Evidence

- `tests/test_validator.py` — 11 tests, all passing, covering JSON parsing,
  placeholder detection, required-field/type/enum checks, and the
  `validate_json_output` convenience wrapper.
- `src/enrichment.py` (the Anthropic API call in `generate_product_content`)
  has no automated test coverage — it is not exercised by `pytest`.
- CI (`.github/workflows/ci.yml`) runs `pytest tests/ -v` on every push and
  pull request.

## Known limitations

- The unfilled-placeholder check only matches `{{UPPER_SNAKE_CASE}}`. Other
  templating syntaxes are not detected.
- `generate_product_content` performs no retries and no rate-limit handling
  around the Anthropic API call.

