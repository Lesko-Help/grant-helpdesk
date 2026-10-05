# Brief: coach-inbox-close

Stages: product (gate 1) · architecture (gate 2) · review:300 — DOWNGRADED (dropped: design · slices)
Downgraded: repo default "groot" wanted design · slices.
Reason: Martin chose midden for this task on 2026-10-05: close only, the spec is already agreed and committed, so the design and slices gates are not needed

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)

## Product — gate 1

Against `docs/specs/goal.md`: nothing changes — that file is still the empty template (Status: draft), so there is no stated goal or number to move.

### Problem
A member's private question stays in the coaches' Tickets list forever, even after it is answered, so coaches cannot see at a glance what still needs them.

### User
Coaches and the admin, in the Tickets tab of the helpdesk app, each time they work through the list.

### Success metric
Number of member questions closed since shipping, and by how many coaches:

```sql
SELECT COUNT(*) AS closed_questions,
       COUNT(DISTINCT updated_by) AS coaches_closing,
       MAX(closed_at) AS last_close
FROM `bigtribebuilders.grant_helpdesk.private_thread_workflow`
WHERE status = 'closed'
  AND closed_at >= TIMESTAMP('2026-10-05');
```

Working: `closed_questions` is 0 today and, one week after shipping, is above 0 and about as high as the number of questions coaches answered that week; `last_close` is recent. Still 0 after a week of answers means closing does not work.

### Mock-up
Tickets tab, Status = open (dropdown open on a member question):

```
 Tickets (2 new)
+----------------------------------------------------------------+
| [Member question] [waiting]   Anna de Vries                    |
| "Which budget form do I use?"            [ Action        v ]   |
|                                          |  Answer         |   |
|                                          |  Close          |   |
|                                          +-----------------+   |
+----------------------------------------------------------------+
| [Ticket] [open]   Community question ...     [ Action    v ]   |
+----------------------------------------------------------------+
```

One click on Close, or sending an answer: the row leaves this list. A new message from Anna brings it back as waiting.

Same row, sidebar Status = closed:

```
+----------------------------------------------------------------+
| [Member question] [Closed]    Anna de Vries                    |
| "Which budget form do I use?"            [ Action        v ]   |
|                                          |  Answer         |   |
|                                          +-----------------+   |
+----------------------------------------------------------------+
```

Architecture — gate 2: agreed text is `docs/specs/modules/coach_inbox.md`, sections `load_member_questions`, `merge_into_tickets(tickets, questions)`, `add_coach_reply` and `set_thread_workflow` (committed on main, 523f69d). Read it there; it is not copied here.

## Agentic review

### Verdict
Verdict: pass with fixes, now resolved

