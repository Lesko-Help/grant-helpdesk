"""grant-helpdesk's own copy of the BTB_ALERT emitter, per the global
CLAUDE.md rule "Unattended code reports its own failure" (decided
2026-09-14).

Vendored here, at the repo root, rather than imported from jobs/raillog.py:
the Streamlit app (app.py) is built and run from the repo root, while each
Cloud Run job's own Dockerfile (e.g. jobs/Dockerfile.poll_dataform) COPYs
only jobs/raillog.py alongside the one script it runs — neither build
context can reach a copy that lives in the other, so the kit needs one file
per path rather than one shared import (docs/specs/modules/coach_inbox.md,
"raillog.alert").

Cloud Run only promotes a log line above severity DEFAULT when the line is a
single JSON object on stdout/stderr carrying a "severity" key. A plain
logging.error(...) or print(...) writes text that lands at DEFAULT no matter
how alarming it reads, and an ERROR-only Cloud Monitoring policy never sees
it — so this prints raw JSON instead of going through the logging module.
"""
import json

REPO = "grant-helpdesk"

# The fixed list from the global CLAUDE.md rule. This repo hasn't needed to
# add its own code yet.
CODES = {
    "AUTH_FAILED",
    "SOURCE_FAILED",
    "SOURCE_EMPTY",
    "ASSERTION_FAILED",
    "QUOTA",
    "STALE",
    "UNEXPECTED",
}


def alert(runnable, code, message):
    """Log one structured ERROR line: BTB_ALERT <repo>/<runnable> <CODE>: <message>.

    Like inserting one row into an error log table, except the "table" is
    Cloud Logging and deploy-alerts.sh's Cloud Monitoring policy is the query
    that watches it for the BTB_ALERT text.

    `runnable` names WHAT failed, not necessarily the process calling this —
    coach_inbox.py's report_source_failure() is one caller among possibly
    several in this app, so it names the thing being reported on (e.g.
    "coach-inbox"), the same way a log table's source column records what
    broke, not what happened to notice it.

    An unknown `code` falls back to UNEXPECTED rather than raising: this
    function is itself the failure-reporting path, so it must never be the
    thing that crashes the caller mid-alert.
    """
    if code not in CODES:
        code = "UNEXPECTED"
    # flush=True: a caller that's about to exit non-zero right after this call
    # (see rule 1, "failure looks like failure") could be killed before a
    # buffered stdout line reaches the log agent — this line is usually the
    # last thing a failing run does, so it can't be the one that gets lost.
    print(json.dumps({
        "severity": "ERROR",
        "message": f"BTB_ALERT {REPO}/{runnable} {code}: {message}",
    }), flush=True)
