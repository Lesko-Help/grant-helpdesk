#!/usr/bin/env python3
"""Weekly watch on what a dropped websocket costs the coaches.

In:  the Cloud Run request log of the grant-helpdesk Streamlit service.
Out: one plain summary line per run, and one BTB_ALERT line when coaches are
     losing whole sessions faster than the agreed rate.
Why: Streamlit keeps a coach's screen — her filters, her open ticket dialog,
     her half-typed reply — in a session held by one container, tied to one
     websocket. When that socket dies the session is kept for
     server.disconnectedSessionTTL seconds and then deleted. A reconnect
     after the TTL gets a brand new session, which the coach experiences as
     the app crashing and losing her work. Measured 2026-10-16 on the 120s
     default: 37-44 of those a working day for one coach. The app now
     deploys with a 900s TTL; this job is how we know whether that held,
     without waiting for somebody to complain again.

What it cannot see: who the coach is. Cloud Run request logs carry a client
IP and no identity, so this reports per IP and the IP-to-person link is
Martin's to make.

Run it by hand over any window:
    python3 jobs/watch_disconnects.py --days 7
    python3 jobs/watch_disconnects.py --days 2 --ttl-seconds 120   # before/after
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from collections import Counter, defaultdict

import raillog

RUNNABLE = "disconnect-watch"

PROJECT = os.environ.get("PROJECT", "bigtribebuilders")
SERVICE = os.environ.get("SERVICE", "grant-helpdesk")

# Streamlit 1.65.0 pings the browser every 30s and closes the socket when a
# pong is 30s late (DEFAULT_WEBSOCKET_PING_INTERVAL / _TIMEOUT, both 30).
# A socket whose life is an exact multiple of 30s therefore died on that
# clock — the network under it went quiet — rather than being closed by the
# coach navigating away. Counting them separates "her line is flaky" from
# "she closed the tab", which are different problems with different owners.
PING_GRID_SECONDS = 30
# Cloud Run logs a grid death as 60.006s, not 60.000s, so the window has to
# be a shade over zero - but in SECONDS. As a fraction of a tick, 0.05 is
# 1.5s wide and counts sockets that died nowhere near the clock.
PING_GRID_TOLERANCE_SECONDS = 0.1

# What the app is deployed with (.streamlit/config.toml). Passed in rather
# than read from the config file: this job runs in its own container and
# never ships the app's config, and the number that matters is the one the
# live service is using.
DEFAULT_TTL_SECONDS = 1800

# Above this, the fix is not holding and Martin should hear about it. One
# reset a day per coach is a bad afternoon; five a day, every day, is the
# problem this branch was written for coming back.
DEFAULT_MAX_RESETS_PER_DAY = 5.0

STREAM_PATH = "_stcore/stream"


class Session(tuple):
    """One websocket: who, which container, when it opened, how long it lived.

    In: the four fields. Out: a comparable, sortable record. Why a tiny class
    rather than a dict — the summary sorts these by start time thousands at a
    time, and a tuple subclass keeps that cheap while still naming the fields
    where they are read.
    """

    __slots__ = ()

    def __new__(cls, client, instance, start, seconds):
        return super().__new__(cls, (client, instance, start, seconds))

    client = property(lambda self: self[0])
    instance = property(lambda self: self[1])
    start = property(lambda self: self[2])
    seconds = property(lambda self: self[3])

    @property
    def closed(self):
        """In: nothing. Out: when the socket died. Why: every gap in the
        summary is measured from here, not from the start."""
        return self.start + dt.timedelta(seconds=self.seconds)

    @property
    def died_on_the_ping_clock(self):
        """In: nothing. Out: True when this socket's life is an exact multiple
        of the 30s ping grid. Why: see PING_GRID_SECONDS — it is the
        fingerprint of a connection the network dropped."""
        if self.seconds < PING_GRID_SECONDS:
            return False
        off_grid = self.seconds % PING_GRID_SECONDS
        distance = min(off_grid, PING_GRID_SECONDS - off_grid)
        return distance < PING_GRID_TOLERANCE_SECONDS


def parse_latency(raw):
    """In: a Cloud Logging latency, either '60.006s' or a number of seconds.
    Out: float seconds, or None when it cannot be read.
    Why: the REST payload spells a duration as a string with a trailing 's'
    while the Python client hands back a timedelta, and this job is fed by
    both (the API in production, synthetic rows in the tests). One reader
    for both keeps the arithmetic in one place.
    """
    if raw is None:
        return None
    if isinstance(raw, dt.timedelta):
        return raw.total_seconds()
    if isinstance(raw, (int, float)):
        return float(raw)
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)s?\s*", str(raw))
    return float(match.group(1)) if match else None


def parse_timestamp(raw):
    """In: an RFC3339 timestamp string or a datetime. Out: an aware datetime
    in UTC, or None. Why: the same two-shapes problem as parse_latency, and
    a naive datetime silently breaks every subtraction downstream."""
    if raw is None:
        return None
    if isinstance(raw, dt.datetime):
        stamp = raw
    else:
        text = str(raw).replace("Z", "+00:00")
        # Cloud Logging writes nanoseconds; fromisoformat takes at most
        # microseconds, so trim the extra digits rather than lose the row.
        text = re.sub(r"\.(\d{6})\d+", r".\1", text)
        try:
            stamp = dt.datetime.fromisoformat(text)
        except ValueError:
            return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone.utc)


def websocket_sessions(entries):
    """In: raw request-log entries, each a dict with httpRequest, timestamp
    and labels. Out: a list of Session, sorted oldest first, holding only the
    websocket entries (/_stcore/stream) that carry both a timestamp and a
    duration. Why: everything downstream is arithmetic on these four fields,
    and keeping the log's shape out of the arithmetic is what lets the tests
    run with no credentials.
    """
    sessions = []
    for entry in entries:
        request = entry.get("httpRequest") or {}
        url = request.get("requestUrl") or ""
        if STREAM_PATH not in url:
            continue
        start = parse_timestamp(entry.get("timestamp"))
        seconds = parse_latency(request.get("latency"))
        if start is None or seconds is None:
            continue
        labels = entry.get("labels") or {}
        sessions.append(Session(
            client=request.get("remoteIp") or "unknown",
            instance=labels.get("instanceId") or "unknown",
            start=start,
            seconds=seconds,
        ))
    sessions.sort(key=lambda session: session.start)
    return sessions


def summarise(sessions, ttl_seconds=DEFAULT_TTL_SECONDS):
    """In: the sessions and the disconnected-session TTL the service is
    deployed with. Out: a dict — per client the sessions seen, the drops that
    died on the ping clock, the resets, and resets per day; plus the totals
    and the worst client. Why: a reset is the only number that matches what a
    coach feels. It is not a log line anywhere — it is a *gap between two
    consecutive* sockets of one client that outlived the TTL, which is why
    this cannot be a Cloud Logging metric and has to be computed here.
    """
    by_client = defaultdict(list)
    for session in sessions:
        by_client[session.client].append(session)

    clients = {}
    for client, their_sessions in by_client.items():
        their_sessions.sort(key=lambda session: session.start)
        resets_by_day = Counter()
        instances = set()
        grid_drops = 0
        for session in their_sessions:
            instances.add(session.instance)
            if session.died_on_the_ping_clock:
                grid_drops += 1
        for earlier, later in zip(their_sessions, their_sessions[1:]):
            gap = (later.start - earlier.closed).total_seconds()
            # A negative gap is two tabs open at once, not a reset.
            if gap > ttl_seconds:
                resets_by_day[later.start.date()] += 1
        days_seen = len({session.start.date() for session in their_sessions})
        resets = sum(resets_by_day.values())
        clients[client] = {
            "sessions": len(their_sessions),
            "ping_clock_drops": grid_drops,
            "resets": resets,
            "days_seen": days_seen,
            "resets_per_day": resets / days_seen if days_seen else 0.0,
            "worst_day": max(resets_by_day.items(), key=lambda kv: kv[1])
                         if resets_by_day else None,
            "instances": len(instances),
        }

    worst = max(
        clients.items(),
        key=lambda kv: (kv[1]["resets_per_day"], kv[1]["resets"]),
        default=None,
    )
    return {
        "ttl_seconds": ttl_seconds,
        "clients": clients,
        "total_sessions": len(sessions),
        "total_resets": sum(c["resets"] for c in clients.values()),
        "worst_client": worst[0] if worst else None,
        "worst_resets_per_day": worst[1]["resets_per_day"] if worst else 0.0,
    }


def reporting_always(today, until_raw):
    """In: today's date and the REPORT_ALWAYS_UNTIL value (an ISO date or
    empty). Out: True while today is before that date. Why: Martin wants one
    guaranteed review mail a week after landing, whatever the numbers say,
    and then wants the job to go back to speaking only when something is
    wrong. A date does that by itself — nobody has to remember to switch a
    flag off. An unreadable value reports (loud beats silent).
    """
    if not until_raw:
        return False
    try:
        return today < dt.date.fromisoformat(str(until_raw).strip())
    except ValueError:
        return True


def verdict(summary, max_resets_per_day=DEFAULT_MAX_RESETS_PER_DAY,
            report_always=False, days=7):
    """In: a summary, the agreed rate, whether this run reports regardless,
    and the window length. Out: (should_alert, message). Why: the one place
    that decides whether Martin's phone buzzes, kept pure so a test can hold
    it to the threshold without a network or a clock.
    """
    worst = summary["worst_resets_per_day"]
    over = worst > max_resets_per_day
    headline = (
        f"{summary['total_resets']} lost sessions across "
        f"{len(summary['clients'])} clients in {days}d; worst {worst:.1f}/day "
        f"({summary['worst_client']}); TTL {summary['ttl_seconds']}s; "
        f"{summary['total_sessions']} websockets"
    )
    if over:
        return True, (
            f"coaches are losing sessions faster than {max_resets_per_day}/day "
            f"— {headline}"
        )
    if report_always:
        return True, f"weekly review, nothing over threshold — {headline}"
    return False, headline


def render(summary, days):
    """In: a summary and the window. Out: the multi-line plain-text report
    printed on every run. Why: the BTB_ALERT line has to stay one grep-able
    line, so the detail a human actually reads lives here, in the log, where
    it costs nothing and is there when Martin opens the run."""
    lines = [
        f"grant-helpdesk websocket sessions over the last {days} days",
        f"  TTL in force: {summary['ttl_seconds']}s "
        f"(a reconnect gap longer than this loses the coach's screen)",
        f"  websockets: {summary['total_sessions']}   "
        f"lost sessions: {summary['total_resets']}",
        "  per client (worst first):",
    ]
    ranked = sorted(
        summary["clients"].items(),
        key=lambda kv: (-kv[1]["resets_per_day"], kv[0]),
    )
    for client, stats in ranked:
        worst_day = stats["worst_day"]
        worst_text = f"{worst_day[1]} on {worst_day[0]}" if worst_day else "none"
        lines.append(
            f"    {client}: {stats['sessions']} websockets, "
            f"{stats['ping_clock_drops']} dropped on the 30s ping clock, "
            f"{stats['resets']} lost sessions "
            f"({stats['resets_per_day']:.1f}/day, worst day {worst_text}), "
            f"{stats['instances']} instance(s)"
        )
    return "\n".join(lines)


def log_filter(project, service, days, now=None):
    """In: project, service, window and optionally the clock. Out: the Cloud
    Logging filter string for that service's websocket requests. Why: pulled
    out so a test can pin the filter without calling Google — a filter that
    quietly selects the wrong log is the one failure this job cannot notice
    about itself."""
    now = now or dt.datetime.now(dt.timezone.utc)
    since = (now - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f'logName="projects/{project}/logs/run.googleapis.com%2Frequests" '
        f'AND resource.labels.service_name="{service}" '
        f'AND httpRequest.requestUrl:"{STREAM_PATH}" '
        f'AND timestamp>="{since}"'
    )


def fetch_entries(project, service, days):
    """In: project, service, window. Out: the request-log entries as dicts.
    Why: the only part of this job that talks to Google, kept apart from the
    arithmetic so everything above it is testable offline. Raises on failure
    rather than returning nothing — an empty read and a broken read must not
    look the same (see main)."""
    from google.cloud import logging_v2

    client = logging_v2.Client(project=project)
    entries = []
    for entry in client.list_entries(
        resource_names=[f"projects/{project}"],
        filter_=log_filter(project, service, days),
        order_by=logging_v2.DESCENDING,
        page_size=1000,
    ):
        entries.append({
            "timestamp": entry.timestamp,
            "httpRequest": entry.http_request or {},
            "labels": entry.labels or {},
        })
    return entries


def main(argv=None):
    """In: the command line. Out: exit 0 when the measurement worked, 1 when
    this job itself failed. Why exit 0 even on a bad finding, unlike
    poll_dataform_failures.py: the silence policy watches this job's
    successful executions, so exiting 1 every week while a coach's line is
    still flaky would fire the "went silent" alert too and turn one problem
    into two mails. The finding travels in the BTB_ALERT line.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int,
                        default=int(os.environ.get("WINDOW_DAYS", 7)))
    parser.add_argument("--ttl-seconds", type=int,
                        default=int(os.environ.get("TTL_SECONDS",
                                                   DEFAULT_TTL_SECONDS)))
    parser.add_argument("--max-resets-per-day", type=float,
                        default=float(os.environ.get("MAX_RESETS_PER_DAY",
                                                     DEFAULT_MAX_RESETS_PER_DAY)))
    args = parser.parse_args(argv)

    try:
        entries = fetch_entries(PROJECT, SERVICE, args.days)
    except Exception as error:  # noqa: BLE001 — the reporting path itself
        raillog.alert(RUNNABLE, "SOURCE_FAILED",
                      f"could not read the request log: {error!r}")
        return 1

    sessions = websocket_sessions(entries)
    if not sessions:
        # Nobody used the helpdesk for a week, or the filter stopped matching.
        # Either way this job has nothing to say and saying nothing would be a
        # lie by omission, so it says that instead.
        raillog.alert(RUNNABLE, "SOURCE_EMPTY",
                      f"no websocket requests for {SERVICE} in "
                      f"{args.days}d — nobody used it, or the log filter broke")
        return 0

    summary = summarise(sessions, ttl_seconds=args.ttl_seconds)
    print(render(summary, args.days), flush=True)

    should_alert, message = verdict(
        summary,
        max_resets_per_day=args.max_resets_per_day,
        report_always=reporting_always(dt.date.today(),
                                       os.environ.get("REPORT_ALWAYS_UNTIL")),
        days=args.days,
    )
    if should_alert:
        raillog.alert(RUNNABLE, "SESSION_LOST", message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
