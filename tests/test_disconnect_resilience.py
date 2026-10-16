"""Guards for the three deployed settings that decide what a dropped
websocket costs a coach, and for the wiring that deploys the watcher.

Why these are source-walking tests rather than runtime ones: all three
settings only exist in a file that a deploy ships — there is no running object
to ask. A test that started the app would prove the app can start, not that
Cloud Run was told to keep the session. See docs/briefs/disconnect-resilience.md.

Run this file on its own:
    /opt/anaconda3/bin/python3 -m pytest tests/test_disconnect_resilience.py
Never bare `pytest tests/` — tests/smoke_test.py writes to live BigQuery.
"""

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# The floor, not the value: a guard demanding exactly 1800 would go red on a
# deliberate raise, which is not a regression. The floor is 1800 because that
# is what the measurement asked for - the coach's reconnect gaps cluster at
# 15-17 minutes, so anything under half an hour leaves most of them losing
# the session (76 of them still lost at 900s, against 9 at 1800s, over the
# same three real days).
MIN_DISCONNECTED_SESSION_TTL = 1800


def _config():
    """In: nothing. Out: the parsed .streamlit/config.toml the image ships.
    Why: three tests read it, and tomllib gives a real parse instead of a
    regex that a commented-out line would fool."""
    with open(REPO / ".streamlit" / "config.toml", "rb") as handle:
        return tomllib.load(handle)


def test_disconnected_session_ttl_outlives_a_short_drop():
    """A websocket that dies must not take the coach's session with it.

    Streamlit deletes a disconnected session after server.disconnectedSessionTTL
    (default 120s) — filters, open dialog, half-typed reply and all. Measured
    2026-10-16: 128 of one coach's 222 reconnect gaps were longer than that.
    """
    ttl = _config().get("server", {}).get("disconnectedSessionTTL")
    assert ttl is not None, (
        "server.disconnectedSessionTTL is unset, so Streamlit's 120s default "
        "applies and a drop longer than two minutes deletes the session"
    )
    assert ttl >= MIN_DISCONNECTED_SESSION_TTL, (
        f"disconnectedSessionTTL is {ttl}s; a coach who steps away from her "
        f"desk needs at least {MIN_DISCONNECTED_SESSION_TTL}s"
    )


def test_deploy_turns_on_session_affinity():
    """A longer TTL is worthless without stickiness.

    Streamlit 1.65.0's own config docs: "If you are using load balancing or
    replication in your deployment, you must enable session stickiness in your
    proxy to guarantee reconnection to the existing session." This service runs
    minScale 1 / maxScale 3 and was measured at 5 instances on 2026-10-15, so a
    reconnect can land on an instance that never held the session.
    """
    deploy = (REPO / "deploy.sh").read_text()
    assert "--session-affinity" in deploy, (
        "deploy.sh does not pass --session-affinity, so a reconnect may land "
        "on a different instance and the longer TTL buys nothing"
    )
    # It has to be part of the deploy command, not a comment or an echo: a
    # flag that only appears in prose would pass a bare substring check while
    # Cloud Run never hears about it.
    deploy_command = deploy.split("gcloud run deploy", 1)[1]
    flag_line = next(
        line for line in deploy_command.splitlines()
        if "--session-affinity" in line
    )
    assert not flag_line.lstrip().startswith("#"), (
        "--session-affinity is commented out inside the deploy command"
    )


def test_streamlit_version_is_pinned_exactly():
    """An unpinned streamlit means the websocket and session machinery this
    brief tunes can change on any rebuild, with no commit to point at. The
    image built 2026-10-06 resolved to 1.65.0; the pin freezes what is live.
    """
    requirements = (REPO / "requirements.txt").read_text().splitlines()
    streamlit_lines = [
        line.strip() for line in requirements
        if re.match(r"^\s*streamlit\b", line)
    ]
    assert streamlit_lines, "requirements.txt no longer requires streamlit"
    assert len(streamlit_lines) == 1, f"streamlit pinned twice: {streamlit_lines}"
    assert re.match(r"^streamlit==\d+\.\d+\.\d+$", streamlit_lines[0]), (
        f"streamlit must be pinned to one exact version, found "
        f"{streamlit_lines[0]!r} — a floating requirement lets a rebuild "
        f"change the session behaviour this branch depends on"
    )


# ── the watcher's wiring ─────────────────────────────────────────────────
# Source-walking again, and for the same reason: a Cloud Run job's env, its
# image contents and the order two gcloud calls run in only exist in files a
# deploy reads. Nothing here calls gcloud.

def _deploy_script():
    """In: nothing. Out: jobs/deploy-watch-disconnects.sh as text. Why: four
    tests read it and one place to change if it is ever renamed."""
    return (REPO / "jobs" / "deploy-watch-disconnects.sh").read_text()


def test_the_watcher_measures_against_the_ttl_the_app_deploys():
    """The whole measurement is "was the gap longer than the TTL". If the
    job's TTL_SECONDS and the app's disconnectedSessionTTL drift apart, the
    weekly mail counts lost sessions against a line the app is not using and
    nobody would notice, because both numbers look plausible on their own.
    """
    deployed = _config()["server"]["disconnectedSessionTTL"]
    match = re.search(r'TTL_SECONDS="\$\{TTL_SECONDS:-(\d+)\}"', _deploy_script())
    assert match, "TTL_SECONDS default not found in the deploy script"
    assert int(match.group(1)) == deployed, (
        f"the job measures against {match.group(1)}s while the app deploys "
        f"{deployed}s — one of the two is lying about what a coach loses"
    )


