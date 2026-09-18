"""
lesko-ui / ui_theme.py  —  Layer 5: Python Bridge

Reads CSS files and injects them into Streamlit via st.markdown().
Block comments are stripped before injection to prevent HTML tags
inside comments from confusing Streamlit's markdown renderer.
"""

import os
import re
import streamlit as st

_HERE = os.path.dirname(os.path.abspath(__file__))

# Studiolo uses the system font stack (see tokens.css), so no webfont is
# self-hosted or fetched — the old fonts.css (base64 Inter) is gone.
_CORE_FILES = [
    "tokens.css",
    "base.css",
    "components.css",
    "streamlit.css",
]


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _strip_comments(css: str) -> str:
    """Remove /* ... */ block comments before injection.

    CSS comments frequently contain HTML examples (div, span, etc.).
    Streamlit's markdown renderer can misinterpret those HTML tags and
    break the <style> block, causing CSS to render as visible text.
    Stripping comments before injection eliminates this permanently.
    The CSS rules themselves are unchanged — only the explanatory text
    inside /* ... */ is removed.
    """
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def inject():
    """Inject all core lesko-ui CSS (tokens + base + components + streamlit).

    Call once in app.py after st.set_page_config():
        ui_theme.inject()
    """
    css_parts = []
    for filename in _CORE_FILES:
        filepath = os.path.join(_HERE, filename)
        if not os.path.exists(filepath):
            st.warning(f"[ui_theme] CSS file not found: {filepath}")
            continue
        css_parts.append(_strip_comments(_read(filepath)))

    st.markdown(
        f"<style>\n{''.join(css_parts)}\n</style>",
        unsafe_allow_html=True,
    )


def inject_dark_override():
    """Inject dark mode on top of the core lesko-ui CSS.

    Two shared files, so the palette stays identical to the React portal:
      • dark-tokens.css   — the canonical dark token variables (shared with React).
        It is scoped to :root[data-theme="dark"] for the portal; Streamlit has no
        such attribute, so we rewrite the selector to plain :root here — this file
        is injected ONLY when the manual dark toggle is on, so unconditional :root
        is correct.
      • streamlit-dark.css — Streamlit-only DOM overrides ([data-testid] chrome).

    Call after inject() when dark_mode is enabled:
        if st.session_state.dark_mode:
            ui_theme.inject_dark_override()
    """
    parts = []

    tokens_path = os.path.join(_HERE, "dark-tokens.css")
    if os.path.exists(tokens_path):
        css = _strip_comments(_read(tokens_path))
        css = css.replace(':root[data-theme="dark"]', ":root")
        parts.append(css)
    else:
        st.warning("[ui_theme] dark-tokens.css not found — dark palette unavailable")

    streamlit_dark_path = os.path.join(_HERE, "streamlit-dark.css")
    if os.path.exists(streamlit_dark_path):
        parts.append(_strip_comments(_read(streamlit_dark_path)))

    if parts:
        st.markdown(f"<style>\n{''.join(parts)}\n</style>", unsafe_allow_html=True)


def inject_file(path: str):
    """Inject a single CSS file (zone-specific styles in grant-helpdesk/static/).

    Example:
        ui_theme.inject_file(os.path.join(_STATIC, "tickets.css"))
    """
    if not os.path.exists(path):
        st.warning(f"[ui_theme] CSS file not found: {path}")
        return

    css = _strip_comments(_read(path))
    st.markdown(f"<style>\n{css}\n</style>", unsafe_allow_html=True)
