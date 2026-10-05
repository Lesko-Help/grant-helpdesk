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

Done (commits so far, oldest first):
668bea6 brief filled in.
b6e5811 `config.py` `PRIVATE_THREAD_WORKFLOW_TABLE` + `migrations/018_private_thread_workflow.sql`
(simple `CREATE TABLE IF NOT EXISTS`, not yet run).
f0a2e4c `WorkflowResult` enum + `set_thread_workflow` in `coach_inbox.py` (one MERGE on
`private_thread_workflow` only, REFUSED before any query on bad status/empty id/updated_by,
WRITE_FAILED + alert on a raising client) with `tests/test_coach_inbox_workflow.py`.
e5cd1bf `load_member_questions` derives `status="closed"` via `_read_workflow_closed_at` (R3/R5/R6,
own try/except so a workflow-read failure never looks like a main-read failure) and
`filter_questions_by_status` (R4), with the extended `tests/test_coach_inbox.py` (30 tests).
0add7d1 `reply_form.py`: `close_thread` param on `on_reply_submit`/`render_thread_and_reply` — an OK
reply closes the thread at once (R7), a non-OK close overwrites the message with "Answer sent, but
the thread could not be closed" while still clearing the box/cache; `tests/test_reply_form.py` now
13 tests.
e0d7004 fixed a false positive the workflow MERGE test tripped in
`tests/test_private_chat_insert_only.py`'s 200-char proximity scan (its own literal "MERGE" sitting
near its own "private_threads"/"private_messages" negative-assertion strings) by building the
keyword at runtime, the same trick that guard's own fixture already uses.
1487f40 `app.py`: `_member_question_opts(status)` (Close offered until closed, then only Answer);
Close dispatch in the `_triggered` single-row branch calls `set_thread_workflow` directly (no
dialog — R5/R6), clears `load_member_questions` cache and reruns on OK, `st.error` with the row left
in place on `WRITE_FAILED`; inline-style Closed badge next to waiting/answered; `filter_questions_
by_status(_member_questions, filter_status)` wired in alongside `should_include_questions`; a
`close_thread` lambda now passed into `show_member_question_dialog`'s `render_thread_and_reply`
call.

Full suite green: `unset LIVE_SMOKE; /opt/anaconda3/bin/python3 -m pytest tests/ -q -p
no:cacheprovider` → 158 passed, 17 skipped (baseline 141 passed + 17 new this branch, no
regressions).

Not yet done: app.py's own dropdown/dialog click-through has no automated test — its login gate and
live BigQuery loaders keep it out of AppTest, same as `add_coach_reply`/`set_thread_workflow`'s own
spec test notes say for the rest of app.py's wiring — so it needs a by-hand check on the live app
after deploy (Streamlit 1.58), not before.

Next, in order:
1. Merge `origin/main` once, right before reporting (never rebase mid-round).
2. `git add -N .`, confirm `git status` clean of anything unexpected.
3. Run `wt-done.sh --check coach-inbox-close` until it exits 0.
4. Report to `helpdesk-opzichter`: branch, commit range (668bea6..1487f40), HEAD sha, summary, the
   red-then-green proofs run this branch, and that migration 018 must run before deploy (the table
   `private_thread_workflow` does not exist yet). Then stop and wait.

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
  context, so anything defined inside app.py (like `_member_question_opts`) is checked by hand, not
  by pytest, unless it's moved into a module app.py merely imports.
