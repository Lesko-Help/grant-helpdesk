# Brief: coach-inbox-list

Stages: product (gate 1) · architecture (gate 2) · design (gate 3) · slices (gate 4) · review:300

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)

# GATE — grant-helpdesk: coach inbox for members' private questions
# for: helpdesk-opzichter · approved by Martin 2026-09-25 · drafted 2026-09-25 from `20260924-HANDOFF-questions-zone-coach-inbox.md` + Martin's decisions of 2026-09-25

Design and function rules: `docs/specs/modules/coach_inbox.md` (in grant-helpdesk, on `main`). A worker reads that file before its first slice.

## Product — gate 1

### Problem
A member who asks a coach a private question on their page gets no answer, because no coach can see it; so the zone stays switched off.

### User
Lesko Help coaches (and the admin), working in the grant-helpdesk Tickets tab.

### Success metric
Hours from a member's message to the next coach message in `private_messages` (median per week, and count of threads still waiting after 48h):
`SELECT COUNT(*) FROM (SELECT thread_id, ARRAY_AGG(author_role ORDER BY created_at DESC LIMIT 1)[OFFSET(0)] AS last_role, MAX(created_at) AS last_at FROM lesko-486515.private_chat.private_messages GROUP BY thread_id) WHERE last_role='member' AND last_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)` — target 0.

### Mock-up
```
[🎫 Tickets (2 new)] [💬 Conversations] [📊 Reports] ... [📬 Inbox]
 Tickets (14)
 ┌───────────────────────────────────────────────────────────────┐
 │ [Member question] Anna K. · housing · "Can I get help with…"  │  waiting · 3h
 │   ▸ 2 messages (expand to read)                               │
 │ [Member question] Joe P. · jobs-training · "Is the course…"   │  waiting · 1d
 │ #8812 MN post · urgent · "Grant form rejected…"   [— action —]│  open · 20m
 │ [Member question] Sue L. · food · "Thanks, that worked"       │  answered · 2d
 └───────────────────────────────────────────────────────────────┘
```
Member-question rows have no action dropdown until the workflow slice; later they get Answer / Assign / Close like tickets.

## Slices — gate 4

### Slice order
Worktrees A and B run in parallel and touch no file in common. Neither edits `docs/specs/modules/coach_inbox.md` except A (its own functions); the overseer fills B's stubs at landing. Landing order: B, then A.

**A — `coach-inbox-list`** (read-only mixed list, badge, waiting count).
May touch: `coach_inbox.py` (new), `app.py` (tab label at ~1226, Tickets tab body, `render_ticket_table` for the badge row), `config.py` (`PRIVATE_CHAT_DATASET`), `tests/test_coach_inbox.py` (new), `tests/test_private_chat_insert_only.py` (new), `docs/specs/modules/coach_inbox.md` (its four functions + the code rule), `docs/briefs/coach-inbox-list.md`.
- A1 tracer: a hardcoded thread goes through `merge_into_tickets` and shows in Tickets with the badge. Proof: `pytest tests/test_coach_inbox.py -k merge` green, red first against `origin/main`; screenshot of the local app.
- A2 real read: `load_member_questions` against `private_chat` with names from `core_members`, derived status. Proof: fake-client test for R1-R3; local run against the real (empty or test) tables shows no error.
- A3 count: `waiting_count` and the `🎫 Tickets (N new)` label. Proof: test for R1-R2.
- A4 insert-only guard: `tests/test_private_chat_insert_only.py`, shown red with a fixture UPDATE, then green.
- A5 (after B has landed; rebase on `origin/main`): read failure -> `st.error` + `report_source_failure`. Proof: raising fake client -> empty frame and one captured `BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED` line, red first.
Done when: A1-A5 proofs recorded in the brief, full `pytest tests/` green, B landed and its fire drill recorded.

