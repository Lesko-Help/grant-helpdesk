"""
Proof for followup_cache.load_followup_statuses — see
docs/briefs/coach-inbox-dialog-history.md, Context (the measured ~2s per
BigQuery round trip).

tab_main used to call bq_client.get_followup_statuses directly, with no
st.cache_data around it, so it re-paid that BigQuery round trip on every
single script rerun of the Tickets tab — including the rerun that opens
either dialog. This drives the real followup_cache.load_followup_statuses
(the exact function app.py imports and calls), with bq_client.get_followup_
statuses monkeypatched to a fake that only counts how many times it
actually ran, across repeated st.rerun()-like AppTest.run() calls of the
same script. Removing the module's @st.cache_data decorator must turn
this red — see the "prove it can go red" note below each test.
"""

import streamlit as st
from streamlit.testing.v1 import AppTest

import bq_client
import followup_cache


def _script(content_ids):
    import followup_cache
    followup_cache.load_followup_statuses(tuple(content_ids))


# The cache key is global by source-hash+args, so tests reusing the same
# ids as each other need a clear() up front — test isolation only, not the
# app's own runtime code (the brief rules out a blanket clear there, not
# here).

def test_calls_bigquery_once_across_repeated_reruns_with_the_same_ids(monkeypatch):
    st.cache_data.clear()
    calls = []
    monkeypatch.setattr(
        bq_client, "get_followup_statuses", lambda ids: calls.append(tuple(ids)) or {}
    )

    at = AppTest.from_function(_script, args=(["c1", "c2"],))
    at.run()
    at.run()
    at.run()

    # Proven red: with @st.cache_data removed from
    # followup_cache.load_followup_statuses, this becomes 3, not 1.
    assert list(at.exception) == []
    assert len(calls) == 1


def test_calls_bigquery_again_for_a_different_set_of_ids(monkeypatch):
    # A cache keyed on the ids means a coach switching filters to a
    # different page of tickets still gets a fresh (if freshly-cached)
    # answer, rather than always reusing the very first page's result.
    st.cache_data.clear()
    calls = []
    monkeypatch.setattr(
        bq_client, "get_followup_statuses", lambda ids: calls.append(tuple(ids)) or {}
    )

    at = AppTest.from_function(_script, args=(["c1", "c2"],))
    at.run()
    at2 = AppTest.from_function(_script, args=(["c3"],))
    at2.run()

    assert list(at.exception) == [] and list(at2.exception) == []
    assert len(calls) == 2
