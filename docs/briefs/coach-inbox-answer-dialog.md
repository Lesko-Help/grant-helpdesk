# Brief: coach-inbox-answer-dialog

Stages: oneshot — DOWNGRADED (dropped: product · architecture · design · slices)
Downgraded: repo default "groot" wanted product · architecture · design · slices.
Reason: UI-only rewiring: member-question rows get the regular action dropdown with Answer opening a dialog around the already-reviewed reply_form/add_coach_reply; no new data, table or write path. Scope chosen by Martin 2026-09-29.

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)


## Goal

Member-question rows use the same action dropdown as other Questions tickets: only 'Answer' shown, which opens an st.dialog with the member's private thread and the reply box (reply_form.on_reply_submit, add_coach_reply unchanged); remove the inline reply form from the list; other actions hidden until the workflow slice. Must work on Streamlit 1.58 (production).

## Done when

1. `tests/test_reply_form.py` gains tests for the new dialog-body function (working name `reply_form.render_thread_and_reply`) proving, with real widgets via `streamlit.testing.v1.AppTest`: it renders the thread's messages (member then coach, in order); on `ReplyResult.OK` it clears the text box and calls `st.rerun()` (the same close-the-dialog idiom `show_flag_dialog`/`show_assign_dialog`/`show_delete_dialog` already use); on any other `ReplyResult` it shows that result's own message (`reply_form.reply_result_message`, unchanged) and keeps the typed text. Red first: write the test against the not-yet-existing function (import error / AttributeError), then green after it's added.
2. The same new tests pass unmodified under a second, separate Streamlit install — 1.58.0 — in a scratch venv (`/opt/anaconda3/bin/python -m venv`, never touching the base anaconda install), proving no behaviour gap between local 1.45.1 and production 1.58.
3. `app.py`'s member-question row: the inline `st.form` reply box (the old `~1492-1531` block) is gone; the row instead gets the same `st.selectbox` action dropdown as a ticket row, but built from a new `_MEMBER_QUESTION_OPTS = ["— action —", "Answer"]` instead of `_ACTION_OPTS[lane]`, so Close/Flag/Assign/Delete/lane-move stay hidden. Picking "Answer" goes through the existing `_act_triggered_*` → `_pending_action` dispatch (unchanged) and a new `if _pa["row"].get("source") == "member_question":` branch opens a new `show_member_question_dialog(content_id, row_dict)` (`@st.dialog`) instead of `show_ticket_dialog`. This part is UI wiring only, not independently unit-tested (app.py cannot run under AppTest — login gate, live BigQuery loaders — same limitation `tests/test_reply_form.py`'s own docstring already states for the existing inline form; unchanged by this task).
4. `/opt/anaconda3/bin/python -m pytest tests/ -q -p no:cacheprovider` stays fully green (127 pre-existing + new).
5. `add_coach_reply`, `on_reply_submit`, `reply_result_message`, and coach_inbox's SQL are untouched — this task only moves where the existing reply UI is drawn from (inline row → dialog).

Spec: unchanged because this is UI-only rewiring inside `app.py`'s Tickets-tab rendering — no new function, table, or write path; `coach_inbox.md`'s existing `add_coach_reply` R6 line ("Tickets tab shows a reply form under each member-question row") describes *where* the reply box lives, which this task changes, but the overseer owns that wording — flagged under Spec proposals below rather than edited here.

## May touch

Module: `coach_inbox` (see `docs/specs/modules/coach_inbox.md`).
- `app.py` — the Tickets-tab `render_ticket_table` fragment (the action-dropdown block and the inline reply-form block, both inside the `len(grp) == 1` branch, roughly lines 1420-1560) and the `_pending_action` dispatch block below `render_ticket_table(...)` (roughly lines 1771-1782); a new `_MEMBER_QUESTION_OPTS` constant near `_ACTION_OPTS` (~line 1286); a new `show_member_question_dialog` function near the other `@st.dialog` functions (~line 1156-1236).
- `reply_form.py` — add the new dialog-body render function; `on_reply_submit` and `reply_result_message` unchanged.
- `tests/test_reply_form.py` — new tests only, existing ones untouched.
- Nothing in `coach_inbox.py`, `config.py`, or any spec/migration/deploy file.

## Deploy implied

`deploy.sh` (the app). The worktree session never runs it — the overseer does, from `main`, after the merge.

## Context

