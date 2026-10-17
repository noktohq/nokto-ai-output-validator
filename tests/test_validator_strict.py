"""Regression tests for stricter field semantics in validate_output.

Covers: missing key vs null, bool vs int/float, non-finite numbers,
type-aware enum membership, list item types and the README contract.
"""

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


def _schema(*rules: FieldRule) -> OutputSchema:
    return OutputSchema(required_fields=list(rules))


# ── Missing key vs null ──────────────────────────────────────────────────────


def test_nullable_field_missing_key_fails():
    schema = _schema(FieldRule(name="description", type=str, nullable=True))
    result = validate_output(_json({"other": 1}), schema)
    assert result.status == Status.FAIL
    assert any("Missing required field 'description'" in e for e in result.errors)


def test_nullable_field_null_passes():
    schema = _schema(FieldRule(name="description", type=str, nullable=True))
    assert validate_output(_json({"description": None}), schema).ok


def test_non_nullable_field_null_fails_with_null_message():
    schema = _schema(FieldRule(name="body_html", type=str))
    result = validate_output(_json({"body_html": None}), schema)
    assert result.status == Status.FAIL
    assert any("'body_html'" in e and "null" in e for e in result.errors)


def test_non_nullable_field_missing_key_fails():
    schema = _schema(FieldRule(name="body_html", type=str))
    result = validate_output(_json({}), schema)
    assert result.status == Status.FAIL
    assert any("Missing required field 'body_html'" in e for e in result.errors)


def test_optional_field_may_be_missing():
    schema = _schema(FieldRule(name="note", type=str, required=False))
    assert validate_output(_json({}), schema).ok


def test_optional_field_is_still_type_checked_when_present():
    schema = _schema(FieldRule(name="note", type=str, required=False))
    assert not validate_output(_json({"note": 5}), schema).ok


# ── bool vs int / float ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "expected, value, ok",
    [
        (int, 3, True),
        (int, True, False),
        (int, False, False),
        (int, 1.0, False),
        (float, 1.5, True),
        (float, True, False),
        (bool, True, True),
        (bool, 1, False),
        ((int, float), 2, True),
        ((int, float), 2.5, True),
        ((int, float), True, False),
        ((int, bool), True, True),
        (object, True, True),
    ],
)
def test_numeric_types_and_bool(expected, value, ok):
    schema = _schema(FieldRule(name="n", type=expected))
    result = validate_output(_json({"n": value}), schema)
    assert result.ok is ok, result.errors


def test_tuple_type_error_message_does_not_crash():
    schema = _schema(FieldRule(name="n", type=(int, float)))
    result = validate_output(_json({"n": "x"}), schema)
    assert result.status == Status.FAIL
    assert any("int | float" in e for e in result.errors)


# ── Non-finite and out-of-range numbers ──────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        '{"price": NaN}',
        '{"price": Infinity}',
        '{"price": -Infinity}',
        '{"prices": [1, NaN]}',
        '{"meta": {"score": Infinity}}',
        '{"price": 1e400}',
        '{"price": -1e400}',
    ],
)
def test_non_finite_numbers_fail(raw):
    result = validate_output(raw, OutputSchema())
    assert result.status == Status.FAIL
    assert any("Invalid JSON" in e for e in result.errors)


def test_finite_float_passes():
    schema = _schema(FieldRule(name="price", type=float))
    assert validate_output('{"price": 1.5e10}', schema).ok


def test_oversized_integer_fails_instead_of_raising():
    raw = '{"qty": ' + "1" * 5000 + "}"
    result = validate_output(raw, OutputSchema())
    assert result.status == Status.FAIL


def test_deeply_nested_json_fails_instead_of_raising():
    raw = '{"a": ' + "[" * 200_000 + "]" * 200_000 + "}"
    result = validate_output(raw, OutputSchema())
    assert result.status == Status.FAIL


# ── Enum membership is type-aware ────────────────────────────────────────────


@pytest.mark.parametrize(
    "allowed, value, ok",
    [
        ([0, 1], 1, True),
        ([0, 1], True, False),
        ([0, 1], False, False),
        ([True, False], True, True),
        ([True, False], 1, False),
        ([True, False], 0, False),
        (["PASS", "FAIL"], "PASS", True),
        (["PASS", "FAIL"], "pass", False),
        ([Status.PASS, Status.FAIL], "PASS", True),
    ],
)
def test_allowed_values_are_type_aware(allowed, value, ok):
    schema = _schema(FieldRule(name="status", allowed_values=allowed))
    result = validate_output(_json({"status": value}), schema)
    assert result.ok is ok, result.errors


def test_allowed_values_combined_with_type():
    schema = _schema(FieldRule(name="status", type=str, allowed_values=["A", "B"]))
    assert not validate_output(_json({"status": 1}), schema).ok
    assert validate_output(_json({"status": "A"}), schema).ok


# ── Lists and objects ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "expected, value, ok",
    [
        (list, [], True),
        (list, {}, False),
        (list, "a,b", False),
        (dict, {"a": 1}, True),
        (dict, [], False),
    ],
)
def test_list_and_object_types(expected, value, ok):
    schema = _schema(FieldRule(name="v", type=expected))
    assert validate_output(_json({"v": value}), schema).ok is ok


@pytest.mark.parametrize(
    "value, ok",
    [
        (["a", "b"], True),
        ([], True),
        ([1], False),
        (["a", None], False),
        (["a", ["b"]], False),
        ("a,b", False),
    ],
)
def test_item_type_str(value, ok):
    schema = _schema(FieldRule(name="tags", type=list, item_type=str))
    result = validate_output(_json({"tags": value}), schema)
    assert result.ok is ok, result.errors


def test_item_type_int_rejects_bool_items():
    schema = _schema(FieldRule(name="qty", type=list, item_type=int))
    result = validate_output(_json({"qty": [1, True]}), schema)
    assert result.status == Status.FAIL
    assert any("qty[1]" in e for e in result.errors)


# ── Backward-compatible output ───────────────────────────────────────────────


def test_readme_schema_accepts_valid_output():
    schema = OutputSchema(
        required_fields=[
            FieldRule(name="body_html", type=str),
            FieldRule(name="tags", type=list),
            FieldRule(name="status", allowed_values=["COMPLETED", "BLOCKED"]),
        ],
        forbid_placeholders=True,
    )
    raw = _json(
        {
            "body_html": "<p>Sykkel</p>",
            "tags": ["sykkel", "el"],
            "status": "COMPLETED",
            "extra": {"price": 9999.0, "qty": 4, "in_stock": True},
        }
    )
    result = validate_output(raw, schema)
    assert result.status == Status.PASS
    assert result.errors == []


def test_field_rule_positional_arguments_unchanged():
    rule = FieldRule("status", str, ["A"], True)
    assert (rule.name, rule.type, rule.allowed_values, rule.nullable) == (
        "status",
        str,
        ["A"],
        True,
    )
    assert rule.required is True
    assert rule.item_type is None


def test_validate_json_output_null_value_still_fails():
    result = validate_json_output(_json({"title": None}), required_keys=["title"])
    assert not result.ok
