"""
Cached wrapper around bq_client.get_followup_statuses — see
docs/briefs/coach-inbox-dialog-history.md (root cause section).

tab_main used to call bq_client.get_followup_statuses directly, with no
st.cache_data around it, so it paid a live BigQuery round trip (~2s
measured) on every single script rerun of the Tickets tab, including the
rerun that opens either dialog — every other loader on that path was
already cached, this one alone was not. Pulled into its own module (like
member_history.py and reply_form.py) so a test can import and call the
exact function app.py uses, rather than a re-typed copy that could drift
out of sync with the decorator it's supposed to be testing.
"""

import streamlit as st

import bq_client


@st.cache_data(ttl=300, show_spinner=False)
def load_followup_statuses(content_ids: tuple) -> dict:
    """
    Input: a tuple of ticket content_ids (a tuple, not the list
    bq_client.get_followup_statuses itself takes, because st.cache_data
    hashes its arguments and a list isn't hashable).
    Output: dict of content_id -> follow-up status, straight from
    bq_client.get_followup_statuses.
    Why cached: so the Tickets tab's other reruns — including opening
    either the regular Ticket dialog or the Answer dialog — don't re-pay
    this BigQuery round trip every single time.
    """
    return bq_client.get_followup_statuses(list(content_ids))