### Findings
Overseer review of 668bea6..d260c16, by mutation testing a scratch copy
(14 mutations):
1. `load_member_questions`'s closed-status derivation forced a reopened
   thread back to "waiting" even once a coach had answered it again —
   should keep "answered" (load R3's own newest-message rule).
2. `test_coach_inbox_workflow.py`'s MERGE-shape assertions only checked
   that words appeared somewhere in the SQL string — `ON TRUE`, dropping
   `closed_at` from the UPDATE branch, and `status = 'open'` all still
   passed.
3. `_member_question_opts` lived in app.py with no automated test — the
   spec's own test note expects it tested, but app.py's login gate makes
   it unimportable under pytest.
4. The existing closed/reopen tests used ISO strings for `created_at`/
   `closed_at`, proving only string-sort order, not real datetime
   comparison.
5. `closed_at is None` missed `pd.NaT`, which is how a NULL column
   actually surfaces from `.to_dataframe()` — a row like that stuck
   "closed" forever.
6. Tidy: migration 018's `thread_id` had `NOT NULL`, which the spec does
   not; several touched functions and test helpers were missing the
   docstrings the global CLAUDE.md rule asks for.

Held back by the overseer, not part of this round: a cache/race-condition
question on `closed_at` being "now" at click time, escalated to Martin
separately — no fix attempted here pending that answer. The outage-wording
question in app.py was left as-is, no action needed.

### Fixed in
1. `a924fa8` — kept the newest-message-derived status unless there is no
   member message after `closed_at`; new tests for reopen-then-reanswer
   and for the plain reopen case with real `pd.Timestamp` values (covers
   finding 4 too).
2. `df73684` — whitespace-normalized, branch-exact assertions on the
   WHEN MATCHED/WHEN NOT MATCHED text; verified red on all three
   mutations from finding 2 on a scratch copy, then green on the real
   code, before committing.
3. `4bcba20` — moved the function into `coach_inbox.py` as
   `member_question_action_opts`, three new tests, app.py's call site
   and dropdown comment updated.
5. `a924fa8` — same commit as finding 1 (`pd.isna(closed_at)` instead of
   `is None`), with its own reopen test using `pd.NaT` directly.
6. `b80b747` — migration 018's `thread_id` column, and docstrings for
   `reply_form.py`'s module docstring, app.py's Close branch, `_params`,
   `_thread_row`, and both `_close_thread` fakes.

Full suite: 164 passed, 17 skipped (was 158 passed before this round).

This section is filled last, after the overseer runs its review subagent
and sends the findings back — never by the worker reviewing its own
diff. Record the verdict, fix what needs fixing, commit, then report
again the normal way.

wt-done.sh's check on this is literal: it greps this brief for a line
starting with exactly `Verdict:` at the very start of the line (column 0)
— no bold, no indent, no renamed label, no different case. Keep the
`Verdict:` line reading exactly as it does above, or the guard cannot see
it and treats the brief as not yet reviewed.


## Goal

A 1:1 member question is closed when a coach answers it, or with a Close action under Answer; closed questions show only under Status closed — build exactly the closing rules of docs/specs/modules/coach_inbox.md (set_thread_workflow, migration 018, close on answer, Close action)

## Done when

`/opt/anaconda3/bin/python3 -m pytest tests/ -q -p no:cacheprovider` passes, including:
- `tests/test_coach_inbox_workflow.py` (new): `set_thread_workflow` — MERGE shape/params against
  `private_thread_workflow` only, no `assignee`/`lane` in SET; wrong status / empty thread_id /
  empty updated_by refuse with no query; a raising client returns `WRITE_FAILED` and logs the
  exact `BTB_ALERT ... SOURCE_FAILED: private_chat workflow write failed: ...` line.
- `tests/test_coach_inbox.py` additions: `load_member_questions` derives `status="closed"` from a
  closed `private_thread_workflow` row (R3); a member message newer than `closed_at` reopens it to
  `waiting` (R5); a workflow-read-only failure still returns every thread, none closed, plus one
  `SOURCE_FAILED: ... workflow read failed: ...` alert (R6); new `filter_questions_by_status`
  keeps only closed rows when the sidebar Status is `closed`, only non-closed otherwise (R4).
- `tests/test_reply_form.py` additions: a successful `add_coach_reply` closes the thread via a new
  `close_thread` callable (R7); when that close does not return OK, the reply still counts as
  sent, the typed text still clears, and the coach sees "Answer sent, but the thread could not be
  closed".
- `tests/test_private_chat_insert_only.py` stays green — the workflow MERGE must never name
  `private_threads` or `private_messages`.
Every new test proven red first against `origin/main` (the function/behaviour does not exist
there), then green here.

Spec: unchanged because `docs/specs/modules/coach_inbox.md` already carries this task's rules
(`set_thread_workflow`, migration 018, close-on-answer, the Close action) — committed on main
before this worktree started (523f69d); this worktree implements it, it does not change the text.

## May touch

Module: `coach_inbox` (`docs/specs/INDEX.md`).
- `coach_inbox.py` — `set_thread_workflow`, `WorkflowResult`, the workflow read inside
  `load_member_questions`, `filter_questions_by_status`.
- `config.py` — one new table constant for `private_thread_workflow`.
- `reply_form.py` — `on_reply_submit`/`render_thread_and_reply` gain a `close_thread` callable (R7).
- `app.py` — the member-question row's Action dropdown (add "Close", hide it once closed), the
  Close dispatch (reuses the existing `_act_triggered_*` short-circuit, calls
  `set_thread_workflow` instead of `bq_client.update_ticket_meta` for a `member_question` row),
  the Closed badge, wiring `close_thread` into `render_thread_and_reply`, and applying
  `filter_questions_by_status` alongside the existing `should_include_questions` check.
- `migrations/018_private_thread_workflow.sql` (new) — creates
  `bigtribebuilders.grant_helpdesk.private_thread_workflow`, per the spec's column list. Write
  only — never run it.
- `tests/test_coach_inbox.py`, `tests/test_coach_inbox_workflow.py` (new), `tests/test_reply_form.py`.

Out of scope (per spec's Decisions, 2026-10-05): `assignee`/`lane` columns get no behaviour yet;
`set_thread_workflow` accepts only `status="closed"`.

## Deploy implied

`deploy.sh` (the Streamlit app) — after `main` has this merged. Migration 018 must run against
`bigtribebuilders.grant_helpdesk` **before** that deploy — it creates the table
`load_member_questions`'s workflow read and `set_thread_workflow`'s write both depend on. The
worktree session never runs either; the overseer does, on Martin's word.

## Context

- Architecture gate (already agreed, read in full, not copied here):
  `docs/specs/modules/coach_inbox.md`, sections `load_member_questions`, `merge_into_tickets`,
  `add_coach_reply`, `set_thread_workflow`, committed 523f69d.
- Overseer memory relay, received 2026-10-05 after this worktree opened (not in time for this
  commit's first draft, added before any code was written):
  - Decisions by Martin, 2026-10-05: a coach's answer closes the thread by itself (derived on
    read, nothing written); "Close" sits under "Answer", always offered, one click, any coach, no
    reason; a closed question shows only under sidebar Status `closed`, with a Closed badge; scope
    is close only — no assign/lane for threads.
  - Trap 1: the zone's tables (`lesko-486515.private_chat`) are read-only for this app except
    `INSERT` into `private_messages` — enforced only by `tests/test_private_chat_insert_only.py`
    (the BigQuery role itself would allow more). The workflow statement must never name
    `private_threads` or `private_messages`.
  - Trap 2: this worktree only *writes* migration 018 — never runs it, never touches BigQuery with
    `bq`/`gcloud`. Until the overseer runs it (production, Martin's word), the table does not
    exist — spec's R6 (workflow read fails, threads still returned, none closed) is exactly that
    case, and must be proven here, offline, against a fake client.
  - Trap 3: only `/opt/anaconda3/bin/python3` has pytest and the deps. Run
    `unset LIVE_SMOKE; /opt/anaconda3/bin/python3 -m pytest tests/ -q -p no:cacheprovider`.
    Baseline on `origin/main`: 141 passed, 17 skipped. Never `LIVE_SMOKE=1` (writes to production).
  - Trap 4: `st.dialog` behaves differently on Streamlit 1.58 (production) vs 1.45.1 (local, pin
    still owed) — a local AppTest run proves the logic, not the live dialog's click-through; say
    so in the report.
  - Trap 5 (orientation only, verify — line numbers drift): action options ~app.py:1330
    (`_MEMBER_QUESTION_OPTS`), dispatch `_on_action_change` ~1548, member-question dialog
    `show_member_question_dialog` ~1242 (not 1782 — that line is the `_pending_action` dispatch
    that opens it); `coach_inbox.merge_into_tickets`/`waiting_count`; `reply_form.on_reply_submit`
    clears the `load_member_questions` cache on OK.
  - Trap 6: failures go through `report_source_failure`/`raillog.alert` — never swallow one
    silently.

## Spec proposals

Specs belong to the overseer (DECISION BY MARTIN 2026-09-24) — this worktree
never edits docs/specs/ itself. Anything found missing, unclear or wrong in a
module's spec goes here instead: what the spec says now, what it should say,
and why. The overseer applies what it agrees with on main.

## State

Done: the original close-only build (668bea6..1487f40 — workflow table/migration 018,
`set_thread_workflow`, closed-status derivation in `load_member_questions`, close-on-answer in
`reply_form.py`, the Close action and closed badge in `app.py`), then the overseer's PASS WITH
FIXES review of that range, now all fixed (a924fa8..b80b747):
- a924fa8: two closed-status bugs — a reopened-then-reanswered thread now keeps "answered" (was
  forced to "waiting"); `pd.isna(closed_at)` replaces `is None` (NULL surfaces as `pd.NaT`, which
  used to stick a row closed forever). Tests include a real-`pd.Timestamp` case.
- df73684: `test_coach_inbox_workflow.py`'s MERGE assertion rewritten branch-exact and whitespace-
  normalized; verified red on all three mutations the overseer found before going green.
- 4bcba20: `_member_question_opts` moved from (untestable) app.py into `coach_inbox.py` as
  `member_question_action_opts`, three new tests.
- b80b747: migration 018's `thread_id` dropped `NOT NULL` to match spec; missing docstrings added
  (reply_form.py module docstring, app.py Close branch, `_params`/`_thread_row`/`_close_thread`).

Full suite green: `unset LIVE_SMOKE; /opt/anaconda3/bin/python3 -m pytest tests/ -q -p
no:cacheprovider` → 164 passed, 17 skipped (baseline 141, no regressions).

Not yet done: app.py's own dropdown/dialog click-through still has no automated test (login gate +
live BigQuery loaders keep it out of AppTest) — a by-hand check on the live app after deploy
(Streamlit 1.58), not before.

On hold, not this worker's call: a cache/race-condition question on `closed_at` being "now" at
click time, escalated to Martin separately — no fix attempted pending that answer.

In flight: none — all six review fixes committed, brief's `## Agentic review` filled in with
`Verdict: pass with fixes, now resolved`. Next is the report-and-stop sequence below.

Next, in order:
1. Merge `origin/main` once, right before reporting (never rebase mid-round).
2. `git add -N .`, confirm `git status` clean of anything unexpected.
3. Run `wt-done.sh --check coach-inbox-close` until it exits 0.
4. Report to `helpdesk-opzichter`: branch, commit range (668bea6..b80b747), HEAD sha, summary of the
   six review fixes and their red-then-green proofs, and that migration 018 must run before deploy
   (the table `private_thread_workflow` does not exist yet). Then stop and wait.

Traps (with dates):
- 2026-10-05 (overseer relay): zone tables read-only except INSERT into `private_messages`,
  enforced only by `tests/test_private_chat_insert_only.py` — workflow MERGE must never name
  `private_threads`/`private_messages`, and must avoid the guard's own literal-proximity false
  positive too (see e0d7004 above) — build the keyword at runtime if a test needs both close by.
- 2026-10-05 (overseer relay): never run migration 018 or touch BigQuery with `bq`/`gcloud` — the
  table does not exist yet; that is exactly R6's case, prove it with a fake, not a real outage.
- 2026-10-05 (overseer relay): only `/opt/anaconda3/bin/python3` has pytest/deps; never
  `LIVE_SMOKE=1`; baseline on `origin/main` is 141 passed, 17 skipped.
- 2026-10-05 (overseer relay): `st.dialog` differs between Streamlit 1.58 (prod) and 1.45.1
  (local, pin still owed) — local AppTest proves logic only, say so in the report.
- 2026-10-05 (self, during reading): `show_member_question_dialog` is at app.py ~1242, not ~1782
  as the relay said — 1782 is the `_pending_action` dispatch that opens it. Verify line numbers
  fresh each time; they drift as app.py is edited this round.
- 2026-10-05 (self): `app.py` cannot be imported directly even for a pure-logic unit test —
  `st.user.is_logged_in` raises at module import time with no `DEV_USER` set and no live script
  context, so anything defined inside app.py (like the former `_member_question_opts`) is checked by
  hand, not by pytest, unless it's moved into a module app.py merely imports. Fixed in 4bcba20: it now
  lives in `coach_inbox.py` as `member_question_action_opts` and app.py just calls it — trap 5 above
  (`_MEMBER_QUESTION_OPTS`/`_member_question_opts`) is stale as of that commit.
- 2026-10-05 (overseer review, mutation testing a scratch copy): six findings — two real bugs in
  `load_member_questions`'s closed-status derivation (reopen-then-reanswer, `pd.NaT`), a weak MERGE-
  shape test assertion, an untestable dropdown-options function, an ISO-string-only test, and several
  missing docstrings/a migration mismatch. All six fixed — see `## Agentic review` above for the full
  findings/fixed mapping. A `closed_at`-is-"now"-at-click-time race condition was raised but held back
  for a spec answer from Martin, not fixed here.
