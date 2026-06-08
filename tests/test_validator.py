"""Tests for the AI output validator."""

import json
import pytest

from src.validator import (
    FieldRule,
    OutputSchema,
    Status,
    validate_json_output,
    validate_output,
)


def _json(obj: dict) -> str:
    return json.dumps(obj)


# â”€â”€ JSON parse â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_invalid_json_returns_fail():
    result = validate_output("not json", OutputSchema())
    assert result.status == Status.FAIL
    assert any("JSON" in e for e in result.errors)


def test_json_array_returns_fail():
    result = validate_output("[1, 2]", OutputSchema())
    assert result.status == Status.FAIL


# â”€â”€ Placeholder detection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_unfilled_placeholder_returns_blocked():
    result = validate_output(
        _json({"body_html": "<p>{{DESCRIPTION}}</p>", "tags": []}),
        OutputSchema(forbid_placeholders=True),
    )
    assert result.status == Status.BLOCKED
    assert "{{DESCRIPTION}}" in result.errors[0]


def test_placeholder_check_disabled():
    schema = OutputSchema(forbid_placeholders=False)
    result = validate_output(
        _json({"key": "{{PLACEHOLDER}}"}),
        schema,
    )
    assert result.status == Status.PASS


# â”€â”€ Required fields â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_missing_required_field():
    schema = OutputSchema(required_fields=[FieldRule(name="body_html", type=str)])
    result = validate_output(_json({"tags": ["a"]}), schema)
    assert result.status == Status.FAIL
    assert any("body_html" in e for e in result.errors)


def test_wrong_type_fails():
    schema = OutputSchema(required_fields=[FieldRule(name="tags", type=list)])
    result = validate_output(_json({"tags": "not-a-list"}), schema)
    assert result.status == Status.FAIL


def test_nullable_field_accepts_none():
    schema = OutputSchema(
        required_fields=[FieldRule(name="description", type=str, nullable=True)]
    )
    result = validate_output(_json({"description": None}), schema)
    assert result.status == Status.PASS


def test_allowed_values_enforced():
    schema = OutputSchema(
        required_fields=[
            FieldRule(name="status", allowed_values=["PASS", "FAIL", "BLOCKED"])
        ]
    )
    result = validate_output(_json({"status": "UNKNOWN"}), schema)
    assert result.status == Status.FAIL


def test_allowed_values_accepted():
    schema = OutputSchema(
        required_fields=[
            FieldRule(name="status", allowed_values=["PASS", "FAIL", "BLOCKED"])
        ]
    )
    result = validate_output(_json({"status": "PASS"}), schema)
    assert result.status == Status.PASS


# â”€â”€ validate_json_output convenience â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_validate_json_output_all_keys_present():
    result = validate_json_output(
        _json({"body_html": "<p>Hi</p>", "tags": ["a"]}),
        required_keys=["body_html", "tags"],
    )
    assert result.ok


def test_validate_json_output_key_missing():
    result = validate_json_output(
        _json({"body_html": "<p>Hi</p>"}),
        required_keys=["body_html", "tags"],
    )
    assert not result.ok

