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
Verdict: `<fill in — pass, or changes requested>`

### Findings
What the overseer's review subagent flagged — style, bugs, security —
one line each. A trimmer before Martin's read, not a replacement for it.

### Fixed in
Which commit fixed each finding, or "not fixed — see report" — one line
each.

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

Done: nothing coded yet. This brief itself is the only change so far, about to become the first
commit on this branch. Read `docs/specs/modules/coach_inbox.md` in full, plus `coach_inbox.py`,
`app.py` (action options ~1330, dispatch ~1548, `show_member_question_dialog` ~1242, status
filter ~409-421, row rendering ~1466-1572), `config.py` (table constants ~63), `reply_form.py`,
`tests/test_coach_inbox.py`, `tests/test_coach_inbox_reply.py`, `tests/test_reply_form.py`,
migrations 008/017 (style reference), CSS files (no existing closed-badge style — plan is inline
style like the existing "Member question" badge, not a new class).

In flight: none — about to start `config.py`.

Next, in order:
1. `config.py`: add `PRIVATE_THREAD_WORKFLOW_TABLE = f"{PROJECT_ID}.{DATASET}.private_thread_workflow"`
   near the other `*_TABLE` constants.
2. `migrations/018_private_thread_workflow.sql`: simple `CREATE TABLE IF NOT EXISTS` style (like
   008, not 017's transactional rewrite) — write only, header comment says not yet run.
3. `coach_inbox.py`: `WorkflowResult` enum (OK/REFUSED/WRITE_FAILED); `set_thread_workflow`
   (one parameterised MERGE on `private_thread_workflow` only, refuse before any query unless
   `status == "closed"` and both `thread_id`/`updated_by` are non-empty, `report_source_failure`
   on a raising client); extend `load_member_questions` with a second, independently-caught
   workflow-table read nested inside the existing try (so a main-read failure and a workflow-read
   failure stay distinct per R6); add `filter_questions_by_status`.
   New test file `tests/test_coach_inbox_workflow.py`; extend `_FakeBigQueryClient` in
   `tests/test_coach_inbox.py` with an optional `workflow_df` param, dispatching `query()` on
   whether `"private_thread_workflow"` is in the SQL text; add a workflow-raising fake; update
   `test_load_member_questions_sends_exactly_one_query...` (now 2 queries on success). Red before
   green against `origin/main` for every new test.
4. `reply_form.py`: add `close_thread` param to `on_reply_submit`/`render_thread_and_reply`; after
   a reply returns OK, call it and if not `WorkflowResult.OK` overwrite the result message with
   "Answer sent, but the thread could not be closed" (body/cache still clear either way). Update
   `tests/test_reply_form.py` call sites plus new R7 tests, red before green.
5. `app.py`: status-dependent `_MEMBER_QUESTION_OPTS` (Close hidden once a row is closed); Close
   dispatch in the `_triggered` short-circuit's member-question branch, calling
   `set_thread_workflow(thread_id, status="closed", updated_by=current_user)` directly (no dialog,
   per R5/R6 — "Close asks nothing"), clearing `load_member_questions` cache and rerunning on OK,
   `st.error` and no state change on WRITE_FAILED; inline-style Closed badge next to the existing
   waiting/answered ones; `filter_questions_by_status(_member_questions, filter_status)` applied
   alongside the existing `should_include_questions` check (~1734-1754); pass a `close_thread`
   lambda into `show_member_question_dialog`'s call to `render_thread_and_reply`.
6. Full suite: `unset LIVE_SMOKE; /opt/anaconda3/bin/python3 -m pytest tests/ -q -p no:cacheprovider`
   — expect 141 + new tests passed, 17 skipped, no regressions.
7. Merge `origin/main` once, right before reporting. `git add -N .`. `wt-done.sh --check
   coach-inbox-close` until 0. Report to `helpdesk-opzichter`, then stop.

Traps (with dates):
- 2026-10-05 (overseer relay): zone tables read-only except INSERT into `private_messages`,
  enforced only by `tests/test_private_chat_insert_only.py` — workflow MERGE must never name
  `private_threads`/`private_messages`.
- 2026-10-05 (overseer relay): never run migration 018 or touch BigQuery with `bq`/`gcloud` — the
  table does not exist yet; that is exactly R6's case, prove it with a fake, not a real outage.
- 2026-10-05 (overseer relay): only `/opt/anaconda3/bin/python3` has pytest/deps; never
  `LIVE_SMOKE=1`; baseline on `origin/main` is 141 passed, 17 skipped.
- 2026-10-05 (overseer relay): `st.dialog` differs between Streamlit 1.58 (prod) and 1.45.1
  (local, pin still owed) — local AppTest proves logic only, say so in the report.
- 2026-10-05 (self, during reading): `show_member_question_dialog` is at app.py ~1242, not ~1782
  as the relay said — 1782 is the `_pending_action` dispatch that opens it. Verify line numbers
  fresh each time; they drift as app.py is edited this round.
