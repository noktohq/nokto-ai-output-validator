"""
AI output validator.

Validates structured output from LLM calls — checks JSON shape, required fields,
enum values, and detects unfilled template placeholders before the output is used.
"""

from __future__ import annotations

import json
import math
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
    """Declares a field in an AI output dict.

    - ``required``: the key must be present (default). ``required=False``
      allows the key to be absent; a present value is still checked.
    - ``nullable``: the value may be JSON ``null``. It does not make the key
      optional — a missing key still fails unless ``required=False``.
    - ``type``: expected Python type (or tuple of types). ``bool`` is only
      accepted when ``bool`` (or ``object``) is listed explicitly, so
      ``type=int`` / ``type=float`` reject ``true``/``false``.
    - ``allowed_values``: enum check; ``true``/``false`` only match booleans.
    - ``item_type``: when set, the value must be a JSON array whose items all
      match this type (same bool rule as ``type``).
    """

    name: str
    type: type | tuple[type, ...] | None = None
    allowed_values: list[Any] | None = None
    nullable: bool = False
    required: bool = True
    item_type: type | tuple[type, ...] | None = None


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


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-finite number {name} is not valid JSON")


def _parse_finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"number {text} is out of range")
    return value


def _loads(raw: str | bytes) -> Any:
    """json.loads that rejects NaN, Infinity and floats that overflow to inf."""
    return json.loads(
        raw,
        parse_constant=_reject_constant,
        parse_float=_parse_finite_float,
    )


def _type_name(expected: type | tuple[type, ...]) -> str:
    if isinstance(expected, tuple):
        return " | ".join(_type_name(t) for t in expected)
    return getattr(expected, "__name__", repr(expected))


def _bool_allowed(expected: type | tuple[type, ...]) -> bool:
    types = expected if isinstance(expected, tuple) else (expected,)
    return any(t is bool or t is object for t in types)


def _matches_type(value: Any, expected: type | tuple[type, ...]) -> bool:
    if not isinstance(value, expected):
        return False
    # bool is a subclass of int in Python; JSON true/false is not a number.
    if isinstance(value, bool) and not _bool_allowed(expected):
        return False
    return True


def _is_allowed(value: Any, allowed_values: list[Any]) -> bool:
    for allowed in allowed_values:
        # True == 1 and False == 0 in Python; keep booleans and numbers apart.
        if isinstance(value, bool) != isinstance(allowed, bool):
            continue
        if value == allowed:
            return True
    return False


def validate_output(
    raw: str,
    schema: OutputSchema,
) -> ValidationResult:
    """
    Validate a raw JSON string against an OutputSchema.

    Returns a ValidationResult. Sets status to FAIL if the JSON is invalid
    (including NaN/Infinity or numbers outside the float range), or if a
    required field is missing, null without ``nullable=True``, or has the
    wrong type/value. Sets BLOCKED if the output contains unfilled
    {{PLACEHOLDER}} tokens.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Parse JSON
    try:
        data = _loads(raw)
    except (ValueError, RecursionError) as exc:
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
        if rule.name not in data:
            if rule.required:
                errors.append(f"Missing required field '{rule.name}'.")
            continue

        value = data[rule.name]

        if value is None:
            if not rule.nullable:
                errors.append(f"Field '{rule.name}' is null but not nullable.")
            continue

        if rule.type is not None and not _matches_type(value, rule.type):
            errors.append(
                f"Field '{rule.name}' must be {_type_name(rule.type)}, "
                f"got {type(value).__name__}."
            )
            continue

        if rule.item_type is not None:
            if not isinstance(value, list):
                errors.append(
                    f"Field '{rule.name}' must be list, got {type(value).__name__}."
                )
                continue
            bad_items = [
                f"Field '{rule.name}[{i}]' must be {_type_name(rule.item_type)}, "
                f"got {type(item).__name__}."
                for i, item in enumerate(value)
                if not _matches_type(item, rule.item_type)
            ]
            if bad_items:
                errors.extend(bad_items)
                continue

        if rule.allowed_values is not None and not _is_allowed(
            value, rule.allowed_values
        ):
            errors.append(
                f"Field '{rule.name}' has value {value!r}, "
                f"expected one of {rule.allowed_values}."
            )

    status = Status.FAIL if errors else Status.PASS
    return ValidationResult(status=status, errors=errors, warnings=warnings)


def validate_json_output(raw: str, required_keys: list[str]) -> ValidationResult:
    """Convenience wrapper — validate that a JSON object has all required keys."""
    schema = OutputSchema(
        required_fields=[FieldRule(name=k) for k in required_keys],
    )
    return validate_output(raw, schema)