def test_the_watcher_image_carries_its_alert_helper():
    """watch_disconnects.py imports raillog at module scope. A Dockerfile that
    copies only the script builds and starts fine, then dies on the import —
    at which point the rail that was supposed to report failure is the thing
    that failed."""
    dockerfile = (REPO / "jobs" / "Dockerfile.watch_disconnects").read_text()
    copy_line = next(line for line in dockerfile.splitlines()
                     if line.startswith("COPY"))
    assert "watch_disconnects.py" in copy_line
    assert "raillog.py" in copy_line, (
        "the image does not carry raillog.py, so the job cannot report its "
        "own failure"
    )


def test_the_weekly_jobs_silence_window_outlives_its_schedule():
    """Rule 4 says silence is a failure — but a silence window shorter than
    the schedule turns the heartbeat itself into the noise. This job runs
    weekly, so the window has to be more than seven days."""
    alerts = (REPO / "jobs" / "deploy-alerts.sh").read_text()
    match = re.search(
        r'WATCH_SILENCE_WINDOW_SECONDS="\$\{WATCH_SILENCE_WINDOW_SECONDS:-(\d+)\}"',
        alerts)
    assert match, "WATCH_SILENCE_WINDOW_SECONDS not found in deploy-alerts.sh"
    window = int(match.group(1))
    assert window > 7 * 24 * 3600, (
        f"a {window}s silence window on a weekly job pages every week"
    )


def test_the_watch_metric_is_created_before_the_policy_that_names_it():
    """A Cloud Logging metric counts only lines written after it exists, and a
    policy that references a metric which is not there yet fails to apply. The
    same ordering the Dataform silence block already keeps."""
    alerts = (REPO / "jobs" / "deploy-alerts.sh").read_text()
    creates_metric = alerts.index('gcloud logging metrics create "$WATCH_METRIC_NAME"')
    applies_policy = alerts.index('apply_policy "$TITLE_WATCH" "$PAYLOAD_WATCH"')
    assert creates_metric < applies_policy, (
        "deploy-alerts.sh applies the watch-disconnects policy before the "
        "metric it names exists"
    )


# ── the alert helper itself ──────────────────────────────────────────────

def test_both_raillog_copies_agree_on_the_codes():
    """Two copies of one helper, per the repo's own note in raillog.py. The
    global rule's whole reason for naming a canonical file is that copies
    drift silently — so the drift is a test, not a hope."""
    import ast as ast_module

    def codes(path):
        tree = ast_module.parse((REPO / path).read_text())
        for node in ast_module.walk(tree):
            if (isinstance(node, ast_module.Assign)
                    and any(getattr(t, "id", None) == "CODES" for t in node.targets)):
                return {el.value for el in node.value.elts}
        raise AssertionError(f"no CODES in {path}")

    app_codes = codes("raillog.py")
    job_codes = codes("jobs/raillog.py")
    assert app_codes == job_codes, (
        f"the two raillog copies have drifted: "
        f"only in app {app_codes - job_codes}, only in jobs {job_codes - app_codes}"
    )
    assert "SESSION_LOST" in job_codes, (
        "jobs/watch_disconnects.py raises SESSION_LOST; without it in CODES "
        "raillog silently rewrites it to UNEXPECTED and the mails stop "
        "grouping"
    )


def test_every_btb_alert_print_flushes():
    """Global CLAUDE.md rule 2, the `ast` form. stdout to a pipe is
    block-buffered, so an unflushed marker reaches Cloud Logging only when the
    process exits — and a killed job loses its buffer, which means the alert
    most likely to vanish is the one for the failure that killed it.

    Why a source walk and never a capture-and-assert: a test that runs the
    helper and reads back what it printed sees the line either way, because
    the buffer flushes when the process ends. It cannot tell a flushed print
    from an unflushed one, so it passes over exactly the bug it was written
    for. This walks every marker print in the whole file, including the one
    somebody adds next month.
    """
    import ast as ast_module

    checked = 0
    for path in ("raillog.py", "jobs/raillog.py"):
        tree = ast_module.parse((REPO / path).read_text())
        for node in ast_module.walk(tree):
            if not (isinstance(node, ast_module.Call)
                    and getattr(node.func, "id", None) == "print"):
                continue
            source = ast_module.unparse(node)
            if "BTB_ALERT" not in source:
                continue
            keywords = {kw.arg for kw in node.keywords}
            # A marker written to stderr needs no flush: stderr is
            # line-buffered even when piped.
            if "file" in keywords:
                continue
            checked += 1
            flush = next((kw for kw in node.keywords if kw.arg == "flush"), None)
            assert flush is not None and getattr(flush.value, "value", False) is True, (
                f"{path}: a print emitting BTB_ALERT does not pass flush=True"
            )
    assert checked, (
        "no BTB_ALERT print found in either raillog copy — this guard would "
        "pass vacuously the day the helper stops printing"
    )
