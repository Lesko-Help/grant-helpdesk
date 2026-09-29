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

**`docs/specs/modules/coach_inbox.md`** does not yet document the new
function this task added, `member_other_threads`. Proposed addition (own
section, alongside `waiting_count`/`merge_into_tickets`):

> ### `member_other_threads(questions, member_id, exclude_content_id) -> pd.DataFrame`
>
> Input: the frame from `load_member_questions` (every member's private
> threads, already loaded by the Tickets tab); the member_id whose other
> threads the Answer dialog wants; the content_id of the thread already
> open, so it doesn't list itself.
>
> Output: that member's remaining threads, newest activity first.
>
> Why: the Answer dialog's Member-history panel (member_history.py) needs
> this member's other private-chat threads alongside their community
> tickets (bq_client.get_member_history), the same way show_ticket_dialog's
> own panel already showed a member's other tickets. No new BigQuery read —
> filters the frame the Tickets tab already fetched and cached.
>
> Test: tests/test_coach_inbox.py (member_other_threads section) — plain
> pandas fixtures, no fake BigQuery client needed.

## State

Replaced in full each time the context guard asks you to save — never append another checkpoint.
About 60 lines max. Old traps stay (they are short and worth keeping); everything else gets
overwritten with the current picture.

Done (2026-09-29):
- First implementation landed as 4 commits (301f41e..487c5d2): shared
  `member_history.py` + `show_ticket_dialog` extraction;
  `coach_inbox.member_other_threads`; the Answer dialog's combined-history
  wiring; the `load_followup_statuses` caching fix. Reported to
  helpdesk-opzichter, full suite 149 passed, `wt-done.sh --check` passed.
- Overseer reviewed 487c5d2: **FAIL**, 2 blockers + 7 minors (G is
  informational only — a pre-existing 20-row cap in bq_reads.py the
  overseer is telling Martin about, not for me to change).
- Blocker 1 fixed (763d9b3): `tests/test_app_followup_cache.py` never
  imported app.py, so deleting the real `@st.cache_data` decorator left it
  green. Moved the wrapper into its own importable module,
  `followup_cache.py` (same pattern as `member_history.py`/`reply_form.py`);
  app.py now does `import followup_cache` and calls
  `followup_cache.load_followup_statuses(...)`. Test now imports the same
  module and drives the real function via `AppTest.from_function`, with
  `bq_client.get_followup_statuses` monkeypatched to a counting fake. Proven
  red by stripping the decorator (3 calls across 3 reruns), green restored.
- Blocker 2 fixed (3cb9c18): `tests/test_member_history.py`'s
  `_expected_ticket_line` read its icon from `member_history.STATUS_ICON` —
  the code under test — so an icon mutation there was invisible. Hardcoded
  a literal `_EXPECTED_ICON` dict in the test file instead. Proven red by
  changing `STATUS_ICON["answered"]`, green restored.
- Full suite after both blocker fixes: 148 passed (one test count lower
  than before — the old standalone "old shape" reproduction test in
  test_app_followup_cache.py was replaced by two tests that both drive the
  real module, not a third copy).

In flight: minors A-F not yet started (B: dedupe STATUS_ICON between app.py
and member_history.py; C: private-thread preview should use the member's
first message not whichever is last, flatten newlines, escape markdown too
— html.escape alone isn't enough under unsafe_allow_html; D: `_ticket_line`/
`_private_thread_line` sort keys are raw `pd.Timestamp` — confirmed locally
that comparing a tz-aware one against a tz-naive one raises TypeError, needs
a shared naive-UTC normalizer + a test; A: `_cached_member_history` calls at
app.py have no show_spinner text or try/except fallback; E: `show_ticket_
dialog` still has no docstring). Nothing uncommitted lost — no code changes
made yet for A/B/C/D/E, only the two blocker-fix commits above exist so far
on top of 487c5d2.

Next (in order):
1. Fix minors B, C (+tests), D (+test), A, E — one commit each, red-then-
   green where the fix is a behavior change (C, D), plain fix+verify for the
   rest (A, B, E).
2. One final brief commit: `## Agentic review` section (Verdict: FAIL line
   in column 0, Findings 1-9, Fixed in 1-9 referencing commit shas) + this
   State section rewritten to match.
3. `git add -N .`, verify clean tree; origin/main was already an ancestor
   last check, re-verify with `git merge-base --is-ancestor origin/main
   HEAD`.
4. Run `wt-done.sh --check coach-inbox-dialog-history` until it exits 0.
5. Report the new commit range to `helpdesk-opzichter [8ddd8b]` (there are
   two agents named helpdesk-opzichter — the ref matters) with red-then-green
   proof for both blockers, then stop and wait.

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
