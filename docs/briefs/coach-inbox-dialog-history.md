# Brief: coach-inbox-dialog-history

Stages: oneshot — DOWNGRADED (dropped: product · architecture · design · slices)
Downgraded: repo default "groot" wanted product · architecture · design · slices.
Reason: Reuses the existing ticket-dialog history element in the Answer dialog and speeds up its opening; no new table, no new write

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)


## Goal

Answer dialog for member questions shows the member's full history (community tickets + private chats) below the conversation, using the SAME history component as the regular ticket dialog (one shared function called from both), and opens fast (measure why it is slow now, fix the cause)

## Done when

`/opt/anaconda3/bin/python -m pytest tests/test_member_history.py tests/test_coach_inbox.py tests/test_app_followup_cache.py -q -p no:cacheprovider`
is green, where:

1. `tests/test_member_history.py` (new) pins `member_history.render_member_history`:
   called with `private_threads=None` (the regular ticket dialog's own case) it
   draws the exact markup/text `show_ticket_dialog`'s inline block drew before
   this task (same icons, same "No other tickets from this member." on empty);
   called with `private_threads` given (the Answer dialog's new case) it also
   draws the member's other private-chat threads, newest activity first mixed
   in with the tickets, HTML-escaped, and says
   "No other tickets or private chats from this member." only when both are
   empty. Proven red first: this file fails to collect before `member_history.py`
   exists.
2. `tests/test_coach_inbox.py` gains tests for the new pure function
   `coach_inbox.member_other_threads(questions, member_id, exclude_content_id)`
   — filters to one member, excludes the thread already open, sorts newest
   first. Proven red first (function does not exist yet).
3. `tests/test_app_followup_cache.py` (new) proves the speed fix: a script
   shaped like tab_main's old call to `bq_client.get_followup_statuses` (no
   `st.cache_data`) re-runs the BigQuery call on every single script rerun —
   proven red by asserting 3 calls across 3 `at.run()`s; the new
   `load_followup_statuses` wrapper (ttl=300, same pattern as
   `load_tickets`/`load_open_stats`) hits it once across 3 reruns with the
   same ids — green.

Manual check (not automated, same as the rest of app.py's dialog wiring —
"checked by hand" per `add_coach_reply`'s own Test note): opening the Answer
dialog after this change shows the reply form, then below it one "Member
history" expander with community tickets and private threads combined; the
regular Ticket dialog's Member history expander looks pixel-identical to
before.

Spec: docs/specs/modules/coach_inbox.md — see `## Spec proposals` below for
`member_other_threads`; `app.py`/`member_history.py`/`reply_form.py` have no
module spec yet (INDEX.md is still a template), so their tests are derived
from this Done-when, not from a spec.

## May touch

Module: `coach_inbox` (deploy: `deploy.sh`).

- `app.py` — `show_ticket_dialog`'s Member-history block, `show_member_question_dialog`,
  the uncached `get_followup_statuses` call in `tab_main`.
- `coach_inbox.py` — new pure function `member_other_threads`.
- `member_history.py` — new file, the shared history-render function (no
  module spec owns this; see Done-when).
- `tests/test_member_history.py` (new), `tests/test_coach_inbox.py`,
  `tests/test_app_followup_cache.py` (new).
- This brief.

## Deploy implied

`deploy.sh` (the app) once landed on `main`. No Dataform, no new table, no
new write, no alert change — nothing else to redeploy.

## Context

**Overseer's memory message (2026-09-29, arrived after `wt-new.sh`), Martin's
own words on seeing the live Answer dialog:** "a list below where we can see
all the previous history chats of this person in the community + privately,
make sure you reuse the element of the other regular tickets, these 2 should
be the same code referenced in both places. it also takes very long to open
the private message ticket."

**Measured locally against live BigQuery** (`gcloud auth application-default`
works from this worktree; see scratch probe, not committed):
`get_tickets` 2.8s, `get_followup_statuses` 1.8s, `load_member_questions` 2.3s,
`get_member_history` 1.9s, `get_open_stats` 1.9s, `get_daily_stats` 2.2s — every
BigQuery round trip here costs ~2s regardless of table size. `load_tickets`,
`load_open_stats`, `load_daily_stats`, `load_member_questions` are all already
`@st.cache_data` in `app.py`; **`get_followup_statuses` (app.py:1637) is the
one call in `tab_main` with no cache at all**, so it re-pays that ~2s on
*every single script rerun* of the Tickets tab — including the rerun that
opens either dialog, `show_ticket_dialog` or `show_member_question_dialog`
alike. That is the root cause of "takes very long to open" (matches the
2026-05-18 slow-open precedent: BigQuery time is the real bottleneck, not
Streamlit). Fix: `load_followup_statuses`, a `@st.cache_data(ttl=300)`
wrapper keyed on `tuple(content_ids)`, cleared alongside `load_tickets`/
`load_open_stats`/`load_daily_stats` at app.py:813-815 (the one write path
that changes a follow-up, `bq_client.queue_followup`, already clears those
three there).

**Join key (overseer's question 3):** community tickets (`grant_tickets.member_id`)
and private-chat threads (`private_threads.member_id`, read via
`coach_inbox.load_member_questions`) are the same MN member id space — both
join to `bigtribebuilders.dataform.core_members.member_id` filtered to
`client_id = 'lesko_4022250'` (coach_inbox.py's own `load_member_questions`
SQL does this join already; `bq_reads.get_member_history` filters
`grant_tickets` by the same `member_id`). No new join needed — a plain
`==` on `member_id` is correct.

**Traps carried from the overseer's memory (2026-09-29), for whichever
session reads this brief next:**
- Streamlit 1.58 in prod vs 1.45.1 local; `on_change` inside `@st.dialog`
  fires on 1.58 (proved with headless Playwright) but may not on 1.45.1 —
  test under a scratch venv with 1.58.0 if a dialog widget's `on_change` is
  ever in question again.
- Dialog open/close can't be modelled in AppTest — test render functions
  directly (this is why `member_history.py` and `reply_form.py` are plain
  functions app.py calls, not tested through the `@st.dialog` wrapper).
- Never log a private message's body, anywhere.
- The helpdesk's grant on `lesko-486515.private_chat` (EU) is `dataViewer`
  on `private_threads` (plus the `private_messages` insert path) — this task
  reads no new zone table, so no new permissions question.
- `pytest` can trigger a live Dataform run via `trigger_assignment_refresh`;
  none of this task's tests reach `bq_writes` at all.
- Run pytest with `/opt/anaconda3/bin/python -m pytest tests/ -q -p no:cacheprovider`.

## Spec proposals

Specs belong to the overseer (DECISION BY MARTIN 2026-09-24) — this worktree
never edits docs/specs/ itself. Anything found missing, unclear or wrong in a
module's spec goes here instead: what the spec says now, what it should say,
and why. The overseer applies what it agrees with on main.

## State

Replaced in full each time the context guard asks you to save — never append another checkpoint.
About 60 lines max. Old traps stay (they are short and worth keeping); everything else gets
overwritten with the current picture.

Done (2026-09-29):
- Brief committed as the first commit on this branch (4e8316b).
- `member_history.py` written: `render_member_history(member_name,
  ticket_history, private_threads=None)`. `private_threads=None` reproduces
  `show_ticket_dialog`'s old inline block exactly; given a private_threads
  frame it merges in `coach_inbox.member_other_threads`' rows, HTML-escaped,
  newest-activity-first, with its own combined empty message.
- `coach_inbox.member_other_threads(questions, member_id, exclude_content_id)`
  added (end of coach_inbox.py) — pure pandas filter/sort, no new BigQuery
  call, matches member_id as a string on both sides (numpy int64 vs int).
  Its Spec proposal entry is still a stub below — fill in before reporting.
- app.py wired up: `import member_history`; show_ticket_dialog's inline
  Member-history block replaced by one call to
  `member_history.render_member_history(...)` (no `private_threads` arg);
  `show_member_question_dialog` now adds `st.divider()` + the combined
  history call after the reply form; `load_followup_statuses` (ttl=300,
  keyed on a tuple of content_ids) wraps the old uncached
  `bq_client.get_followup_statuses` call at the old app.py:1637 site;
  `load_followup_statuses.clear()` added next to the other three clears in
  the one write path that queues a follow-up (`_fu_enabled and
  _fu_msg.strip()` branch, ~app.py:813-816).
- Tests written and proven red-then-green:
  `tests/test_member_history.py` (5 tests, proven red via temporarily
  moving member_history.py aside — ModuleNotFoundError — then green);
  `tests/test_coach_inbox.py` (+4 tests for member_other_threads, proven red
  by `git stash` of coach_inbox.py alone, restored via `git stash apply
  <sha>`, not pop — a leftover stash entry with tag
  `coach-inbox-dialog-history-redcheck-1790675883` still exists in the
  shared stash list, already reapplied, safe to leave or drop later);
  `tests/test_app_followup_cache.py` (3 tests — the first IS the red proof,
  no app.py import needed since it reproduces both shapes standalone; had
  to add `st.cache_data.clear()` at the top of the two cache-dependent
  tests because Streamlit's cache_data key is global by source-hash+args,
  so two tests redefining an identically-worded nested cached function
  collided with each other otherwise).
- Full suite green: `pytest tests/ -q -p no:cacheprovider` → 149 passed,
  including `test_private_chat_insert_only.py` (4 passed, untouched).
  `py_compile app.py coach_inbox.py member_history.py` also clean.
- Docstrings updated on `show_member_question_dialog` to mention the new
  history section and shared module.

In flight: nothing uncommitted has been lost — all of the above is only in
the working tree, NOT YET COMMITTED as git commits (still one commit total:
the brief). Was about to also touch `show_ticket_dialog`'s own docstring
(app.py:623) to mention the extraction when the context guard fired.

Next (in order):
1. Finish the small docstring touch on `show_ticket_dialog` (app.py:623) —
   optional polish, skip if short on time.
2. Fill in the `## Spec proposals` section below for
   `coach_inbox.member_other_threads` (not yet written).
3. Commit the actual changes — split into sensible commits (e.g. one for
   member_history.py + the show_ticket_dialog extraction + its test; one
   for member_other_threads + its test; one for the load_followup_statuses
   caching fix + its test; one for show_member_question_dialog's wiring).
   One idea per commit, per CLAUDE.md.
4. `git add -N .`, verify clean tree.
5. Merge `origin/main` once (never rebase mid-round).
6. Run `wt-done.sh --check coach-inbox-dialog-history` until it exits 0.
7. Report to `helpdesk-opzichter` via SendMessage: branch, commit range,
   HEAD sha, 5-line summary, how done-when was proven red-then-green,
   deploy implications (`deploy.sh`). Then stop and wait.

Traps (with dates):
- 2026-05-18: slow dialog open before was a hidden-spinner cache; the fix
  pattern (ThreadPoolExecutor + spinner + timeout fallback) already lives in
  show_ticket_dialog (app.py:617-636) — do not re-fix that, only the new
  get_followup_statuses caching gap.
- 2026-09-29 (this task): Streamlit 1.58 prod vs 1.45.1 local — dialog
  on_change differs; test render functions directly, never model dialog
  open/close in AppTest.
- 2026-09-29: never log a private message body anywhere.
- 2026-09-29: helpdesk's BigQuery grant on private_chat (EU) is dataViewer
  on private_threads only, plus an insert path on private_messages — no new
  table read needed for this task, don't touch grants.
- 2026-09-29: pytest must never reach bq_writes.trigger_assignment_refresh
  (live Dataform trigger) — all three new/changed test files use fakes only.
