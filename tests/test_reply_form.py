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


def _fixed_script(add_reply_result, lookup_result, close_thread_result=None):
    import streamlit as st

    import coach_inbox
    import reply_form

    if close_thread_result is None:
        close_thread_result = coach_inbox.WorkflowResult.OK

    st.session_state.setdefault("calls", [])
    st.session_state.setdefault("close_calls", [])

    def _add_reply(thread_id, author_id, body):
        st.session_state["calls"].append((thread_id, author_id, body))
        return add_reply_result

    def _lookup(email):
        return lookup_result

    def _clear_cache():
        st.session_state["cache_cleared"] = True

    def _close_thread(thread_id, current_user):
        """Fakes coach_inbox.set_thread_workflow: records the call (so a
        test can assert it happened, and with what args) and returns the
        WorkflowResult the test wants, without ever touching BigQuery."""
        st.session_state["close_calls"].append((thread_id, current_user))
        return close_thread_result

    with st.form("reply_form", clear_on_submit=False):
        st.text_area("Reply", key="reply_body", label_visibility="collapsed")
        st.form_submit_button(
            "Send reply",
            on_click=reply_form.on_reply_submit,
            args=(
                "th1", "reply_body", "reply_result", "coach@example.com",
                _lookup, _add_reply, _clear_cache, _close_thread,
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


# ── R7: a successful reply closes the thread ────────────────────────────────

def test_on_reply_submit_success_closes_the_thread_once():
    at = AppTest.from_function(_fixed_script, args=(coach_inbox.ReplyResult.OK, 42))
    at.run()
    at.text_area[0].set_value("hello there").run()
    at.button[0].click().run()

    assert list(at.exception) == []
    assert at.session_state["close_calls"] == [("th1", "coach@example.com")]
    assert list(at.error) == []


def test_on_reply_submit_non_ok_never_calls_close_thread():
    at = AppTest.from_function(_fixed_script, args=(coach_inbox.ReplyResult.WRITE_FAILED, 42))
    at.run()
    at.text_area[0].set_value("x").run()
    at.button[0].click().run()

    assert at.session_state["close_calls"] == []


def test_on_reply_submit_success_with_failed_close_still_clears_but_warns():
    at = AppTest.from_function(
        _fixed_script,
        args=(coach_inbox.ReplyResult.OK, 42, coach_inbox.WorkflowResult.WRITE_FAILED),
    )
    at.run()
    at.text_area[0].set_value("hello there").run()
    at.button[0].click().run()

    assert list(at.exception) == []
    assert at.session_state["close_calls"] == [("th1", "coach@example.com")]
    assert at.session_state["cache_cleared"] is True
    assert at.text_area[0].value == ""
    assert [e.value for e in at.error] == ["Answer sent, but the thread could not be closed"]


# ── render_thread_and_reply: the answer-dialog's body ───────────────────────
#
# Same fake-dependency shape as _fixed_script above, but calling the dialog
# body function directly and unconditionally (no one-shot open/close flag
# wrapped around it) rather than reproducing app.py's @st.dialog/
# _pending_action dispatch — an AppTest scratch probe (see
# docs/briefs/coach-inbox-answer-dialog.md, Context) found that AppTest
# does not re-invoke a function gated behind such a flag on a widget's own
# rerun, which would make the dialog look closed regardless of outcome.
# The open/close dispatch itself is the same _pending_action -> single
# @st.dialog call -> st.rerun() idiom show_flag_dialog/show_assign_dialog/
# show_delete_dialog already use unchanged in production.

_MESSAGES = [
    {"author_role": "member", "body": "When is the next cohort?", "created_at": "2026-09-01"},
    {"author_role": "coach", "body": "Starts October 6th.", "created_at": "2026-09-02"},
]


def _dialog_script(add_reply_result, lookup_result, messages, close_thread_result=None):
    import streamlit as st

    import coach_inbox
    import reply_form

    if close_thread_result is None:
        close_thread_result = coach_inbox.WorkflowResult.OK

    # Counts every script execution, including ones triggered by a
    # st.rerun() inside render_thread_and_reply itself — a plain "box got
    # cleared" assertion can't tell that apart from the on_click callback
    # clearing the box on its own, since that happens either way.
    st.session_state["runs"] = st.session_state.get("runs", 0) + 1
    st.session_state.setdefault("calls", [])
    st.session_state.setdefault("close_calls", [])

    def _add_reply(thread_id, author_id, body):
        st.session_state["calls"].append((thread_id, author_id, body))
        return add_reply_result

    def _lookup(email):
        return lookup_result

    def _clear_cache():
        st.session_state["cache_cleared"] = True

    def _close_thread(thread_id, current_user):
        """Same fake as _fixed_script's own _close_thread above — see there."""
        st.session_state["close_calls"].append((thread_id, current_user))
        return close_thread_result

    reply_form.render_thread_and_reply(
        "th1", messages, "reply_body", "reply_result", "coach@example.com",
        _lookup, _add_reply, _clear_cache, _close_thread,
    )


def test_render_thread_and_reply_shows_the_messages_oldest_first():
    at = AppTest.from_function(_dialog_script, args=(coach_inbox.ReplyResult.OK, 42, _MESSAGES))
    at.run()

    assert list(at.exception) == []
    assert [cm.name for cm in at.chat_message] == ["user", "assistant"]
    assert [m.value for cm in at.chat_message for m in cm.markdown] == [
        "When is the next cohort?", "Starts October 6th.",
    ]


def test_render_thread_and_reply_on_ok_reruns_to_close_not_just_clears_the_box():
    # A reviewer's scratch copy with render_thread_and_reply's st.rerun()
    # replaced by `pass` still passed a box-cleared-only assertion here (the
    # on_click callback clears the box on its own) — count script runs
    # instead, since only an actual st.rerun() adds one beyond the submit's
    # own run. Checked red with st.rerun() removed (delta 1) before this was
    # written; green with it in place (delta 2).
    at = AppTest.from_function(_dialog_script, args=(coach_inbox.ReplyResult.OK, 42, _MESSAGES))
    at.run()
    at.text_area[0].set_value("hello there").run()
    _runs_before_submit = at.session_state["runs"]
    at.button[0].click().run()

    assert list(at.exception) == []
    assert at.session_state["calls"] == [("th1", 42, "hello there")]
    assert at.session_state["cache_cleared"] is True
    assert at.session_state["runs"] - _runs_before_submit == 2
    assert at.text_area[0].value == ""
    assert list(at.error) == []


def test_render_thread_and_reply_on_failure_keeps_the_dialog_open_with_the_text():
    at = AppTest.from_function(_dialog_script, args=(coach_inbox.ReplyResult.UNKNOWN_THREAD, 42, _MESSAGES))
    at.run()
    at.text_area[0].set_value("still here").run()
    at.button[0].click().run()

    assert list(at.exception) == []
    assert "cache_cleared" not in at.session_state
    # the dialog stayed open: the form (and its text) is still on screen
    assert len(at.text_area) == 1
    assert at.text_area[0].value == "still here"
    assert [e.value for e in at.error] == [
        "This conversation could not be found — it may have been removed."
    ]
