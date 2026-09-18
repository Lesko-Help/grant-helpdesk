"""
Palette guard for the Studiolo look and feel.

Studiolo's first rule: four colours, and no others — everything else is neutral
grey. This test walks every stylesheet, the app module, the Streamlit theme
file and the tab-icon SVG, pulls out each hex colour literal, and fails on any
value outside the allowed set. A fifth hue, or a leftover from the previous
indigo palette, breaks the build before it reaches a coach's screen.

Runs without BigQuery or Streamlit — it only reads files.

Run:  python3 -m pytest tests/test_theme.py -v
"""

import os
import re
import glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The four, each with its deepened twin (the second stop of a gradient).
STUDIOLO_HUES = {
    "#543ff8", "#3b2ac9",   # violet — primary action
    "#ed1748", "#bd0f36",   # red    — critical, destructive
    "#20a375", "#17805b",   # green  — done, answered
    "#e47d17", "#b86111",   # orange — urgent, in progress, late
}

# Neutral greys: light surfaces and text, plus the dark-mode set derived from ink.
STUDIOLO_NEUTRALS = {
    "#ffffff", "#fff",
    "#f6f7f9",              # canvas
    "#d5d8e0",              # hairline
    "#14161c",              # ink
    "#334155",              # ink-soft
    "#64748b",              # muted
    "#94a3b8",              # faint
    "#cbd5e1",              # ghost
    "#f8fafc", "#f1f5f9",   # grey-50, grey-100
    "#1c1f27", "#262a34", "#333846",   # dark surfaces
    "#000000", "#000",
}

ALLOWED = STUDIOLO_HUES | STUDIOLO_NEUTRALS

SCANNED = (
    glob.glob(os.path.join(ROOT, "lesko-ui", "*.css"))
    + glob.glob(os.path.join(ROOT, "lesko-ui", "assets", "*.svg"))
    + glob.glob(os.path.join(ROOT, "static", "*.css"))
    + [
        os.path.join(ROOT, "app.py"),
        os.path.join(ROOT, ".streamlit", "config.toml"),
    ]
)

HEX = re.compile(r"#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")


def _colours_in(path: str):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    # An 8-digit value is a colour with alpha — compare its first six digits.
    for m in HEX.finditer(text):
        raw = m.group(1).lower()
        yield ("#" + (raw[:6] if len(raw) == 8 else raw)), m.start(), text


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def test_scanned_files_exist():
    missing = [p for p in SCANNED if not os.path.exists(p)]
    assert not missing, f"Scanned files missing: {missing}"


def test_only_studiolo_colours_are_used():
    """Every hex colour in the UI layer is one of the four hues or a neutral."""
    offenders = []
    for path in SCANNED:
        for colour, pos, text in _colours_in(path):
            if colour not in ALLOWED:
                offenders.append(f"{os.path.relpath(path, ROOT)}:{_line_of(text, pos)} {colour}")
    assert not offenders, "Colours outside the Studiolo palette:\n  " + "\n  ".join(offenders)


def test_theme_file_matches_tokens():
    """.streamlit/config.toml paints Streamlit's chrome before the CSS loads —
    it must carry the same four values as tokens.css or the page flashes off-brand."""
    with open(os.path.join(ROOT, ".streamlit", "config.toml"), encoding="utf-8") as f:
        toml = f.read()
    expected = {
        "primaryColor": "#543ff8",
        "backgroundColor": "#f6f7f9",
        "secondaryBackgroundColor": "#ffffff",
        "textColor": "#14161c",
    }
    for key, value in expected.items():
        m = re.search(rf'^{key}\s*=\s*"([^"]+)"', toml, re.M)
        assert m, f"{key} missing from .streamlit/config.toml"
        assert m.group(1).lower() == value, f"{key} is {m.group(1)}, expected {value}"


def test_system_font_stack_only():
    """Studiolo uses the system font. No self-hosted or remote webfont may load."""
    theme_py = os.path.join(ROOT, "lesko-ui", "ui_theme.py")
    with open(theme_py, encoding="utf-8") as f:
        src = f.read()
    assert '"fonts.css"' not in src, "ui_theme.py still injects the old self-hosted Inter"
    for path in glob.glob(os.path.join(ROOT, "lesko-ui", "*.css")) + glob.glob(os.path.join(ROOT, "static", "*.css")):
        with open(path, encoding="utf-8") as f:
            css = f.read()
        assert "@font-face" not in css, f"{os.path.relpath(path, ROOT)} declares a webfont"
        assert "fonts.googleapis" not in css, f"{os.path.relpath(path, ROOT)} loads a remote font"


if __name__ == "__main__":  # plain-python runner when pytest is not installed
    import sys
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}\n{e}")
    sys.exit(1 if failures else 0)
