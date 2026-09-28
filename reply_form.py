"""
The coach-inbox reply form's submit callback (app.py's Tickets tab).

Pulled out of app.py so it can be exercised by a real Streamlit widget test
(streamlit.testing.v1.AppTest) without app.py's login gate and BigQuery
loaders getting in the way — see tests/test_reply_form.py. app.py imports
and calls on_reply_submit directly; nothing in this file talks to BigQuery
itself, the caller always passes that in (lookup_author, add_reply,
clear_cache), which is also what lets the test use fakes.
"""

import streamlit as st

import coach_inbox


def reply_result_message(result):
    """
    Input: a coach_inbox.ReplyResult.
    Output: the st.error() text to show for it, or None for OK (nothing to
    show — the box already cleared and the row refreshes on its own).
    Why: a dead thread, a refused send and a real outage each mean
    something different to the coach, so each gets its own words instead
    of one generic "try again" for everything.
    """
    if result is coach_inbox.ReplyResult.OK:
        return None
    if result is coach_inbox.ReplyResult.UNKNOWN_THREAD:
        return "This conversation could not be found — it may have been removed."
    if result is coach_inbox.ReplyResult.REFUSED:
        return "Your reply could not be sent — check the text and try again."
    return "Could not send the reply. Please try again."


def on_reply_submit(thread_id, body_key, result_key, current_user, lookup_author, add_reply, clear_cache):
    """
    Input: the thread's id; the text_area widget's own session_state key;
    a session_state key to stash the outcome message in for the main script
    body to show; the logged-in coach's email; and three callables (author
    lookup, the actual write, the cache to clear on success) so app.py can
    pass the real bq_client/coach_inbox/load_member_questions and a test can
    pass fakes.
    Output: none — writes the outcome into session_state[result_key], and on
    success also clears session_state[body_key].
    Why this runs as an on_click callback rather than inline code after the
    button check: a widget can only have its own session_state key written
    before that widget is instantiated in the current run. form_submit_button
    calls on_click before the rest of the script (and its widgets) runs, so
    this is the one place allowed to reset the text_area — resetting it
    after the button check, in the script body, raises StreamlitAPIException
    on every successful send, because by then the text_area already exists.
    """
    body = st.session_state.get(body_key, "")
    if not body.strip():
        st.session_state[result_key] = "Please type a reply before sending."
        return
    author_id = lookup_author(current_user) if current_user else None
    if author_id is None:
        st.session_state[result_key] = "Could not identify your coach profile — ask an admin to link your login."
        return
    result = add_reply(thread_id, author_id, body)
    st.session_state[result_key] = reply_result_message(result)
    if result is coach_inbox.ReplyResult.OK:
        st.session_state[body_key] = ""
        clear_cache()
