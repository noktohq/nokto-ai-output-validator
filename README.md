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

## Tests

```bash
pytest tests/ -v
```