Links: `docs/specs/modules/coach_inbox.md` (spec, read in full), `docs/briefs/coach-inbox-reply.md` (prior slice's decisions).

Overseer's stop-rules message (received after wt-new.sh, 2026-09-29): klein mode, one pass then a review; branch-only, never push/deploy/touch settings; don't edit docs/specs (ask instead); red first; report HEAD/commits/test count/red-green proof/deploy-implied and stop; never write the Verdict line. Where things are today: `_ACTION_OPTS` at app.py:1286, `_on_action_change`/`_act_triggered_<lane>` at ~1540, dispatch to `_pending_action` at ~1341-1383, dialogs open at ~1771 (`show_ticket_dialog` for "Answer", `show_flag_dialog`, `show_assign_dialog`, `show_delete_dialog`). `thread_id` is `content_id` without `pc:`.

Overseer's memory-bank message (received same time, 2026-09-29, line numbers as of main `3d33ecb`):
1. Streamlit 1.45.1 (local): `@st.dialog` doesn't reliably rerun on a widget change when opened from a pending-action dispatch outside an `@st.fragment`; old workaround was always-visible widgets. On 1.58 (production), headless Playwright showed `on_change` inside `@st.dialog` does fire. Playwright is installed under anaconda py3.13 (`python3 -m playwright install chromium` if chromium missing).
2. Keep the reply submit as the `on_click` callback `reply_form.on_reply_submit`. Show all four `ReplyResult` outcomes distinctly inside the dialog.
3. Known review gap: past tests copied app.py's reply wiring instead of calling the real code. Moving the wiring is the chance to make a test go through the real wiring — extract the dialog body into a function in `reply_form.py` (or a small module) and test that, since app.py itself can't be imported under AppTest.
4. Dialog patterns to reuse: the "Insert standard reply" dropdown (optional, not required); wrap slow fetches in `st.spinner`; give any background fetch a timeout.
5. Undecided: reply-to-thread vs reply-to-message — build for the thread, as today (this task doesn't touch that).
6. Tests must never reach `bq_writes.trigger_assignment_refresh` (fires a live Dataform run).

**Design decision made in this worktree (2026-09-29), see Spec proposals:** the new dialog needs no fresh BigQuery read for the thread — `load_member_questions`'s row already carries the full `messages` list (oldest first, `{author_role, body, created_at}`), and that row (`row_dict`, via `_pending_action["row"]`) is already threaded through the existing dispatch. `show_member_question_dialog(content_id, row_dict)` renders `row_dict["messages"]` directly; no new `_cached_*` fetch, no new coach_inbox function.

**AppTest limitation found while probing (2026-09-29):** `streamlit.testing.v1.AppTest` does not faithfully reproduce a real browser's "an already-open `@st.dialog` keeps re-invoking itself on internal widget interactions even though the top-level script's own one-shot open-flag was already reset" behaviour — in a scratch probe, gating a dialog call behind a one-shot flag (exactly `app.py`'s `_pending_action` pattern) and then triggering ANY further `.run()` (even from the correct "click Send" interaction) caused AppTest to skip re-invoking the dialog function, i.e. it looked "closed" regardless of outcome. This makes AppTest unsuitable for proving the *open-dispatch persistence* half of memory item 1 either locally or under 1.58 — that would need real Playwright (as memory item 1 says was already done for `on_change`). Given this task's downgraded, UI-only scope, this worktree treats the open/close *dispatch* mechanism as already proven by existing precedent (it is the exact same `_pending_action` → single `@st.dialog` call → button `on_click` → `st.rerun()` idiom `show_flag_dialog`/`show_assign_dialog`/`show_delete_dialog` already use in production), and only proves the NEW `reply_form` dialog-body function's own logic (render, per-outcome message, clear-and-rerun on OK) via AppTest, calling it directly and unconditionally the same way `tests/test_reply_form.py`'s existing tests call `on_reply_submit` — not wrapped in a one-shot open-flag. This is reported to the overseer rather than silently assumed.

## Spec proposals

- `docs/specs/modules/coach_inbox.md`, `add_coach_reply` R6: currently says "The Tickets tab shows a reply form under each member-question row." After this task it should say the reply box lives inside an `@st.dialog` opened from the row's Answer action, not inline under the row. Rest of R6 (per-outcome messages, keep-text-unless-OK, clear only `load_member_questions`'s cache) is unchanged behaviour, just relocated.

## Agentic review

### Verdict
Verdict: FAIL — overseer review of 3dfa6df (2026-09-29): checks 1-4 pass (clean tree, 0 behind, 4 files, 137 passed, fake clients only; wiring, key uniqueness, callback-only resets, unchanged add_coach_reply/on_reply_submit/reply_result_message/SQL all confirmed). 1 blocker, 4 minors — see Findings.

### Findings
1. BLOCKER — `test_render_thread_and_reply_on_ok_clears_the_box_and_reruns_to_close` (tests/test_reply_form.py:206) still passed with `reply_form.py`'s `st.rerun()` replaced by `pass` in a scratch copy — the box-cleared assertion can't tell `on_reply_submit`'s own clearing apart from the dialog actually closing, so done-when 1's "calls st.rerun()" was unproven.
2. MINOR — `show_member_question_dialog`'s docstring (app.py:1240) had no Output line.
3. MINOR — nothing proves the live dialog on 1.58 itself (only the extracted function is under test); record a post-deploy smoke check as pending.
4. MINOR — spec R6 wording: left as-is, overseer updates `docs/specs/modules/coach_inbox.md` at landing.
5. MINOR — brief's State → Next named a stale commit range (`dd88c2f..991502b`).

### Fixed in
1. `2334862` — rewrote the OK-path test to count script runs (`st.session_state["runs"]`) across the click, and assert the delta is 2 (submit's own run + the rerun) rather than 1 (submit's run alone). Checked red with `st.rerun()` replaced by `pass` (delta 1, assertion fails), green with it restored (delta 2).
2. `a02ef79` — added "Output: none — draws the dialog; closes via reply_form's st.rerun() on a successful send." to `show_member_question_dialog`'s docstring.
3. Not fixed in code — recorded as a pending post-deploy step below (Context): open Answer, confirm a failed send keeps the dialog open with its error, and an OK send closes it and the row shows Answered. The overseer runs this after deploy.
4. Not fixed — left for the overseer to update at landing, as instructed.
5. This commit — State → Next below now names the real range.

wt-done.sh's check on this is literal: it greps this brief for a line
starting with exactly `Verdict:` at the very start of the line (column 0)
— no bold, no indent, no renamed label, no different case.

### Pending post-deploy smoke check (not yet run — no live deploy from this worktree)
After this lands and deploys: open a member-question row's Answer dialog; send with an empty/invalid state to confirm it stays open with an error and the typed text; then send a real reply and confirm the dialog closes and the row shows Answered. Overseer's to run this, per its review message.

## State

Replaced in full each time the context guard asks you to save — never append another checkpoint.
About 60 lines max. Old traps stay (they are short and worth keeping); everything else gets
overwritten with the current picture.

Done:
- `reply_form.render_thread_and_reply(...)` (reply_form.py) and the app.py wiring
  (`_MEMBER_QUESTION_OPTS`, `show_member_question_dialog`, inline form removed, dropdown and
  `_pending_action`/"Answer" dispatch branch on `source == "member_question"`) — full detail in
  commits 7b1209b and 991502b, and in Done when 1-3 above.
- Overseer review of 3dfa6df: FAIL, 1 blocker + 4 minors (see Agentic review above). Blocker
  fixed: test_render_thread_and_reply_on_ok_... now counts script runs across the submit click
  and asserts the delta is 2 (submit run + the rerun), not just that the box is empty — checked
  red with st.rerun() replaced by pass (delta 1), green restored. Minor 2 fixed (docstring Output
  line). Minor 3 recorded as a pending post-deploy smoke check (Agentic review section). Minor 4
  left for the overseer. Full suite re-verified green: 137 local (1.45.1), 10 under
  $SCRATCH/venv158 (1.58.0).

In flight: none — fix committed, full suite green on both Streamlit versions, wt-done.sh --check
passes. Left to do: report the new range to helpdesk-opzichter and stop.

Next:
1. Report to helpdesk-opzichter with the new commit range (dd88c2f..a02ef79, brief-save commit
   still to follow) and the red-then-green proof for the blocker fix — then stop.

Traps (with dates):
- 2026-09-29 (this worktree): AppTest does not model an already-open `@st.dialog`'s persistence
  across internal reruns when gated by a one-shot flag — see Context. Test the dialog-body
  function directly and unconditionally; don't try to AppTest the open/close dispatch itself.
- 2026-09-28 (overseer, carried from coach-inbox-reply): a widget's own session_state key can
  only be written before that widget is instantiated in the current run — reset it from an
  on_click callback only. app.py can't run under AppTest (login gate, live BigQuery loaders).
- 2026-09-28 (overseer): after a write, clear only `load_member_questions.clear()`, never
  `st.cache_data.clear()`.
- 2026-09-28 (overseer): tests use fake clients only; never reach `bq_writes.trigger_assignment_refresh`.
- pytest command: `/opt/anaconda3/bin/python -m pytest tests/ -q -p no:cacheprovider`.
