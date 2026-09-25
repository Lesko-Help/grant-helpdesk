"""
Offline proof for the root raillog.py — the app-path copy of jobs/raillog.py
(coach-inbox-alert brief, slice B1).

Streamlit's app.py imports raillog from the repo root, not from jobs/, so
this file exists as its own copy the same way jobs/raillog.py already does
for the Cloud Run jobs (see that file's own module docstring for why it is
vendored rather than shared). This test checks the root copy prints the
exact same structured line, not that the two files are byte-identical — the
two are allowed to drift in comments, just not in the line Cloud Monitoring
actually matches on.
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import raillog  # noqa: E402


def test_alert_prints_one_json_line_with_severity_error(capsys):
    raillog.alert("coach-inbox", "SOURCE_FAILED", "private_chat read failed: Forbidden")
    out = capsys.readouterr().out.strip()
    line = json.loads(out)
    assert line == {
        "severity": "ERROR",
        "message": "BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED: private_chat read failed: Forbidden",
    }


def test_alert_falls_back_to_unexpected_for_an_unknown_code(capsys):
    raillog.alert("coach-inbox", "NOT_A_REAL_CODE", "whatever")
    out = capsys.readouterr().out.strip()
    line = json.loads(out)
    assert line["message"] == "BTB_ALERT grant-helpdesk/coach-inbox UNEXPECTED: whatever"
