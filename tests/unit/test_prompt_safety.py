"""Tests for the temporary prompt persistence boundary."""

from toolwatch.security.prompt import REDACTED, prepare_prompt_for_storage


def test_prompt_storage_is_disabled_by_default() -> None:
    prompt = "Authorization: Bearer raw-test-token"

    assert prepare_prompt_for_storage(prompt, store_prompts=False) is None


def test_enabled_prompt_storage_redacts_obvious_secrets() -> None:
    prompt = "token=raw-test-token and Bearer another-test-token"

    sanitized = prepare_prompt_for_storage(prompt, store_prompts=True)

    assert sanitized is not None
    assert "raw-test-token" not in sanitized
    assert "another-test-token" not in sanitized
    assert REDACTED in sanitized