**B — `coach-inbox-alert`** (alert helper for the app, and its policies).
May touch: `raillog.py` (new, repo root, copy of `jobs/raillog.py`), `jobs/alert_payloads.py` (service-scoped variants: `cloud_run_revision`, `service_name="grant-helpdesk"`), `jobs/deploy-alerts.sh` (second block for the service), `tests/test_raillog_app.py` (new), `tests/test_deploy_alerts_payloads.py`, `docs/briefs/coach-inbox-alert.md`.
- B1: root `raillog.py`, importable from `app.py`'s folder. Proof: test captures the exact JSON line with `severity` ERROR, red first.
- B2: service-scoped log-match and metric + threshold (24h re-notify) payloads, titles starting `BTB-ALERT bigtribebuilders`. Proof: offline payload tests, red first.
- B3: `deploy-alerts.sh` applies them, re-runnable, job policies unchanged. Proof: a dry re-run diff shows only the new service policies.
Done when: B1-B3 proofs in the brief. Fire drill (overseer, after landing B): run `jobs/deploy-alerts.sh`, write one synthetic `BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED: fire drill` entry with resource `cloud_run_revision` / `service_name=grant-helpdesk` through the Logging API, see the email arrive, note it in `docs/briefs/coach-inbox-alert.md`.

**Overseer after A:** land A, `deploy.sh`, check the tab live against the real tables. Real fire drill: a no-traffic tagged revision with `PRIVATE_CHAT_DATASET` pointed at a missing dataset; open it, see the error and the email.

**Later — `coach-inbox-reply`** (reply box). Starts after A lands. May touch: `coach_inbox.py` (`add_coach_reply`), `app.py` (the reply box in the member-question row), `tests/test_coach_inbox_reply.py` (new), the spec's `add_coach_reply` section, its brief. Done when: tests prove role `coach`, `author_member_id` from `grant_coaches` for coach and admin alike, any coach can reply in any thread, the 4000-char limit, "unknown thread -> nothing written", no body in logs, write failure -> `SOURCE_FAILED` line (all red first); insert-only guard still green.

**Later — `coach-inbox-workflow`** (assign, lane, close). Starts after reply lands. May touch: `migrations/<n>_private_thread_workflow.sql` (new), `coach_inbox.py` (`set_thread_workflow`, read joins it), `bq_writes.py`, `app.py` (action dropdown for member-question rows), `config.py`, `tests/test_coach_inbox_workflow.py` (new), the spec's section, its brief. Done when: tests prove assign/lane/close write one row per thread, "member message after close -> waiting again", and closed threads leave the count (red first); overseer runs the migration.

**Then (zone overseer):** set `ZONE_WRITES=true`, ask one test question, answer it in the helpdesk, see "answered" on the member page; written into both briefs.

STOP: after every slice, message the overseer (SendMessage — find it with
ListAgents if the name needs a [ref]): "slice K done - continue or
re-steer?" plus a one-line summary of the slice and its proof line. Wait
for its reply before starting slice K+1 — it writes a slice file, asks
Martin in its own pane, and relays his answer back to you. Record that
reply here before continuing. Never ask Martin directly in this window.

## Settled 2026-09-25 (Martin)
- The admin gets a row in `grant_coaches`; nothing else supplies an MN id.
- Every coach sees and may answer every thread; the badge counts waiting threads, nothing stored.

## Open check
- "React to a specific message": replying to one message inside a thread, or only to the thread? Assumed thread; see the spec's Open check.

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

Slice A of the approved coach-inbox gate: private_chat threads read-only in the Tickets list with 'Member question' badge and waiting count; done-when and may-touch as in the gate; alert wiring (A5) only after B lands; spec docs/specs/modules/coach_inbox.md

## Done when

Five proofs, one per sub-slice, each shown red against `origin/main` before green:
- A1 tracer: a hardcoded thread goes through `merge_into_tickets` and shows in
  Tickets with the `Member question` badge. `pytest tests/test_coach_inbox.py -k merge` green.
- A2 real read: `load_member_questions` against `private_chat`, names joined from
  `core_members`, status derived (R1-R3 of the spec). Fake-client test green;
  local run against the real (empty) tables shows no error.
- A3 count: `waiting_count` and the `🎫 Tickets (N new)` label (R1-R2). Test green.
- A4 insert-only guard: `tests/test_private_chat_insert_only.py` shown red with a
  fixture file holding an `UPDATE ... private_messages`, then green with it removed.
- A5 (only after worktree B lands and this branch rebases on `origin/main`): read
  failure -> `st.error` + `report_source_failure`. Raising fake client -> empty
  frame and one captured `BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED` line.

Overall: full `pytest tests/` green, and worktree B landed with its fire drill
recorded before A5 is attempted (A5 waits on B; A1-A4 do not).

