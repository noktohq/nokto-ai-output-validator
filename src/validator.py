"""
AI output validator.

Validates structured output from LLM calls â€” checks JSON shape, required fields,
enum values, and detects unfilled template placeholders before the output is used.
"""

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"


@dataclass
class FieldRule:
    """Declares a required field in an AI output dict."""

    name: str
    type: type | None = None
    allowed_values: list[Any] | None = None
    nullable: bool = False


@dataclass
class OutputSchema:
    """Declares the expected shape of one AI output."""

    required_fields: list[FieldRule] = field(default_factory=list)
    forbid_placeholders: bool = True


@dataclass
class ValidationResult:
    status: Status
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == Status.PASS


_PLACEHOLDER_RE = re.compile(r"\{\{[A-Z_]+\}\}")


def validate_output(
    raw: str,
    schema: OutputSchema,
) -> ValidationResult:
    """
    Validate a raw JSON string against an OutputSchema.

    Returns a ValidationResult. Sets status to FAIL if any required field is
    missing or has the wrong type/value. Sets BLOCKED if the output contains
    unfilled {{PLACEHOLDER}} tokens.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Parse JSON
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return ValidationResult(
            status=Status.FAIL,
            errors=[f"Invalid JSON: {exc}"],
        )

    if not isinstance(data, dict):
        return ValidationResult(
            status=Status.FAIL,
            errors=["Output must be a JSON object, not a list or scalar."],
        )

    # Unfilled placeholder check
    if schema.forbid_placeholders and _PLACEHOLDER_RE.search(raw):
        found = _PLACEHOLDER_RE.findall(raw)
        return ValidationResult(
            status=Status.BLOCKED,
            errors=[f"Unfilled placeholder(s) in output: {', '.join(found)}"],
        )

    # Field validation
    for rule in schema.required_fields:
        value = data.get(rule.name)

        if value is None:
            if not rule.nullable:
                errors.append(f"Missing required field '{rule.name}'.")
            continue

        if rule.type is not None and not isinstance(value, rule.type):
            errors.append(
                f"Field '{rule.name}' must be {rule.type.__name__}, "
                f"got {type(value).__name__}."
            )
            continue

        if rule.allowed_values is not None and value not in rule.allowed_values:
            errors.append(
                f"Field '{rule.name}' has value {value!r}, "
                f"expected one of {rule.allowed_values}."
            )

    status = Status.FAIL if errors else Status.PASS
    return ValidationResult(status=status, errors=errors, warnings=warnings)


def validate_json_output(raw: str, required_keys: list[str]) -> ValidationResult:
    """Convenience wrapper â€” validate that a JSON object has all required keys."""
    schema = OutputSchema(
        required_fields=[FieldRule(name=k) for k in required_keys],
    )
    return validate_output(raw, schema)

