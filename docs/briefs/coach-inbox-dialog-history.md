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

## Agentic review

### Round 1 — commit `487c5d2`

Verdict: FAIL

Review of commit `487c5d2` by the overseer (2026-09-29), 2 blockers + 7 minors.

### Findings

1. BLOCKER — `tests/test_app_followup_cache.py` never imported `app.py`,
   so it tested a locally re-typed copy of the caching logic rather than
   the real code; deleting the real `@st.cache_data` decorator or
   reverting to the old uncached call left the suite green.
2. BLOCKER — `tests/test_member_history.py`'s `_expected_ticket_line` read
   its expected icon from `member_history.STATUS_ICON` — the code under
   test — so an icon regression there was invisible to the test.
3. MINOR A — `app.py:1272` `_cached_member_history`: no try/except, no
   spinner; first open per member adds ~1.9s of BigQuery time after the
   form draws. Fix: `show_spinner="Loading history…"`, try/except →
   `st.caption("History unavailable")`.
4. MINOR B — `member_history.py:17-25` vs `app.py:83-90`: `STATUS_ICON`
   defined twice. Have `app.py` import `member_history.STATUS_ICON`.
5. MINOR C — `member_history.py:65`: preview shows the last message (may
   be the coach's own reply); `html.escape` alone still lets markdown
   images/links through, and newlines break the line. Use the member's
   first message, flatten newlines, escape markdown too.
6. MINOR D — `member_history.py:49/72`: sort mixes timestamps from two
   sources; add one test with tz-aware datetimes.
7. MINOR E — `app.py:371` `load_followup_statuses`: docstring (input
   tuple of ids, output dict, why) instead of a `#` comment. `app.py:623`
   `show_ticket_dialog`: add a docstring.
8. MINOR F — Brief `## State` is stale (said nothing committed yet).
   Rewrite to match.
9. MINOR G — Community history is capped at the newest 20
   (`bq_reads.py:675` `LIMIT 20`) — informational only, the overseer is
   telling Martin directly; not to be changed by this worktree.

### Fixed in

1. `763d9b3` — moved the cached wrapper into its own importable module,
   `followup_cache.py` (same pattern as `member_history.py`/
   `reply_form.py`); `app.py` now calls
   `followup_cache.load_followup_statuses(...)`. The test imports that
   same module and drives the real function via `AppTest.from_function`,
   with `bq_client.get_followup_statuses` monkeypatched to a counting
   fake. Proven red by stripping the decorator (3 calls across 3 reruns
   instead of 1), green restored.
2. `3cb9c18` — hardcoded a literal `_EXPECTED_ICON` dict in the test file,
   copied from origin/main's values, instead of reading
   `member_history.STATUS_ICON`. Proven red by changing
   `STATUS_ICON["answered"]` to a wrong value (assertion failure showing
   the mismatch), green restored.
3. `78d18ab` — `_cached_member_history` now shows
   `show_spinner="Loading history…"`; both call sites
   (`show_ticket_dialog`, `show_member_question_dialog`) catch a failed
   read, log it via `raillog.alert("coach-inbox", "SOURCE_FAILED", ...)`,
   and fall back to `st.caption("History unavailable")` instead of
   crashing the dialog. Plain fix + verify (py_compile clean, full suite
   green) — no test can pin this without driving app.py's own
   `@st.dialog`-wrapped function, which needs the login gate the
   testable-module pattern exists to route around.
4. `e9fa90d` — `app.py` now does `STATUS_ICON = member_history.STATUS_ICON`
   instead of carrying its own second literal dict. Plain fix + verify.
5. `67f331a` — `_private_thread_line` now picks the member's own first
   message, flattens newlines to spaces, and backslash-escapes markdown's
   special characters in addition to HTML-escaping. Proven red by
   reverting to `messages[-1]["body"]` + `html.escape` only — the 3 new
   tests failed exactly as expected (coach reply shown instead of the
   member's question, a raw newline breaking the line, raw `*`/`[]()`
   passing through unescaped) — green restored.
6. `fc96299` — added `_sort_key`, converting a tz-aware timestamp to naive
   UTC before comparison; both `_ticket_line` and `_private_thread_line`
   use it for their sort key. Proven red by reverting both call sites to
   bare `pd.Timestamp(...)` — the new mixed-tz test failed with
   `TypeError: Cannot compare tz-naive and tz-aware timestamps` — green
   restored.
7. `763d9b3` (docstring on the new `followup_cache.load_followup_statuses`,
   input/output/why, written when the module was created) + `f07b91b`
   (added the same shape of docstring to `show_ticket_dialog`).
8. This commit — `## State` below rewritten to match the current, complete
   picture.
9. Not fixed — informational only, per the overseer's explicit
   instruction; left for the overseer to handle directly with Martin.

### Round 2 — commit `da71bc7`

Verdict: PASS

Re-review of commit `da71bc7` by the overseer (2026-09-29), 0 blockers +
6 minors (numbered 0-5). Martin's explicit call, relayed by the overseer:
"fix the crash, then land" — fix 0, 2, 4 in code (one commit each,
red-then-green); note 1 and 3 here instead of changing code; 5 needs no
action.

### Findings (round 2)

0. MUST FIX — no source test blocked `app.py` from reverting to a direct,
   uncached `bq_client.get_followup_statuses(` call (the exact bug
   `followup_cache.py` exists to fix); the suite stayed green even if
   reverted.
1. Brief said "152 passed" but that includes `tests/smoke_test.py`
   (135 + 17), which writes to live BigQuery (MERGEs `_smoke_test_*` rows
   into META_TABLE). From now on, run pytest with
   `--ignore=tests/smoke_test.py` and report that count.
2. MUST FIX (Martin's call: "fix the crash") — `member_history.py:79`
   `_escape_preview`'s `body.split()` crashes on a NULL body (bodies come
   straight from BigQuery via `coach_inbox.py:88`), outside the
   try/except at `app.py:1276-1279` — one such message crashed the whole
   Answer dialog.
3. Accepted risk, brief-only, do not change `bq_reads.py` —
   `followup_cache.py:32`'s `bq_reads.get_followup_statuses` swallows
   errors and returns `{}`; now cached 300s, so one transient BigQuery
   failure hides follow-up badges for up to 5 minutes.
4. `member_history.py:69` markdown-escape set (`_MARKDOWN_ESCAPE`) is
   missing `~` and `|`.
5. `member_history.py:24` `STATUS_ICON` gained a `"waiting"` key; harmless
   since `config.TICKET_STATUSES` has no such status.

### Fixed in (round 2)

0. `6c1578a` — added `test_app_source_calls_the_cached_wrapper_not_
   bigquery_directly` to `tests/test_app_followup_cache.py`, reading
   `app.py`'s own source text and asserting the literal string
   `"bq_client.get_followup_statuses("` is absent. Proven red by
   temporarily reintroducing that exact call at `app.py`'s real call
   site (the assertion failed, showing the offending line); `app.py`
   restored to its committed state (confirmed via `git diff`), green
   restored.
1. Brief note only (this entry) — full-suite command from now on is
   `pytest tests/ -q -p no:cacheprovider --ignore=tests/smoke_test.py`;
   true count for this task's suite is 138 passed (135 baseline + 3 new
   tests added this round: the null-body test, the tilde/pipe test, and
   minor 0's source test).
2. `e8afcdd` — `_escape_preview` now does `(body or "").split()`. Proven
   red first: with the old `body.split()`, the new
   `test_combined_mode_does_not_crash_on_a_null_message_body` failed with
   `AttributeError: 'NoneType' object has no attribute 'split'` at
   `member_history.py:83`, matching the finding exactly; green restored.
3. Brief note only (this entry) — accepted risk, `bq_reads.py` not
   touched, per the overseer's explicit instruction.
4. `0a4ac8b` — added `~` and `|` to `_MARKDOWN_ESCAPE`. Proven red first:
   with the old set, the new
   `test_combined_mode_escapes_tilde_and_pipe_in_the_preview` failed —
   the preview line held the raw `~~strike~~ | table` instead of the
   escaped form; green restored.
5. Not fixed — no action needed, per the overseer's explicit finding
   (harmless).

## State

Replaced in full each time the context guard asks you to save — never append another checkpoint.
About 60 lines max. Old traps stay (they are short and worth keeping); everything else gets
overwritten with the current picture.

Done (2026-09-29):
- First implementation (301f41e..487c5d2), reviewed FAIL (2 blockers + 7
  minors, G informational). Both blockers + minors A-F fixed, one commit
  each (763d9b3, 3cb9c18, e9fa90d, 67f331a, fc96299, 78d18ab, f07b91b),
  recorded in `## Agentic review` above; brief committed at da71bc7.
- Reported da71bc7 to helpdesk-opzichter. Overseer re-reviewed at da71bc7:
  **PASS**, 0 blockers, 6 minors (numbered 0-5). Martin's call: "fix the
  crash, then land."
- Fixed minors 0, 2, 4 in code, one commit each, all red-then-green
  proven: minor 2 (e8afcdd, NULL-body crash), minor 4 (0a4ac8b, missing
  ~/| escapes), minor 0 (6c1578a, source test on app.py). Minors 1, 3, 5
  recorded in `## Agentic review` above (brief-only/no action, per the
  overseer's instruction — bq_reads.py not touched). Full round-2
  `## Agentic review` entry (Verdict: PASS, findings 0-5, fixed-in 0-5)
  committed alongside this State rewrite.
- Full suite (excluding tests/smoke_test.py, which writes to live
  BigQuery — always exclude it from now on):
  `pytest tests/ -q -p no:cacheprovider --ignore=tests/smoke_test.py` ->
  138 passed (135 baseline + 3 new tests this round).

Next (in order):
1. `git add -N .`, clean tree; re-verify `git merge-base --is-ancestor
   origin/main HEAD`; `wt-done.sh --check` until it exits 0.
2. Report the new commit range to helpdesk-opzichter [8ddd8b] (two
   agents share the bare name) with proof, then stop and wait.

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