Spec: `docs/specs/modules/coach_inbox.md` updated — this slice writes the
`load_member_questions`, `waiting_count`, `merge_into_tickets` and
`report_source_failure` R-lines from `<!-- spec:stub -->` markers that don't
exist yet for these four (they are already written in the agreed text) — no
change expected unless code diverges from what's agreed, in which case see
Spec proposals below.

## May touch

Module: `coach_inbox` (see `docs/specs/modules/coach_inbox.md`).
- `coach_inbox.py` (new) — `load_member_questions`, `waiting_count`, `merge_into_tickets`, `report_source_failure`.
- `app.py` — tab label at ~1226 (`🎫 Tickets (N new)`), the Tickets tab body (~1526-1625), `render_ticket_table` for the badge row and suppressing the action dropdown on member-question rows.
- `config.py` — `PRIVATE_CHAT_DATASET` (default `lesko-486515.private_chat`).
- `tests/test_coach_inbox.py` (new).
- `tests/test_private_chat_insert_only.py` (new) — scans tracked `.py` files for UPDATE/DELETE/MERGE/etc. against `private_threads`/`private_messages`.
- `docs/specs/modules/coach_inbox.md` — its four functions' R-lines and the insert-only code rule (this worktree's own functions only; B's stubs stay for the overseer at landing).
- `docs/briefs/coach-inbox-list.md` — this file.

Anything outside this list is a question back to the overseer, not a change.

## Deploy implied

`deploy.sh` (the Streamlit app) — read-only change, no schema/grant change to
`private_chat`. The overseer runs it from `main` after merge, then checks the
tab live against the real (currently empty) tables.

## Context

- Drafted 2026-09-25 from `20260924-HANDOFF-questions-zone-coach-inbox.md` (not
  present in this worktree checkout — lives with the overseer/main history)
  plus Martin's decisions of 2026-09-25, recorded in the spec's Decisions
  section and in `## Settled 2026-09-25 (Martin)` above.
- Overseer memory message, received 2026-09-25 (this worktree does not use the
  memory bank itself — see CLAUDE.md Roles):
  1. Every coach sees every thread; any coach may reply in any of them. Badge
     counts waiting threads (member wrote last), same for everyone, nothing
     stored. Admin gets a `grant_coaches` row. The spec is agreed text.
  2. Access: app SA `170880920649-compute@` has `dataViewer` on
     `lesko-486515.private_chat.private_threads` and `privateChatAppender` on
     `private_messages` (both EU, same region as `bigtribebuilders.grant_helpdesk`,
     so a join with `core_members` works). Both tables are EMPTY and the zone's
     writes are off — test only against a stub or seeded fixture. This slice
     never writes to `private_chat`.
  3. TRAP (2026-08-19, this repo): `bq_writes.trigger_assignment_refresh()`
     fires a REMOTE Dataform run; pytest has triggered it before and rebuilt
     `grant_tickets` from the committed `.sqlx`, damaging live data. Keep tests
     offline — no live BQ writes, no Dataform, no new `.sqlx` files this slice.
  4. Preview harness: `HELPDESK_PREVIEW=1` in `config.py` repoints
     `TICKETS_TABLE`/`META_TABLE` to `bigtribebuilders.grant_helpdesk_preview`.
     Local run: `DEV_USER=martin.j.menke@gmail.com streamlit run app.py`.
     Playwright (anaconda py3.13) works for headless UI checks.
  5. Existing patterns: parameterised queries use `bigquery.ScalarQueryParameter`
     (see `bq_reads.search_members`). Cached loaders get a specific `.clear()`,
     not `st.cache_data.clear()`. A BQ NULL comes back as a pandas NaN — guard
     it before string methods (the 00053 crash).
  6. A5's `BTB_ALERT` wiring waits until worktree B (`coach-inbox-alert`) lands
     `raillog.py`; merge `origin/main` then, do not copy the helper early.
