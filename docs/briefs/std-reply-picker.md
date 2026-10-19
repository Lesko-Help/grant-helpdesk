---
# Pairing block: what this worktree is paired to. Read by control-window.sh
# (cw_pairing) for the overview. wt-new.sh fills repo, and module and spec
# when WT_MODULE was given; everything else is yours or the interview's.
# Never guess a value from a branch, folder or repo name: leave `<fill in`.
client: <fill in>
repo: helpdesk
rails: none
module: coach_inbox
spec: docs/specs/modules/coach_inbox.md
folder: repo root (`reply_form.py`, `app.py`, `tests/test_reply_form.py`)
---

# Brief: std-reply-picker

Stages: product (gate 1) · architecture (gate 2) · design (gate 3) · slices (gate 4) · review:300

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below, under Goal and Done when, with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)

## Goal

Offer the standard replies in the member 1 to 1 answer dialog, the one dialog that lacks them

## Done when

`tests/test_reply_form.py`, run as `PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_reply_form.py -q`, gains tests per slice, each red against `origin/main` first: a fake picker called once with `("stdreply_reply_body", "reply_body")` before the form; `std_reply_picker=None` draws no selectbox; a pick appends below the committed text and resets the dropdown; an `ast` walk of `app.py` finds exactly three `_std_reply_picker` calls, none in `reply_form.py`.

Spec: unchanged because the overseer already wrote the picker into `coach_inbox.md` (R1-R6 of `render_thread_and_reply`) on main; any gap goes under Spec proposals.

# Gate: standard replies in the member 1:1 answer dialog

## Product

Problem: the canned answers sit one dropdown away in the Tickets dialog and the group
dialog, but not in the 1:1 dialog, so a coach answering a private question retypes them.

User: a coach in the Tickets tab, on a `Member question` row, action `Answer`. Above the
reply box she picks a title, the template lands in the box, she edits it and sends.

Success: the 1:1 dialog offers the same titles as the other two; picking one lands the
template in the box; after deploy a coach sends one from it and says it worked.

Not in scope: the Replies tab, which templates each dialog shows, inserting at the cursor,
moving the reply box out of st.form (what full parity with the other two would need).

Mock-up:
```
┌ Member Question · "How do I apply for SLIM?" ┐
│ [ — insert a standard reply —            ▾ ] │
│ ┌ Hi Jane, thanks for asking … ┐  [ Send ]   │
└──────────────────────────────────────────────┘
```

## Slices

1. `reply_form.render_thread_and_reply` takes an optional picker callable: in = the picker
   and the reply box's key; out = the dropdown above the form, nothing without one. Proof:
   a fake picker, asserted called with the body key and before the form.
2. `app.py:1259` passes `_std_reply_picker`; the stale comment at `app.py:538` ("both
   answer dialogs") becomes all three: in = one shared helper; out = three call sites.
   Proof: `ast` over `app.py` sees exactly three calls, none in `reply_form.py`.
3. Insert behaviour: in = a pick; out = the template appended below the last SENT text,
   dropdown reset, help text "pick it first, then edit" (the box is inside st.form, which
   commits only on Send). Proof: AppTest picks, sees the template; picks twice, sees both.

All three, red first against `origin/main`: `PATH=/opt/anaconda3/bin:$PATH python -m pytest
tests/test_reply_form.py -q`. Never bare `pytest tests/` — it writes live `ticket_metadata`.

Design: docs/specs/modules/coach_inbox.md — Overview entry points, Screens (Answer dialog), `add_coach_reply` R6, new `### render_thread_and_reply(...)`, `## Decisions`.

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

Module `coach_inbox`. Files: `reply_form.py`, `app.py` (only the 1:1 dialog call, `_std_reply_picker` help text, the stale comment at line 538), `tests/test_reply_form.py`. Nothing else.

## Deploy implied

`deploy.sh` (Cloud Run app), run by the overseer from main after the landing. No Dataform change.

## Context

2026-10-19: the overseer's memory message had not arrived when this brief was committed; add its content here once it does.

Facts found while reading: in `reply_form.py` `close_thread` is still a parameter of `render_thread_and_reply` (spec Decisions: it goes in a later landing), so `std_reply_picker=None` is added after it. `app.py:_insert_std_reply` already appends below the committed text and resets the dropdown, so slice 3 is mostly proving that through the form plus the new help text. Its current help text differs from the spec's R5 wording and is shared by all three dialogs.

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
