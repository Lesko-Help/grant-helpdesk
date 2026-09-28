"""
Offline proof for config.py's env-overridable PRIVATE_CHAT_DATASET — see
docs/briefs/coach-inbox-drill.md and docs/specs/modules/coach_inbox.md (R1).

config is read at import time, so each case here sets or clears the env var
and then reloads the module to see the effect; monkeypatch undoes the env
change automatically at the end of the test, but the module itself stays
reloaded with whatever it last saw — so the last thing every test here does
is reload config again with the env var back to unset, restoring the default
for every test file imported after this one.
"""

import importlib

import config


def test_private_chat_dataset_env_override(monkeypatch):
    # Input: no PRIVATE_CHAT_DATASET in the environment. Output: the module
    # keeps today's hardcoded default — an unset override must change nothing.
    monkeypatch.delenv("PRIVATE_CHAT_DATASET", raising=False)
    importlib.reload(config)
    assert config.PRIVATE_CHAT_DATASET == "lesko-486515.private_chat"

    # Input: PRIVATE_CHAT_DATASET set to a throwaway, non-existent dataset —
    # the value the overseer's fire drill will use. Output: the module picks
    # it up on reload, so the live service can be pointed at a missing
    # dataset without a code change.
    monkeypatch.setenv("PRIVATE_CHAT_DATASET", "no-such-project.no-such-dataset")
    importlib.reload(config)
    assert config.PRIVATE_CHAT_DATASET == "no-such-project.no-such-dataset"

    # Restore: reload once more with the env var unset again, so any test
    # file imported after this one still sees the real default.
    monkeypatch.delenv("PRIVATE_CHAT_DATASET", raising=False)
    importlib.reload(config)
    assert config.PRIVATE_CHAT_DATASET == "lesko-486515.private_chat"