- `core_members` lives at `{PROJECT_ID}.dataform.core_members`, filtered
  `client_id = 'lesko_4022250'`, `member_status = 'active'` for lookups
  (`bq_reads.search_members`) — `load_member_questions` follows the same
  project/dataset path for the join.

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
- Brief filled in and committed (commit 38778be): done-when, may-touch, deploy
  implied, context (incl. overseer's memory message of 2026-09-25).
- Slice A1 tracer built and committed:
  - `coach_inbox.py` (new): `merge_into_tickets(tickets, questions)` — R1
    (waiting questions first, then everything newest `last_activity_at`
    first) + R2 (`source` column: `ticket` / `member_question`).
  - `tests/test_coach_inbox.py` (new): 3 tests, all green —
    `test_merge_into_tickets_puts_waiting_questions_first_then_newest_activity`,
    `test_merge_into_tickets_assigns_source_column`,
    `test_merge_into_tickets_hardcoded_thread_tracer`.
  - Red-then-green proven by hand: moved `coach_inbox.py` to the scratchpad
    dir, reran `pytest tests/test_coach_inbox.py -k merge` → `ModuleNotFoundError`
    (red), moved it back → 3 passed (green).
  - `app.py`: added `import pandas as pd`, `import coach_inbox`; in
    `tab_main`, right before the "Ticket list" section, built one hardcoded
    member-question row and called `coach_inbox.merge_into_tickets(tickets,
    _hardcoded_member_question)`; in `render_ticket_table`, added
    `_is_question = row.get("source") == "member_question"` gating, with the
    ticket-only fields (urgency/ticket_status/domain/space_id/follow-up) read
    only in the non-question branch, since the hardcoded row doesn't carry
    them and they come back as NaN, not None, after the concat (see trap
    below). A "Member question" badge (inline style, no new CSS file — none
    of the `lesko-ui`/`static` CSS files are in this brief's May touch) is
    prepended to the member-name div, a "⏳ waiting"/"✓ Answered" status
    string stands in for the urgency dot, and the action `st.selectbox` is
    skipped entirely (`if not _is_question:` around it) — no dropdown for
    member questions yet, per the spec's R2 and the gate's mock-up.
  - Ran the app locally (`DEV_USER=martin.j.menke@gmail.com streamlit run
    app.py --server.port 8580`), drove it with Playwright (headless
    chromium), screenshot confirmed: Anna K.'s row on top with the "Member
    question" badge and "⏳ waiting" status, no action dropdown, real
    tickets unaffected below it, no server-side error in the log.
  - Committed as one commit (`coach_inbox.py`, `tests/test_coach_inbox.py`,
    `app.py`).
  - Messaged `helpdesk-opzichter`: "slice A1 done - continue or re-steer?"
    with the proof line above.

In flight:
- Waiting on the overseer's reply before starting A2 (real
  `load_member_questions` read against `private_chat`, needs
  `config.PRIVATE_CHAT_DATASET` — not added yet, deferred to A2 by design).

Next:
1. On go-ahead: build `load_member_questions` (A2) against `private_chat`,
   joined to `core_members` for names; add `config.PRIVATE_CHAT_DATASET`.
2. Then A3 (`waiting_count`, `🎫 Tickets (N new)` label), A4
   (`tests/test_private_chat_insert_only.py`), each its own slice, each
   stopped-and-reported before the next starts.
3. A5 (read failure → `st.error` + `report_source_failure`) only after
   worktree B lands — do not start it before then.

Traps (with dates):
- 2026-09-25 (from overseer memory): `bq_writes.trigger_assignment_refresh()`
  fires a REMOTE Dataform run; pytest has triggered it before and rebuilt
  `grant_tickets` from committed `.sqlx`, damaging live data. Keep tests
  offline, no live BQ writes, no Dataform, no new `.sqlx` this slice.
- 2026-09-25: `private_chat.private_threads`/`private_messages` are EMPTY and
  the zone's writes are off — A2's "local run against the real tables" proof
  will show an empty frame, not seeded data; that's expected, not a bug.
- 2026-09-25: no CSS file (`lesko-ui/*.css`, `static/*.css`) is in this
  brief's May touch — the "Member question" badge uses an inline `style=`
  span, not a new CSS class, to stay in scope.
- 2026-09-25: the "00053 crash" trap is real and hit in this slice —
  `merge_into_tickets` concatenates the hardcoded question row (no
  urgency/ticket_status/domain/space_id) with real ticket rows that have
  those columns; pandas fills the question row's missing cells with `NaN`,
  and `NaN or "default"` does NOT fall back (unlike `None`) because
  `bool(float('nan'))` is `True` — crashed `render_ticket_table` with
  `AttributeError: 'float' object has no attribute 'lower'` at the urgency
  line. Fixed by never reading those ticket-only columns for a
  member-question row at all (branch on `_is_question` first), not by
  patching the `or`/`.lower()` idiom in place. Any later field added to
  member-question rows needs the same branch, not an `isinstance` patch.
