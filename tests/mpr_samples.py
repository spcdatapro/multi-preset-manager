"""Synthetic presets for the tests. Never real data.

Values are chosen so that nothing equals the framework's implicit defaults (128000 / 0.7 / 0 ...),
which validate_presets strips from non-Default presets, unless a test wants exactly that.
"""

from copy import deepcopy

SECRET = "S3CRET-tok-123"


def default_preset() -> dict:
    return {
        "name": "Default",
        "chat": {
            "provider": "anthropic", "name": "big-1", "api_base": "", "ctx_length": 200000,
            "ctx_history": 0.75, "vision": True, "max_embeds": 10,
            "rl_requests": 0, "rl_input": 0, "rl_output": 0, "kwargs": {"max_tokens": 4000},
        },
        "utility": {
            "provider": "anthropic", "name": "small-1", "api_base": "", "ctx_length": 150000,
            "ctx_input": 0.6, "rl_requests": 0, "rl_input": 0, "rl_output": 0,
            "kwargs": {"temperature": 0.2},
        },
        "embedding": {"provider": "huggingface", "name": "emb-1", "api_base": "", "rl_requests": 0, "rl_input": 0},
    }


def source_preset() -> dict:
    return {
        "name": "Source",
        "chat": {
            "provider": "anthropic", "name": "big-2", "api_base": "https://proxy.example/v1",
            "ctx_length": 300000, "ctx_history": 0.5, "vision": False, "max_embeds": 3,
            "rl_requests": 5, "rl_input": 6, "rl_output": 7,
            "kwargs": {"thinking": {"type": "enabled"}, "max_tokens": 9000},
        },
        "utility": {
            "provider": "anthropic", "name": "small-2", "api_base": "https://proxy.example/u",
            "ctx_length": 64000, "ctx_input": 0.4, "rl_requests": 1, "rl_input": 2, "rl_output": 3,
            "kwargs": {"temperature": 0.9},
        },
        "embedding": {
            "provider": "huggingface", "name": "emb-2", "api_base": "https://emb.example",
            "rl_requests": 8, "rl_input": 9, "kwargs": {"normalize": True},
        },
        # "vision": True is left out on purpose: the framework strips it as an implicit default
        "vision": {"provider": "anthropic", "name": "vis-1", "max_embeds": 4,
                   "timeout": 100, "max_tokens": 500, "override_main": True},
    }


def target_preset(name: str = "Target") -> dict:
    return {
        "name": name,
        "chat": {
            "provider": "anthropic", "name": "big-3", "api_base": "https://old.example",
            "ctx_length": 111000, "ctx_history": 0.9, "vision": True, "max_embeds": 1,
            "rl_requests": 11, "rl_input": 12, "rl_output": 13, "kwargs": {"top_p": 0.5},
        },
        "utility": {
            "provider": "anthropic", "name": "small-3", "api_base": "https://old.example/u",
            "ctx_length": 32000, "ctx_input": 0.3, "rl_requests": 21, "rl_input": 22, "rl_output": 23,
            "kwargs": {"temperature": 0.1},
        },
        "embedding": {
            "provider": "huggingface", "name": "emb-3", "api_base": "https://old.example/e",
            "rl_requests": 31, "rl_input": 32, "kwargs": {"device": "cpu"},
        },
    }


def lean_preset() -> dict:
    """Only sets its main model: everything else is inherited from Default."""
    return {"name": "Lean", "chat": {"provider": "anthropic", "name": "lean-1"}}


def standard() -> list[dict]:
    return deepcopy([default_preset(), source_preset(), target_preset()])
