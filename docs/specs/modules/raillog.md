# raillog
Status: draft
Kind: helper
Summary: the one function that turns a failure into a line Cloud Monitoring can see — `BTB_ALERT grant-helpdesk/<runnable> <CODE>: <message>`, printed as JSON at severity ERROR
Part of: `docs/specs/INDEX.md` · Deploy: `deploy.sh` (the root copy, inside the app image), `jobs/Dockerfile.poll_dataform` (the `jobs/` copy, inside the job image) · Updated: 2026-10-15
Used by: `app.py` and `coach_inbox.py` (the root copy); `jobs/poll_dataform_failures.py` (the `jobs/` copy)
Reads: nothing
Writes: one JSON line on stdout — no file, no table, no HTTP call

## Overview

*What it is for:* turn a failure into one line Cloud Monitoring can see, so that
unattended code cannot fail quietly.
*What it owns:* both copies of the alert core — `raillog.py` at the repo root and
`jobs/raillog.py` — and the exact text of the `BTB_ALERT` line.
*What it depends on:* `json` from the standard library, and nothing else, so that
the failure path cannot fail for want of an import.
*Public entry points:* `alert(runnable, code, message)`.
*Not in scope:* the policies that watch for these lines
(`jobs/alert_payloads.py`, `jobs/deploy-alerts.sh`), deciding *when* to call it
(each caller's own spec), and an `ok()` or heartbeat line — this repo emits none.
*Personal data:* none passes through here; keeping message bodies and member
names out of a line is the caller's rule (`coach_inbox.md`, `report_source_failure` R2).

## The two copies

Two files, same code. `raillog.py` at the repo root is what `import raillog`
finds in the app image, which `deploy.sh` builds from the repo root with
`COPY . .`. `jobs/raillog.py` is what it finds in the job image, which
`jobs/Dockerfile.poll_dataform` builds from `jobs/` with
`COPY poll_dataform_failures.py raillog.py ./`. Neither build context can reach
into the other, so one shared module cannot be shipped to both.

They differ today only in prose: the module docstring's vendoring paragraph, and
two paragraphs of `alert()`'s docstring that name the caller nearest to hand.
Everything the alert rail depends on — the JSON line, `REPO`, `CODES`,
`flush=True` — is byte-identical, and R6 below says it stays that way.

## Functions

### alert(runnable, code, message)

`def alert(runnable, code, message)` — the same signature in both copies.

*What it does:*
- R1: prints exactly one line to stdout: a single JSON object carrying
  `"severity": "ERROR"` and `"message": "BTB_ALERT grant-helpdesk/<runnable> <CODE>: <message>"`.
  One JSON object on one line is the only thing Cloud Run promotes above
  severity DEFAULT; the same text through `logging.error` or a plain `print`
  lands at DEFAULT, where an ERROR-only policy never sees it, however alarming
  it reads.
- R2: `code` is one of `AUTH_FAILED`, `SOURCE_FAILED`, `SOURCE_EMPTY`,
  `ASSERTION_FAILED`, `QUOTA`, `STALE`, `UNEXPECTED`. Anything else becomes
  `UNEXPECTED` rather than raising: this function *is* the failure-reporting
  path, so it must never be the thing that crashes a caller mid-alert.
- R3: the print carries `flush=True`, and the suite proves that by parsing this
  file with `ast` — every `print` in the whole file that emits a `BTB_ALERT`
  marker, not only the ones inside `alert()`, because the one somebody adds next
  month will not be inside `alert()`. A `print` carrying a `file=` keyword is
  exempt: stderr is line-buffered even when piped. The walk fails if it found no
  marker print at all, or it passes vacuously the day the helper stops printing.
- R4: `runnable` names *what* failed, not the process that noticed. `app.py` and
  `coach_inbox.py` both pass `"coach-inbox"`; `jobs/poll_dataform_failures.py`
  passes `"poll_dataform_failures"` for its own breakage and the Dataform action
  name for a failure it is reporting on. The same way a log table's source
  column records what broke, not what happened to see it.
- R5: `REPO` is the literal `"grant-helpdesk"`, never read from the environment.
  The service policy matches on the text `BTB_ALERT grant-helpdesk/`
  (`jobs/alert_payloads.py:228`), so an env var here would let one changed
  variable unhook every policy silently.
- R6: the two copies' code stays identical; only comments may differ. A change
  to one is a change to both, in the same commit.
- R7: it returns `None`, exits nothing and re-raises nothing. Making the failure
  look like a failure — a non-zero exit, a 5xx — belongs to the caller
  (`jobs/poll_dataform_failures.py:296`), so that one swallowed exit code cannot
  also lose the alert line.

*Examples:* `("coach-inbox", "SOURCE_FAILED", "private_chat read failed: Forbidden")`
-> stdout `{"severity": "ERROR", "message": "BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED: private_chat read failed: Forbidden"}`.
`("coach-inbox", "NOT_A_REAL_CODE", "whatever")` -> the same shape with
`UNEXPECTED` in place of the code (R2).

*Inputs:* the name of what failed, one code from R2's list, and a one-line
message with no personal data in it.

*Outputs:* one JSON line on stdout, which Cloud Logging records at ERROR and the
repo's policies match on by its `BTB_ALERT` text.

*Errors:* it has none of its own — an unknown code is absorbed by R2 and nothing
else here can raise. It is the helper that logs `BTB_ALERT grant-helpdesk/<runnable> <CODE>`
on behalf of every caller; what each caller alerts on is in that caller's spec.

*Test:* `/opt/anaconda3/bin/python -m pytest tests/test_raillog_app.py` from the
repo root, no fixture beyond the two calls in the Examples above; observes that
stdout holds one line, that it parses as JSON with `"severity": "ERROR"` and the
exact message (R1), and that an unknown code comes back as `UNEXPECTED` (R2);
red first against a copy of the file with the `severity` key removed. This
covers the root copy only. R3, R5 and R6 are guarded apart from it, in
`tests/test_raillog_kit.py`: one `ast` walk over both files, asserting
`flush=True` on every marker print (R3), `REPO` assigned a string constant equal
to `"grant-helpdesk"` (R5), and the two files equal once comments and docstrings
are stripped (R6). Each guard there is a function from source text to a list of
problems, run against the real files and again against mutated copies held in
memory, so the red proof reruns on every suite run. Never `capsys` or `subprocess.run(...).stdout` as the
proof of R3: the buffer flushes when the process ends, so a read-back sees the
line whether or not the print flushed, and the test passes over exactly the bug
it was written for. Never `pytest tests/` either: that runs `smoke_test.py`,
which writes to the live `ticket_metadata`.

## Open check

1. `jobs/sync_events.py`, `jobs/sync_spaces.py` and `jobs/send_followups.py`
   import no `raillog` and emit no marker — `jobs/Dockerfile` does not copy one
   into their image. All three run unattended, so the global rule 2 says each
   owes a marker and rule 3 an alert. Giving them one is their own task, not
   this helper's; it is written down here so the gap has an owner.

## Decisions

- 2026-10-20: the R3/R5/R6 walk mutates copies in memory rather than files in a
  scratch directory, so its red proof reruns with the suite. That shape proves
  the guard functions catch breakage but *not* that the tests read the real
  files — a wrong path in `COPIES` would leave every mutation test green. So the
  review also broke the real files on disk five ways, including a new unflushed
  marker print outside `alert()`. Repeat that by hand if `COPIES` ever moves.
- 2026-10-15: this spec owns both copies, and `coach_inbox.md` gives up the root
  one. Why: `jobs/raillog.py` belonged to no spec at all while the root copy
  belonged to an app spec, so a change to the pair had nowhere to be described
  once and no owner — the global rule 7, owned or gone.
- 2026-10-15: two files rather than one import (R6 instead of a shared module).
  Why: each build context sees only its own folder, so a single module cannot be
  shipped to both the app image and the job image; the duplication is the price
  of the Dockerfiles, and R6 is what keeps the copies honest.
- 2026-10-15: R3's proof reads this file's source and never its captured output,
  per the global rule of 2026-10-12. Why: five copies of this helper across the
  agency were found printing without `flush=True` while their capture-based
  tests stayed green. Reading source also holds without a deploy, and goes red
  by deleting one `flush=True`.
- 2026-10-15: no `ok()`. Why: the canonical helper covers `ok()` only in a repo
  that has one, and nothing here emits a success or heartbeat line — the app is
  not scheduled, and the one job that alerts is watched by its own policies.
- 2026-09-14 (global rule): the alert core is copied into each repo, not shared
  between repos, from the canonical file named by path,
  `~/Lesko/lesko-inbox/actions/raillog.py`. Why: eighteen files answer to the
  name "Lesko's raillog.py" in three lineages, so a repo seeded from the name
  alone could inherit a copy that prints without flushing.
