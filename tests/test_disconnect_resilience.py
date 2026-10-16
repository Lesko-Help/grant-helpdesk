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

# The floor, not the value. 900s is what the brief deploys; a guard that
# demanded exactly 900 would go red on a deliberate raise to 1200, which is
# not a regression. What matters is that it is far longer than the 120s
# default that was deleting sessions mid-shift.
MIN_DISCONNECTED_SESSION_TTL = 600


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
