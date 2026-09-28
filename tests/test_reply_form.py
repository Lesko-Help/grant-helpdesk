"""
Real-widget proof for reply_form.on_reply_submit (app.py's Tickets tab reply
box) — see docs/briefs/coach-inbox-reply.md's re-review blocker on 745ea00.

Uses streamlit.testing.v1.AppTest to run an actual text_area + form +
form_submit_button, the same shape app.py wires up, with a fake add_reply so
this never touches BigQuery or Dataform. Running real widgets (not just
calling on_reply_submit as a plain function) matters because the bug this
proves fixed is a Streamlit timing rule — writing a widget's own
session_state key after that widget was instantiated in the same run raises
StreamlitAPIException — and only a live AppTest run can catch that.

app.py itself is not used here: its login gate (st.user.is_logged_in) and
its BigQuery-backed loaders make it impossible to run under AppTest without
either a live login or reaching real BigQuery, so this exercises the
reply_form module app.py imports and calls, the same way
test_coach_inbox_reply.py exercises add_coach_reply with a fake client
instead of going through app.py.
"""

from streamlit.testing.v1 import AppTest

import coach_inbox


def _old_buggy_script(add_reply_result):
    # The pre-fix app.py shape: session_state written in the script body,
    # after the button check, once the widget it belongs to already exists
    # this run — kept here only to prove the exception it used to raise.
    import streamlit as st
    import coach_inbox

    with st.form("reply_form", clear_on_submit=False):
        st.text_area("Reply", key="reply_body", label_visibility="collapsed")
        sent = st.form_submit_button("Send reply")
    if sent:
        if add_reply_result is coach_inbox.ReplyResult.OK:
            st.session_state["reply_body"] = ""


def _fixed_script(add_reply_result, lookup_result):
    import streamlit as st

    import reply_form

    st.session_state.setdefault("calls", [])

    def _add_reply(thread_id, author_id, body):
        st.session_state["calls"].append((thread_id, author_id, body))
        return add_reply_result

    def _lookup(email):
        return lookup_result

    def _clear_cache():
        st.session_state["cache_cleared"] = True

    with st.form("reply_form", clear_on_submit=False):
        st.text_area("Reply", key="reply_body", label_visibility="collapsed")
        st.form_submit_button(
            "Send reply",
            on_click=reply_form.on_reply_submit,
            args=(
                "th1", "reply_body", "reply_result", "coach@example.com",
                _lookup, _add_reply, _clear_cache,
            ),
        )
    msg = st.session_state.pop("reply_result", None)
    if msg:
        st.error(msg)


# ── red: the pre-fix shape really did raise on a successful send ───────────

def test_old_inline_reset_after_the_button_check_raises_streamlit_api_exception():
    at = AppTest.from_function(_old_buggy_script, args=(coach_inbox.ReplyResult.OK,))
    at.run()
    at.text_area[0].set_value("hello there").run()
    at.button[0].click().run()

    assert len(at.exception) == 1
    assert "cannot be modified after the widget" in str(at.exception[0].value)


# ── green: the callback shape sends, clears the box, and raises nothing ────

def test_on_reply_submit_success_clears_the_box_and_raises_no_exception():
    at = AppTest.from_function(_fixed_script, args=(coach_inbox.ReplyResult.OK, 42))
    at.run()
    at.text_area[0].set_value("hello there").run()
    at.button[0].click().run()

    assert list(at.exception) == []
    assert at.session_state["calls"] == [("th1", 42, "hello there")]
    assert at.session_state["cache_cleared"] is True
    assert at.text_area[0].value == ""
    assert list(at.error) == []


def test_on_reply_submit_unknown_thread_keeps_the_typed_text_and_shows_its_own_message():
    at = AppTest.from_function(_fixed_script, args=(coach_inbox.ReplyResult.UNKNOWN_THREAD, 42))
    at.run()
    at.text_area[0].set_value("still here").run()
    at.button[0].click().run()

    assert list(at.exception) == []
    assert "cache_cleared" not in at.session_state
    assert at.text_area[0].value == "still here"
    assert [e.value for e in at.error] == [
        "This conversation could not be found — it may have been removed."
    ]


def test_on_reply_submit_refused_shows_its_own_message_not_the_generic_one():
    # Minor e from the re-review: REFUSED used to fall into the same
    # "Please try again" message as WRITE_FAILED.
    at = AppTest.from_function(_fixed_script, args=(coach_inbox.ReplyResult.REFUSED, 42))
    at.run()
    at.text_area[0].set_value("x").run()
    at.button[0].click().run()

    assert [e.value for e in at.error] == [
        "Your reply could not be sent — check the text and try again."
    ]


def test_on_reply_submit_write_failed_shows_the_generic_retry_message():
    at = AppTest.from_function(_fixed_script, args=(coach_inbox.ReplyResult.WRITE_FAILED, 42))
    at.run()
    at.text_area[0].set_value("x").run()
    at.button[0].click().run()

    assert [e.value for e in at.error] == ["Could not send the reply. Please try again."]


def test_on_reply_submit_blank_body_never_calls_add_reply():
    at = AppTest.from_function(_fixed_script, args=(coach_inbox.ReplyResult.OK, 42))
    at.run()
    at.text_area[0].set_value("   ").run()
    at.button[0].click().run()

    assert at.session_state["calls"] == []
    assert [e.value for e in at.error] == ["Please type a reply before sending."]


def test_on_reply_submit_unknown_coach_never_calls_add_reply():
    at = AppTest.from_function(_fixed_script, args=(coach_inbox.ReplyResult.OK, None))
    at.run()
    at.text_area[0].set_value("hello").run()
    at.button[0].click().run()

    assert at.session_state["calls"] == []
    assert [e.value for e in at.error] == [
        "Could not identify your coach profile — ask an admin to link your login."
    ]
