"""
Proof for member_history.render_member_history — see
docs/briefs/coach-inbox-dialog-history.md.

show_ticket_dialog (the regular Ticket dialog) and show_member_question_dialog
(the private-message Answer dialog) both call this one function so there is
only one place drawing a member's history instead of two copies drifting
apart. Called with private_threads=None it must draw exactly what
show_ticket_dialog's own inline block drew before the extraction — pinned
here so a future edit to the combined-history branch cannot silently change
the Ticket dialog's own output too.
"""

import pandas as pd
from streamlit.testing.v1 import AppTest

import member_history


def _render_script(member_name, ticket_history, private_threads):
    import member_history
    member_history.render_member_history(member_name, ticket_history, private_threads)


_TICKETS = pd.DataFrame([
    {
        "content_id": "c1", "permalink": "https://mn.co/posts/1",
        "body_preview": "How do I submit my grant report?",
        "created_at": "2026-09-20", "ticket_status": "answered",
    },
    {
        "content_id": "c2", "permalink": None,
        "body_preview": "Following up on my last question",
        "created_at": "2026-09-10", "ticket_status": "open",
    },
])


# Literal icons copied from origin/main's show_ticket_dialog, not read from
# member_history.STATUS_ICON — the code under test — so mutating an icon
# there is caught here rather than staying invisible to this test.
_EXPECTED_ICON = {"open": "🔵", "answered": "✅"}


def _expected_ticket_line(row):
    icon = _EXPECTED_ICON[row["ticket_status"]]
    link = (
        f'&nbsp;<a href="{row["permalink"]}" target="_blank" '
        f'style="font-size:0.75rem;color:#4a52a3">↗ MN</a>'
        if row["permalink"] else ""
    )
    return (
        f'{icon} <span style="font-size:0.8rem;color:#6b7280">'
        f'`{row["created_at"]}`</span> — {row["body_preview"]}{link}'
    )


# ── private_threads=None: the Ticket dialog's own case, must not change ────

def test_ticket_only_mode_reproduces_the_original_markup_line_for_line():
    at = AppTest.from_function(_render_script, args=("Jamie", _TICKETS, None))
    at.run()

    assert list(at.exception) == []
    assert [m.value for m in at.markdown] == [
        _expected_ticket_line(row) for _, row in _TICKETS.iterrows()
    ]


def test_ticket_only_mode_empty_history_shows_the_original_message_only():
    at = AppTest.from_function(_render_script, args=("Jamie", pd.DataFrame(), None))
    at.run()

    assert list(at.exception) == []
    assert [m.value for m in at.markdown] == ["No other tickets from this member."]


# ── private_threads given: the Answer dialog's new, combined case ──────────

_PRIVATE = pd.DataFrame([
    {
        "content_id": "pc:t1", "last_activity_at": "2026-09-25", "status": "waiting",
        "messages": [{"author_role": "member", "body": "Can we talk <b>privately</b>?", "created_at": "2026-09-25"}],
    },
])


def test_combined_mode_merges_private_threads_newest_activity_first():
    at = AppTest.from_function(_render_script, args=("Jamie", _TICKETS, _PRIVATE))
    at.run()

    assert list(at.exception) == []
    lines = [m.value for m in at.markdown]
    assert len(lines) == 3
    # 2026-09-25 (private) is newer than both tickets, so it sorts first.
    assert "2026-09-25" in lines[0]
    assert "(private message)" in lines[0]


def test_combined_mode_html_escapes_the_private_message_body():
    at = AppTest.from_function(_render_script, args=("Jamie", pd.DataFrame(), _PRIVATE))
    at.run()

    assert list(at.exception) == []
    line = at.markdown[0].value
    assert "<b>privately</b>" not in line
    assert "&lt;b&gt;privately&lt;/b&gt;" in line


def test_combined_mode_both_empty_shows_the_combined_message():
    at = AppTest.from_function(_render_script, args=("Jamie", pd.DataFrame(), pd.DataFrame()))
    at.run()

    assert list(at.exception) == []
    assert [m.value for m in at.markdown] == [
        "No other tickets or private chats from this member."
    ]
