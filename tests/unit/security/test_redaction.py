"""Deterministic and property-based tests for recursive redaction."""

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from toolwatch.domain.common import JSONValue
from toolwatch.security.redaction import DeterministicRedactor, RedactionLimitExceeded

KEY = "unit-test-redaction-fingerprint-key"


def redactor(**overrides: object) -> DeterministicRedactor:
    values: dict[str, object] = {"fingerprint_key": KEY}
    values.update(overrides)
    return DeterministicRedactor(**values)  # type: ignore[arg-type]


def test_sensitive_keys_nested_values_and_similar_names() -> None:
    raw: JSONValue = {
        "apiKey": "alpha-secret",
        "nested": [{"password": "beta-secret"}],
        "monkey": "kept",
        "keyboard": "kept",
        "foreign_key": "kept",
        "empty_secret": "",
    }

    result = redactor().redact(raw)

    assert result.value == {
        "apiKey": "[REDACTED]",
        "nested": [{"password": "[REDACTED]"}],
        "monkey": "kept",
        "keyboard": "kept",
        "foreign_key": "kept",
        "empty_secret": "",
    }
    assert "alpha-secret" not in repr(result)
    assert "beta-secret" not in repr(result)


@pytest.mark.parametrize(
    "value",
    [
        "Authorization failed for Bearer abcdef123456",
        "Basic dXNlcjpwYXNzd29yZA==",
        "aaaabbbb.ccccdddd.eeeeffff",
        "-----BEGIN PRIVATE KEY-----\nprivate-material",
        "https://username:password@example.com/path",
    ],
)
def test_value_patterns_remove_secret(value: str) -> None:
    result = redactor().redact({"message": value})

    assert result.findings
    assert value not in json.dumps(result.value)
    assert all(value not in repr(finding) for finding in result.findings)


def test_repeated_secret_has_stable_hmac_and_redaction_is_idempotent() -> None:
    first = redactor().redact({"token": "same-secret", "other": "Bearer same-secret"})
    second = redactor().redact(first.value)

    fingerprints = {
        finding.fingerprint for finding in first.findings if finding.fingerprint is not None
    }
    assert len(fingerprints) == 1
    assert second.value == first.value


def test_depth_and_node_limits_are_fail_closed() -> None:
    with pytest.raises(RedactionLimitExceeded):
        redactor(max_depth=1).redact({"a": {"b": "value"}})
    with pytest.raises(RedactionLimitExceeded):
        redactor(max_nodes=2).redact({"a": 1, "b": 2})


json_scalars = (
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(
        allow_nan=False,
        allow_infinity=False,
    )
    | st.text(max_size=30)
)
json_values: st.SearchStrategy[JSONValue] = st.recursive(
    json_scalars,
    lambda children: (
        st.lists(children, max_size=4)
        | st.dictionaries(st.text(min_size=1, max_size=10), children, max_size=4)
    ),
    max_leaves=30,
)


@given(json_values)
def test_redaction_properties(value: JSONValue) -> None:
    service = redactor(max_depth=20, max_nodes=1000)
    first = service.redact(value)
    second = service.redact(first.value)

    assert second.value == first.value
    json.dumps(first.value, allow_nan=False)
