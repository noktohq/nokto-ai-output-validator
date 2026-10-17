# Security policy

## Supported version

Security fixes are applied to the latest `main` branch only.

## Reporting

Report suspected vulnerabilities privately to `edin@nokto.no`. Do not open a
public issue for a security report. Do not include production API keys,
credentials, or personal data in the report.

## Security model

This library is a validation helper, not a sandbox or a security boundary:

- `validate_output` / `validate_json_output` parse and check the *shape* of
  already-received LLM output (JSON validity, required fields, types, allowed
  values, unfilled `{{PLACEHOLDER}}` tokens). They do not sanitize the content
  for injection, XSS, or other downstream use — the caller is responsible for
  treating `body_html` and similar fields as untrusted before rendering or
  storing them.
- `src.enrichment.generate_product_content` sends product attributes to
  the Anthropic API using a caller-supplied API key and returns the model's
  output only after it has passed `validate_output` (including string-only
  `tags`). It sets an explicit per-attempt `timeout` and `max_retries` on the
  SDK client; retries for connection errors, 408, 409, 429 and 5xx are done
  by the SDK. It performs no output sanitization beyond the shape checks
  above — validation is not HTML sanitizing.

## Known limitations

- The placeholder check only matches the pattern `{{UPPER_SNAKE_CASE}}`. Other
  templating syntaxes (e.g. `{placeholder}`, `${placeholder}`) are not
  detected.
- `src/enrichment.py` is tested with a mocked HTTP transport
  (`tests/test_enrichment.py`); no test calls the real API.
  `validate_output`/`validate_json_output` are covered by
  `tests/test_validator.py` and `tests/test_validator_strict.py`.
- No dependency vulnerability scanning is configured in CI.
