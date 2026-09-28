# Brief: coach-inbox-reply

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

Coach reply box in the Tickets tab: coach_inbox.add_coach_reply INSERTs one coach message into lesko-486515.private_chat.private_messages via INSERT...SELECT FROM private_threads (uuid4 message_id, author_member_id from grant_coaches, body stripped 1-4000 chars, False on unknown thread, body never logged); failed write -> BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED + st.error; fill the add_coach_reply spec stub; tests red first; insert-only guard stays green

## Done when

`/opt/anaconda3/bin/python -m pytest tests/test_coach_inbox_reply.py -q -p no:cacheprovider`
is green, red first against `origin/main`, proving `coach_inbox.add_coach_reply`:
- writes role `'coach'` as a SQL literal (not a parameter) and a fresh uuid4 `message_id` each call
- writes `author_member_id` exactly as passed in (app.py resolves it from `grant_coaches` via the
  existing `bq_client.get_coach_by_login_email`; the admin has a row there too, so this needs no
  special case)
- strips the body and refuses (returns False, no query sent) anything outside 1-4000 chars after
  stripping; 1 char and 4000 chars both succeed
- returns False, having still sent the query, when zero rows were written (unknown `thread_id`)
- on a write exception: returns False, calls `report_source_failure("write", err)` (same runnable,
  `SOURCE_FAILED`), and never puts the body in that line or in any other output
- does not check who a thread is assigned to — the same call succeeds for any `author_member_id`
- full `pytest tests/` stays green afterwards, including the untouched
  `tests/test_private_chat_insert_only.py` guard (an INSERT is not a forbidden keyword, so this is
  expected to need no change, only proof it still holds).

Spec: docs/specs/modules/coach_inbox.md unchanged — `add_coach_reply`'s stub already carries the
agreed rules this task implements; a worker never edits docs/specs/ (DECISION BY MARTIN 2026-09-24),
so turning its R-lines from agreed-prose into the numbered `R1:` form the other functions use is
left for the overseer and is not required for this task's done-when.

## May touch

Module: `coach_inbox` (see `docs/specs/modules/coach_inbox.md`, `docs/specs/INDEX.md`).
- `coach_inbox.py` — add `add_coach_reply`, nothing else.
- `app.py` — the reply box in a member-question row (a plain `st.form`, not `st.dialog`: production
  runs Streamlit 1.58, local runs 1.45.1, and a dialog's checkbox-rerun behaviour differs between
  them), wired to `bq_client.get_coach_by_login_email(current_user)` for `author_member_id` and
  `load_member_questions.clear()` (not `st.cache_data.clear()`) on a successful send.
- `tests/test_coach_inbox_reply.py` (new).

## Deploy implied

`deploy.sh` (the app). The worktree session never runs it — the overseer does, from `main`, after
the merge, per the parent brief's "Overseer after A" step (already done for slice A).

## Context

- Parent brief/spec: this file's own "Later — coach-inbox-reply" section (above) and
  `docs/specs/modules/coach_inbox.md`'s `add_coach_reply` stub carry the full agreed contract
  (INSERT...SELECT shape, uuid4 message_id, stripped 1-4000 char body, False on unknown thread,
  author_member_id from grant_coaches, no coach-to-thread restriction, no body in logs). Zone-side
  contract: `lesko-questions-zone` `docs/specs/modules/private-chat.md`, "Helpdesk access" — the
  helpdesk's service account already holds a `dataViewer` grant on `private_threads` and a custom
  `privateChatAppender` role (`get`, `getData`, `updateData`) on `private_messages`; insert-only is
  a code contract IAM cannot itself enforce, which is exactly what
  `tests/test_private_chat_insert_only.py` guards.
- Slice A (`coach-inbox-list`) has already landed on this branch's history (visible in `git log`)
  and slice B (`coach-inbox-alert`) too — `raillog.py`, `report_source_failure`, and
  `load_member_questions` all already exist and are reused unchanged here.
- `bq_writes.save_standard_reply` is this repo's existing pattern for a parameterised
  `bigquery.ScalarQueryParameter` write with a fresh uuid4 id; `bq_writes.py:214-215` is the
  existing pattern for reading `job.num_dml_affected_rows` after `.result()`.
