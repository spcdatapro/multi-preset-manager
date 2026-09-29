import json

import pytest

from usr.plugins.multi_preset_manager.helpers.diff import MASK, effective_changes, redact

import mpr_samples as s


@pytest.mark.parametrize(
    "key", ["api_key", "kwargs.api_key", "Authorization", "kwargs.token", "access_token", "client_secret",
            "password", "x-api-key", "kwargs.key", "private_key", "cookie"],
)
def test_sensitive_keys_are_masked(key):
    assert redact(key, s.SECRET) == MASK


@pytest.mark.parametrize("key", ["max_tokens", "kwargs.max_tokens", "temperature", "thinking", "budget_tokens", "name"])
def test_ordinary_keys_are_shown(key):
    assert redact(key, 123) == 123


def test_nested_values_are_masked_by_their_own_keys():
    value = {"extra_headers": {"Authorization": f"Bearer {s.SECRET}", "X-Trace": "on"}, "n": [{"api_key": s.SECRET}]}
    shown = redact("kwargs.extra_body", value)
    assert s.SECRET not in json.dumps(shown)
    assert shown["extra_headers"]["X-Trace"] == "on"


def test_urls_lose_credentials_and_query():
    shown = redact("api_base", f"https://user:{s.SECRET}@host.example:8443/v1?token={s.SECRET}")
    assert shown == "https://host.example:8443/v1"
    assert redact("api_base", "http://localhost:11434") == "http://localhost:11434"
    assert redact("api_base", None) is None


def cfg(**chat):
    return {"chat_model": chat, "utility_model": {}, "embedding_model": {}, "vision_model": {}}


def test_effective_changes_lists_fields_and_flattens_kwargs():
    before = cfg(name="a", ctx_length=1, kwargs={"top_p": 0.5, "same": 1})
    after = cfg(name="b", ctx_length=1, kwargs={"top_p": 0.7, "same": 1, "new": True})
    assert effective_changes(before, after) == [
        {"slot": "chat", "field": "kwargs.new", "before": None, "after": True},
        {"slot": "chat", "field": "kwargs.top_p", "before": 0.5, "after": 0.7},
        {"slot": "chat", "field": "name", "before": "a", "after": "b"},
    ]


def test_missing_and_empty_values_are_the_same_but_zero_is_not():
    assert effective_changes(cfg(api_base=""), cfg()) == []
    assert effective_changes(cfg(rl_input=0), cfg()) != []


def test_api_key_never_appears_in_changes():
    changes = effective_changes(cfg(api_key="old"), cfg(api_key="new"))
    assert changes == []


def test_sensitive_kwargs_changes_show_masked_values():
    changes = effective_changes(cfg(kwargs={"api_key": "old-secret"}), cfg(kwargs={"api_key": s.SECRET}))
    assert changes == [{"slot": "chat", "field": "kwargs.api_key", "before": MASK, "after": MASK}]
