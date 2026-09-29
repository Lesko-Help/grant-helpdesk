"""
The "Member history" panel shared by the regular Ticket dialog and the
private-message Answer dialog (app.py's show_ticket_dialog and
show_member_question_dialog) — see docs/briefs/coach-inbox-dialog-history.md.

Pulled out into its own module, the same reason reply_form.py is its own
module: a plain function with no BigQuery/Streamlit-cache calls of its own
is the only shape that both dialogs can call unchanged, and that a test can
call directly without app.py's login gate.
"""

import html

import pandas as pd
import streamlit as st

STATUS_ICON = {
    "open":      "🔵",
    "answered":  "✅",
    "closed":    "🟢",
    "cancelled": "🔴",
    "flagged":   "🚩",
    "archived":  "⚪",
    "waiting":   "🔵",
}


def _sort_key(value):
    """
    Input: a timestamp-like value (str, or a tz-aware/tz-naive pd.Timestamp)
    as returned by either bq_client.get_member_history (ticket created_at)
    or coach_inbox.member_other_threads (private last_activity_at).
    Output: a tz-naive pd.Timestamp, safe to compare against any other
    value this function returns.
    Why: pd.Timestamp comparison raises TypeError when one side is
    tz-aware and the other tz-naive, and the two BigQuery sources are not
    guaranteed to agree on tz-awareness — merging and sorting both kinds
    of row (render_member_history's combined mode) would otherwise crash.
    """
    ts = pd.Timestamp(value)
    return ts.tz_convert("UTC").tz_localize(None) if ts.tzinfo is not None else ts


def _ticket_line(row):
    """
    Input: one row of the ticket-history frame bq_client.get_member_history
    returns (content_id, permalink, body_preview, created_at, ticket_status).
    Output: (sort key, the exact markdown line show_ticket_dialog drew for
    this row before this module existed).
    Why a separate function: the sort key has to be a plain value pandas'
    own Timestamp compares against pd.Timestamp cleanly for both kinds of
    row, computed once instead of inside the f-string.
    """
    icon = STATUS_ICON.get(row["ticket_status"], "⚪")
    link = (
        f'&nbsp;<a href="{row["permalink"]}" target="_blank" '
        f'style="font-size:0.75rem;color:#4a52a3">↗ MN</a>'
        if row.get("permalink") else ""
    )
    line = (
        f'{icon} <span style="font-size:0.8rem;color:#6b7280">'
        f'`{str(row["created_at"])[:10]}`</span>'
        f' — {row["body_preview"]}{link}'
    )
    return _sort_key(row["created_at"]), line


_MARKDOWN_ESCAPE = {ord(c): f"\\{c}" for c in "\\`*_{}[]()#+-.!~|"}


def _escape_preview(body):
    """
    Input: a member's raw typed message body.
    Output: the same text on one line (newlines flattened to spaces),
    HTML-escaped and with markdown's own special characters
    backslash-escaped.
    Why both: this line is drawn with unsafe_allow_html=True, so a
    member's own typed text — which, unlike a ticket's server-side
    body_preview, has never passed through any sanitizer — would
    otherwise let both raw HTML and markdown formatting/links through,
    not just HTML.
    """
    flattened = " ".join((body or "").split())
    return html.escape(flattened.translate(_MARKDOWN_ESCAPE))


def _private_thread_line(row):
    """
    Input: one row of coach_inbox.member_other_threads's frame (content_id,
    last_activity_at, status, messages).
    Output: (sort key, markdown line) — same visual shape as _ticket_line so
    the two kinds read as one list. The preview is the member's own first
    message in the thread (the question that started it, the same role a
    ticket's body_preview plays), not whichever message happens to be last
    — the last message is often the coach's own reply, not the member's.
    """
    icon = STATUS_ICON.get(row["status"], "⚪")
    messages = row.get("messages") or []
    member_messages = [m for m in messages if m.get("author_role") == "member"]
    first = (member_messages or messages or [None])[0]
    preview = _escape_preview(first["body"])[:300] if first else "(no messages)"
    line = (
        f'{icon} <span style="font-size:0.8rem;color:#6b7280">'
        f'`{str(row["last_activity_at"])[:10]}`</span>'
        f' — {preview} <span style="font-size:0.75rem;color:#6b7280">(private message)</span>'
    )
    return _sort_key(row["last_activity_at"]), line


def render_member_history(member_name, ticket_history, private_threads=None):
    """
    Input: the member's display name for the expander's own title; the
    ticket-history frame (from bq_client.get_member_history, already sorted
    newest-first) shown by both dialogs; and, only for the Answer dialog,
    the member's other private-chat threads (from
    coach_inbox.member_other_threads) — the two are merged and re-sorted
    newest-activity-first, since the caller can't otherwise know which
    kind, if either, happened most recently.
    Output: none — draws one st.expander with one line per item, exactly
    the markup show_ticket_dialog's own inline block drew before this
    module existed when private_threads is left at its default None
    (the Ticket dialog's own call, which must not change at all).
    Why private_threads defaults to None rather than an empty list: an
    empty DataFrame/list and "this dialog never even checked" must read
    differently in the empty-state message below.
    """
    with st.expander(f"📋 Member history ({member_name})"):
        lines = [_ticket_line(row) for _, row in ticket_history.iterrows()]
        if private_threads is not None:
            lines += [_private_thread_line(row) for _, row in private_threads.iterrows()]
            lines.sort(key=lambda item: item[0], reverse=True)
            empty_message = "No other tickets or private chats from this member."
        else:
            empty_message = "No other tickets from this member."

        if not lines:
            st.write(empty_message)
        else:
            for _, line in lines:
                st.markdown(line, unsafe_allow_html=True)