- Overseer's memory-bank message (sent right after this worktree started, read here — not
  resent by wt-new.sh into the brief itself) supplied: the exact INSERT...SELECT contract, the
  zone spec pointer, and five traps — (1) parameterised queries only, copy `save_standard_reply`,
  raw newlines break a BQ string literal; (2) tests must use a fake client only, never touch
  production BigQuery, and never trigger `bq_writes.trigger_assignment_refresh`; (3) `HELPDESK_PREVIEW`
  does not cover `private_chat`, only the `PRIVATE_CHAT_DATASET` env var does; (4) prefer a plain
  `st.form` over `st.dialog` (Streamlit 1.58 prod vs 1.45.1 local behave differently); (5) after a
  write, clear only `load_member_questions`'s own cache, never `st.cache_data.clear()`. Also: this
  is "groot mode" — stop at every gate and after every slice, report to the overseer by message, and
  wait for its relay of Martin's answer before continuing. This brief has no further internal
  gates/slices of its own (the parent brief's gates were already filled and approved before this
  worktree existed), so this task is being treated as its own one-slice unit: report once red-then-
  green is proven and `wt-done.sh --check` passes, then wait.

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
- Brief filled in (f6d005a), `add_coach_reply` implemented and app.py wired (717e3b9, 5520fc0,
  3861923), first report sent, review came back FAIL: 1 blocker, 4 minors, 2 process points.
- Blocker fixed: `add_coach_reply` now returns `coach_inbox.ReplyResult` (OK / REFUSED /
  UNKNOWN_THREAD / WRITE_FAILED), not a bare bool — a None `author_member_id` is refused inside
  the function too, not just in app.py (aad02d9). app.py branches on the result so a blank body,
  an unknown thread and a write failure each get their own message; only the last invites a retry
  (100a3f1).
- Minor fixes: the reply form keeps `clear_on_submit=False` and only clears the text box itself
  on the OK path, so a failed send no longer loses what the coach typed (ffe0ea2). The
  `author_member_id` lookup (`_lookup_coach_member_id` in app.py, replacing the cached
  `_cached_coach_member_id`) now catches a raised exception or a bad `member_id` (e.g. NaN) and
  reports `SOURCE_FAILED` instead of failing the whole tab, and is no longer cached — it ran once
  per reply send already, and caching None made a newly linked coach wait out the cache (203bc1d).
- Full `pytest tests/ -q -p no:cacheprovider`: 127 passed after every commit above.
- Remaining from review: refresh this State section (this edit) and add the fire-drill plan to
  `## Done when` (next commit) — both brief-only, no code.

In flight: none — tree clean, all fixes above committed.

Next:
1. Add the write-path fire drill to `## Done when` (brief-only commit).
2. `git add -N .`, `git status` clean check, `wt-done.sh --check coach-inbox-reply`.
3. Report to helpdesk-opzichter: branch, commit range since the first report, HEAD sha, which
   finding each commit fixed, red-then-green proof, deploy implication (still overseer-only).
   Per the overseer's message: from now on every step ends with a message to it, then stop —
   do not continue past this report without a reply.
4. Watch for the overseer pushing the `add_coach_reply` spec-stub fill to `origin/main` (it said
   it would, after this review) and `git merge origin/main` once that lands, before the next report.

Traps (with dates):
- 2026-09-28 (overseer): parameterised queries only (bigquery.ScalarQueryParameter); copy
  bq_writes.save_standard_reply's shape; raw newlines break a BQ string literal.
- 2026-09-28 (overseer): tests must use a fake client only — never touch production BigQuery,
  never trigger bq_writes.trigger_assignment_refresh.
- 2026-09-28 (overseer): HELPDESK_PREVIEW does not cover private_chat; only the
  PRIVATE_CHAT_DATASET env var does.
- 2026-09-28 (overseer): prod Streamlit is 1.58 (unpinned), local is 1.45.1 — st.dialog
  checkbox-rerun behaviour differs between them; prefer a plain st.form in the row.
- 2026-09-28 (overseer): after a write, clear only the specific cache
  (load_member_questions.clear()), never st.cache_data.clear().
- 2026-09-28 (overseer): pytest runs only under
  /opt/anaconda3/bin/python -m pytest tests/ -q -p no:cacheprovider.
- 2026-09-28: this worktree has no run-suite.sh (unlike the generic worker instructions'
  example) — run pytest directly with the command above.
- 2026-09-28 (overseer, review): groot mode means a message after every step, not just every
  slice — this whole task went start-to-done without a checkpoint; from the next report onward,
  stop after each one and wait.
