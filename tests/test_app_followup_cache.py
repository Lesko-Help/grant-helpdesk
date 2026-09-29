"""
Proof for app.py's load_followup_statuses caching fix — see
docs/briefs/coach-inbox-dialog-history.md, Context (the measured ~2s per
BigQuery round trip).

tab_main used to call bq_client.get_followup_statuses directly, with no
st.cache_data around it, so it re-paid that BigQuery round trip on every
single script rerun of the Tickets tab — including the rerun that opens
either dialog. app.py itself can't run under AppTest (its own login gate
and live loaders), so this reproduces just the two shapes — the old,
uncached call and the new cached wrapper — against a fake, in-process
"BigQuery call" that only counts how many times it actually ran, across
repeated st.rerun()-like AppTest.run() calls of the same script.
"""

import streamlit as st
from streamlit.testing.v1 import AppTest


def _old_uncached_shape(calls, content_ids):
    import streamlit as st

    def _fake_get_followup_statuses(ids):
        calls.append(tuple(ids))
        return {}

    st.session_state["runs"] = st.session_state.get("runs", 0) + 1
    _fake_get_followup_statuses(content_ids)


def _new_cached_shape(calls, content_ids):
    import streamlit as st

    def _fake_get_followup_statuses(ids):
        calls.append(tuple(ids))
        return {}

    @st.cache_data(ttl=300, show_spinner=False)
    def _load_followup_statuses(ids: tuple):
        return _fake_get_followup_statuses(list(ids))

    st.session_state["runs"] = st.session_state.get("runs", 0) + 1
    _load_followup_statuses(tuple(content_ids))


# ── red: the old shape really did re-run the BigQuery call every rerun ─────

def test_old_uncached_shape_calls_bigquery_on_every_single_rerun():
    calls = []
    at = AppTest.from_function(_old_uncached_shape, args=(calls, ["c1", "c2"]))
    at.run()
    at.run()
    at.run()

    assert list(at.exception) == []
    assert at.session_state["runs"] == 3
    assert len(calls) == 3


# ── green: the cached wrapper hits it once across the same reruns ──────────
#
# st.cache_data's cache is process-global, keyed by the decorated function's
# own source code plus its arguments — since every test below redefines an
# identically-worded _load_followup_statuses, two tests calling it with the
# same ids would otherwise share one cache entry across tests that have
# nothing to do with each other. st.cache_data.clear() up front is test
# isolation, not the app's own runtime code, so this is not the blanket
# clear the brief rules out for app.py itself.

def test_cached_wrapper_calls_bigquery_once_across_repeated_reruns_with_the_same_ids():
    st.cache_data.clear()
    calls = []
    at = AppTest.from_function(_new_cached_shape, args=(calls, ["c1", "c2"]))
    at.run()
    at.run()
    at.run()

    assert list(at.exception) == []
    assert at.session_state["runs"] == 3
    assert len(calls) == 1


def test_cached_wrapper_calls_bigquery_again_for_a_different_set_of_ids():
    # A cache keyed on the ids means a coach switching filters to a
    # different page of tickets still gets a fresh (if freshly-cached)
    # answer, rather than always reusing the very first page's result.
    st.cache_data.clear()
    calls = []
    at = AppTest.from_function(_new_cached_shape, args=(calls, ["c1", "c2"]))
    at.run()
    at2 = AppTest.from_function(_new_cached_shape, args=(calls, ["c3"]))
    at2.run()

    assert list(at.exception) == [] and list(at2.exception) == []
    assert len(calls) == 2
