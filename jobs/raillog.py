"""grant-helpdesk's own copy of the BTB_ALERT emitter, per the global
CLAUDE.md rule "Unattended code reports its own failure" (decided
2026-09-14).

Vendored here rather than imported from another repo — each job's Dockerfile
(e.g. jobs/Dockerfile.poll_dataform) COPYs only the one .py file it runs plus
this one, so the kit has to live beside the job, not at the repo root or in
another repo, or the import fails at container build time even though it
works locally.

Cloud Run only promotes a log line above severity DEFAULT when the line is a
single JSON object on stdout/stderr carrying a "severity" key. A plain
logging.error(...) or print(...) writes text that lands at DEFAULT no matter
how alarming it reads, and an ERROR-only Cloud Monitoring policy never sees
it — so this prints raw JSON instead of going through the logging module.
"""
import json

REPO = "grant-helpdesk"

# The fixed list from the global CLAUDE.md rule, plus this repo's own
# SESSION_LOST (the rule allows a repo to add codes in its alert helper).
CODES = {
    "AUTH_FAILED",
    "SOURCE_FAILED",
    "SOURCE_EMPTY",
    "ASSERTION_FAILED",
    "QUOTA",
    "STALE",
    "UNEXPECTED",
    # Raised by jobs/watch_disconnects.py: coaches are losing whole
    # sessions to dropped websockets faster than the agreed rate. Not
    # STALE (the data is current) and not UNEXPECTED (this is the exact
    # thing that runnable watches for), so it gets its own word to group
    # on in a Gmail search.
    "SESSION_LOST",
}


def alert(runnable, code, message):
    """Log one structured ERROR line: BTB_ALERT <repo>/<runnable> <CODE>: <message>.

    Like inserting one row into an error log table, except the "table" is
    Cloud Logging and deploy-alerts.sh's Cloud Monitoring policy is the query
    that watches it for the BTB_ALERT text.

    `runnable` names WHAT failed, not necessarily the process calling this —
    poll_dataform_failures.py is one process that watches several Dataform
    actions, so each call names the action being reported on (e.g.
    "grant_ticket_labels"), the same way a log table's source column records
    what broke, not what happened to notice it.

    An unknown `code` falls back to UNEXPECTED rather than raising: this
    function is itself the failure-reporting path, called from inside a loop
    over many invocations, so it must never be the thing that crashes the
    caller mid-alert.
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
