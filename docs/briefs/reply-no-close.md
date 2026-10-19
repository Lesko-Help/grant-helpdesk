---
# Pairing block: what this worktree is paired to. Read by control-window.sh
# (cw_pairing) for the overview. wt-new.sh fills repo, and module and spec
# when WT_MODULE was given; everything else is yours or the interview's.
# Never guess a value from a branch, folder or repo name: leave `<fill in`.
client: none
repo: helpdesk
rails: BigQuery (private_thread_workflow, read-only here; no new writes)
module: coach_inbox
spec: docs/specs/modules/coach_inbox.md
folder: repo root (reply_form.py, coach_inbox.py, app.py, tests/)
---

# Brief: reply-no-close

Stages: product (gate 1) · architecture (gate 2) · design (gate 3) · slices (gate 4) · review:300

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below, under Goal and Done when, with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)

## Goal

Stop a sent reply from closing the thread, and let Status All show closed member questions

## Done when

Slice 1: in `tests/test_reply_form.py`, a recorder-patched `set_thread_workflow` stays empty on an `OK` reply and `"could not be closed"` is absent from `reply_form.py`; red on `origin/main` (`TypeError`, the call is recorded), green after.

Slice 2: in `tests/test_coach_inbox.py`, `filter_questions_by_status` gives 3 rows under `"All"`, only the closed row under `"closed"`, the 2 non-closed under `"open"`/`"answered"`; red on `origin/main` (`"All"` gives 2).

Spec: unchanged because the overseer already wrote `coach_inbox.md` (add_coach_reply R7, merge_into_tickets R4) before this branch.

# Gate: a coach can answer twice, and can still find the thread

## Product

Problem: Tony and Rose answer a member, then cannot answer again or find the
thread. Two causes, one complaint — an `OK` reply closes the thread
(`reply_form.py:71`), and Status "All" hides closed ones (`coach_inbox.py:452`).

User: coaches and the admin in the Tickets tab. After sending, the row stays in
their list as `Answered`; a thread closed by hand is still under Status = All.

Success: no coach reports a lost thread; from 2026-10-19 every `closed_at` in
`private_thread_workflow` comes from a hand click, not from sending an answer.

Not in scope: any replacement auto-close, an age rule included (Martin chose
(a), 2026-10-19); community tickets' own "All", still hiding closed; assign/lane.

Mock-up — left, after sending a reply (Status = open); right, Status = All:

    Tickets (1 new)                      | Status = All
    [Member q][waiting]  Bo              | [Member q][Closed]   Anna
    [Member q][Answered] Anna  <- stays, | [Member q][Answered] Bo
      [Action v] Answer again / Close    | [Ticket][open] Community ...

## Slices

1. Stop the auto-close. in = an `OK` reply; out = reply sent, thread left
   `answered`, no `private_thread_workflow` write, no "could not be closed"
   text; `close_thread` gone from both `reply_form` entry points and `app.py:1269`.
   Proof: `PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_reply_form.py -q`,
   red on `origin/main` (close is called; the arg is still required).
2. "All" shows closed. in = Status "All"; out = waiting + answered + closed;
   `closed` still only closed; any other status the non-closed ones. Proof:
   `PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_coach_inbox.py -q`,
   red on `origin/main`, where "All" drops every closed row. Never bare
   `pytest tests/`: `tests/smoke_test.py` writes live `ticket_metadata`.

Design: docs/specs/modules/coach_inbox.md — Screens (Answer dialog), `merge_into_tickets` R4, `add_coach_reply` R7, `set_thread_workflow` R5 and Test, `## Decisions`.

## Agentic review

### Verdict
Verdict: `<fill in — pass, or changes requested>`

### Findings
What the overseer's review subagent flagged — style, bugs, security —
one line each. A trimmer before Martin's read, not a replacement for it.

### Fixed in
Which commit fixed each finding, or "not fixed — see report" — one line
each.

This section is filled last, after the overseer runs its review subagent
and sends the findings back — never by the worker reviewing its own
diff. Record the findings under Findings (word for word) and the
fixes under Fixed in (one line per finding, naming its commit), fix
what needs fixing, commit, then report again the normal way. Also
leave the `Verdict:` line exactly as it stands: the overseer fills
it at review.

wt-done.sh's check on this is literal: it greps this brief for a line
starting with exactly `Verdict:` at the very start of the line (column 0)
— no bold, no indent, no renamed label, no different case. Keep the
`Verdict:` line reading exactly as it does above, or the guard cannot see
it and treats the brief as not yet reviewed.


## May touch

Module `coach_inbox`. Files: `reply_form.py`, `coach_inbox.py` (`filter_questions_by_status` only), `app.py` (the Answer dialog call near line 1269 only), `tests/test_reply_form.py`, `tests/test_coach_inbox.py`.

## Deploy implied

`deploy.sh` (Cloud Run app, from main after landing). No Dataform change.

## Context

2026-10-19: the overseer's memory message had not arrived when this brief was committed; its content gets added here once it does. Spec is already on main: `add_coach_reply` R7, `merge_into_tickets` R4, `set_thread_workflow` R5. Martin chose no replacement auto-close (a), 2026-10-19. Never run bare `pytest tests/` (`tests/smoke_test.py` writes live data); use `PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_reply_form.py -q`.

## Spec proposals

Specs belong to the overseer (DECISION BY MARTIN 2026-09-24) — this worktree
never edits docs/specs/ itself. Anything found missing, unclear or wrong in a
module's spec goes here instead: what the spec says now, what it should say,
and why. The overseer applies what it agrees with on main.

## State

Replaced in full each time the context guard asks you to save — never append another checkpoint.
About 60 lines max. Old traps stay (they are short and worth keeping); everything else gets
overwritten with the current picture.

Done:
In flight (file:line):
Next:
Traps (with dates):
