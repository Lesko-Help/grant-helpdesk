import os
import re
import sys
import types
import datetime
import concurrent.futures
import streamlit as st
import bq_client
import config
from mn_format import mn_mention, build_mn_body, _linkify, space_label, MEMBER_BIO_LABEL  # noqa: F401

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lesko-ui"))
import ui_theme

# ── Local dev mode ─────────────────────────────────────────────────────────────
# Set DEV_USER=your@email.com in your shell to bypass OAuth when running locally.
# Example:  export DEV_USER=martin.j.menke@gmail.com
# Leave unset (or empty) in production — Cloud Run never has this var.
_DEV_USER = os.environ.get("DEV_USER", "").strip()
if _DEV_USER:
    _mock = types.SimpleNamespace(
        is_logged_in=True,
        email=_DEV_USER,
        name=_DEV_USER.split("@")[0].replace(".", " ").title(),
    )
    if not hasattr(st, "_original_user"):
        st._original_user = getattr(st, "user", None)
    st.user = _mock

st.set_page_config(page_title=config.APP_NAME, layout="wide", page_icon="🎯")

# ── Brand palette (kept for login screen and urg dot colors) ──────────────────
# Colours live in lesko-ui/tokens.css — nothing in this file names a colour
# directly; HTML rendered here uses class names and var(--…) tokens only.

_STATIC = os.path.join(os.path.dirname(__file__), "static")
ui_theme.inject()
ui_theme.inject_file(os.path.join(_STATIC, "sidebar.css"))
ui_theme.inject_file(os.path.join(_STATIC, "header.css"))
ui_theme.inject_file(os.path.join(_STATIC, "kpi.css"))
ui_theme.inject_file(os.path.join(_STATIC, "tickets.css"))
ui_theme.inject_file(os.path.join(_STATIC, "inbox.css"))

# ── CSS is now loaded via ui_theme above ──────────────────────────────────────
# lesko-ui/tokens.css      → design tokens (colors, spacing, type, radius)
# lesko-ui/base.css        → global font + reset
# lesko-ui/components.css  → .card, .badge, .urg-pill, .avatar …
# lesko-ui/streamlit.css   → Streamlit widget overrides
# static/sidebar.css       → Zone 1: sidebar filter panel
# static/header.css        → Zone 2+3: header + tabs
# static/kpi.css           → Zone 4: KPI cards
# static/tickets.css       → Zone 5+6: ticket table + rows

# ── Domain icons ───────────────────────────────────────────────────────────────
DOMAIN_ICON = {
    "Pay Debt & Bills":        "💰",
    "Home & Housing Help":     "🏠",
    "Cars & Car Repairs":      "🚗",
    "Healthcare Assistance":   "🏥",
    "Start A Business":        "🚀",
    "Launch A Nonprofit":      "🤲",
    "Boost Your Career":       "💼",
    "Taxes Help Guidance":     "🧾",
    "Find Legal Help":         "⚖️",
    "Family & Children":       "👨‍👩‍👧",
    "Seniors & Disabilities":  "🛡️",
    "Programs for Veterans":   "🎖️",
    "Community Support":       "🤝",
    "Other":                   "📌",
}

STATUS_ICON = {
    "open":            "🔵",
    "answered":        "✅",
    "closed":          "🟢",
    "cancelled":       "🔴",
    "flagged":         "🚩",
    "archived":        "⚪",
}
URGENCY_ICON = {
    "normal":   "🟢",
    "urgent":   "🟡",
    "critical": "🔴",
}

# ── Helpers ────────────────────────────────────────────────────────────────────
def _initials(name: str) -> str:
    if not isinstance(name, str):
        # BQ NULLs come back as float NaN through pandas — NaN is truthy and
        # has no .split(), so coerce anything non-string to "" first.
        name = ""
    parts = (name or "?").split()
    return "".join(p[0].upper() for p in parts[:2]) if parts else "?"

def _avatar_class(name: str) -> str:
    # Rotate the four accents so neighbouring rows differ. Colour is
    # decoration here, never meaning.
    colors = ["mem-avatar-violet", "mem-avatar-red", "mem-avatar-green", "mem-avatar-orange"]
    return colors[hash(name or "") % len(colors)]

@st.cache_data
def _paste_links_js() -> str:
    """Read the smart-paste interceptor script (static/paste_links.js)."""
    with open(os.path.join(os.path.dirname(__file__), "static", "paste_links.js")) as f:
        return f.read()


def inject_paste_links() -> None:
    """Install the smart-paste interceptor once per page.

    A plain <textarea> drops embedded hyperlinks on paste. The injected script
    rewrites pasted <a href> as [label](url) markdown in the answer box, which
    _linkify() then turns into clickable links when posting to Mighty Networks.
    """
    import streamlit.components.v1 as _components
    _components.html(f"<script>{_paste_links_js()}</script>", height=0)


_KPI_VARIANTS = {"open", "normal", "urgent", "critical"}

def kpi_card(label: str, value, variant: str = "") -> str:
    """One KPI tile. `variant` picks the status wash (.kpi-open …) defined in
    static/kpi.css; light and dark colours both come from the tokens, so this
    function never names a colour."""
    formatted = f"{value:,}" if isinstance(value, int) else str(value)
    variant_class = f" kpi-{variant}" if variant in _KPI_VARIANTS else ""
    return f"""
    <div class="kpi-card{variant_class}">
      <div class="kpi-label">{label}</div>
      <div class="kpi-value">{formatted}</div>
    </div>"""


# ── Auth ───────────────────────────────────────────────────────────────────────
if not st.user.is_logged_in:
    st.markdown("""
    <div class="login-page">
      <div class="login-card">
        <div class="login-logo">L</div>
        <h2 class="login-title">Lesko Help Desk</h2>
        <p class="login-sub">Grant support queue — team access only</p>
      </div>
    </div>
    """, unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.button(
            "Sign in with Google",
            on_click=st.login,
            args=("google",),
            use_container_width=True,
            type="primary",
        )
        st.button(
            "Sign in with email",
            on_click=st.login,
            args=("auth0",),
            use_container_width=True,
        )
        st.markdown(
            "<p class='login-hint'>New here?</p>",
            unsafe_allow_html=True,
        )
        st.button(
            "Create an account",
            on_click=st.login,
            args=("auth0signup",),
            use_container_width=True,
        )
    st.stop()

user         = st.user
current_user = user.email or user.name or ""

# During the Auth0 OAuth redirect callback Streamlit runs the script but
# st.session_state is None (not yet initialised). Stop here and let Streamlit
# complete the handshake — it will immediately re-run with a proper session.
if st.session_state is None:
    st.stop()

# ── Coach onboarding — fires on first login if email not yet linked ────────────
_ADMIN_EMAILS = {"martin.j.menke@gmail.com"}

def _is_known_coach(email: str) -> bool:
    if email in _ADMIN_EMAILS:
        return True
    return bq_client.get_coach_by_login_email(email) is not None

if current_user and current_user not in _ADMIN_EMAILS:
    if "_coach_verified" not in st.session_state:
        try:
            st.session_state._coach_verified = _is_known_coach(current_user)
        except Exception as _e:
            st.session_state._coach_verified = False
            bq_client.log_event("ERROR", "app.coach_verification", f"Could not verify coach login for {current_user}", str(_e))

    if not st.session_state._coach_verified:
        st.markdown(f"""
        <div class="onboarding-card">
          <div class="onboarding-wave">👋</div>
          <div class="onboarding-title">
            Welcome to Lesko Help Desk
          </div>
          <div class="onboarding-body">
            It looks like this is your first time logging in with
            <strong>{current_user}</strong>.<br>
            Select your grant coach profile below to link your account.
          </div>
        </div>
        """, unsafe_allow_html=True)

        with st.container():
            col = st.columns([1, 2, 1])[1]
            with col:
                unlinked = bq_client.get_unlinked_coaches()
                if unlinked.empty:
                    st.warning("No unlinked coach profiles found. Ask your admin to add you first.")
                    if st.button("Sign out"):
                        st.logout()
                else:
                    _opts = ["— select your profile —"] + [
                        f"{r['full_name']}  ({r['email']})"
                        for _, r in unlinked.iterrows()
                    ]
                    _sel = st.selectbox("Your grant coach profile", _opts, key="_onboard_sel")

                    if st.button("This is me →", type="primary", use_container_width=True,
                                 disabled=_sel == "— select your profile —"):
                        _idx = _opts.index(_sel) - 1
                        _row = unlinked.iloc[_idx]
                        bq_client.link_coach_login_email(int(_row["member_id"]), current_user)
                        st.session_state._coach_verified = True
                        st.cache_data.clear()
                        st.rerun()

                    st.caption("Not a grant coach? Contact martin.j.menke@gmail.com")
        st.stop()

# ── Session state defaults ─────────────────────────────────────────────────────
if "member_id_filter" not in st.session_state:
    st.session_state.member_id_filter = ""
if "_status_overrides" not in st.session_state:
    # {content_id: new_status} — local patches applied after a quick-status change
    # so we don't have to nuke the full cache and re-query BQ on every dropdown click
    st.session_state._status_overrides = {}
if "_open_group" not in st.session_state:
    st.session_state._open_group = None  # (thread_id, member_id, member_name)
if "_ticket_pages" not in st.session_state:
    # One page cursor per lane — the Tickets and Conversations tabs render at the
    # same time, so a single shared cursor would make paging one page the other.
    st.session_state._ticket_pages = {config.LANE_QUESTION: 0, config.LANE_GENERAL: 0}
if "_lane_overrides" not in st.session_state:
    # {content_id: new_lane} — same trick as _status_overrides: after a lane move
    # we patch locally so the row leaves the tab immediately, instead of dropping
    # the cache and re-querying BigQuery on every click.
    st.session_state._lane_overrides = {}
if "show_filters" not in st.session_state:
    st.session_state.show_filters = True
if "show_kpis" not in st.session_state:
    st.session_state.show_kpis = True
if "_pending_action" not in st.session_state:
    st.session_state._pending_action = None  # {"action", "content_id", "row"}
if "_bc_preview" not in st.session_state:
    st.session_state._bc_preview = None
if "dark_mode" not in st.session_state:
    st.session_state.dark_mode = False

# ── Smart paste — keep hyperlinks from pasted rich text in answer fields ────────
inject_paste_links()

# ── Dark mode override (manual toggle — OS preference handled via @media in CSS)
if st.session_state.dark_mode:
    ui_theme.inject_dark_override()
    # Streamlit uses Emotion CSS-in-JS for selected pill state — no stable
    # attribute to target with CSS. Inject JS to watch and restyle selected pills.
    import streamlit.components.v1 as _components
    _components.html("""
    <script>
    (function() {
        function applyPillStyles() {
            var sidebar = window.parent.document.querySelector('[data-testid="stSidebar"]');
            if (!sidebar) return;
            var groups = sidebar.querySelectorAll('[data-testid="stButtonGroup"], [data-testid="stButtonGroupContainer"]');
            groups.forEach(function(group) {
                var buttons = group.querySelectorAll('button');
                buttons.forEach(function(btn) {
                    var bg = window.parent.getComputedStyle(btn).backgroundColor;
                    // Unselected pills carry the dark surface set in
                    // lesko-ui/streamlit-dark.css (#1c1f27 = rgb(28, 31, 39)).
                    // Anything else is the selected pill: paint it light on ink.
                    var isSurface = (bg === 'rgb(28, 31, 39)');
                    if (!isSurface) {
                        btn.style.setProperty('background-color', '#f1f5f9', 'important');
                        btn.style.setProperty('border-color', '#f1f5f9', 'important');
                        btn.style.setProperty('color', '#14161c', 'important');
                    }
                });
            });
        }
        applyPillStyles();
        var obs = new MutationObserver(applyPillStyles);
        obs.observe(window.parent.document.body, {childList: true, subtree: true, attributes: true});
    })();
    </script>
    """, height=0)

# ── Sidebar visibility ────────────────────────────────────────────────────────
if not st.session_state.show_filters:
    st.markdown("""
    <style>
    [data-testid="stSidebar"]                { display: none !important; }
    [data-testid="stSidebarCollapsedControl"] { display: none !important; }
    </style>
    """, unsafe_allow_html=True)

# ── Data loaders ───────────────────────────────────────────────────────────────
# Defined BEFORE the sidebar so the Refresh button (inside the sidebar) can call
# load_tickets.clear() etc. Streamlit reruns the module top-to-bottom on every
# interaction, so anything the sidebar references must already exist by then.
@st.cache_data(ttl=300)
def load_tickets(status, date_from, date_to, assignee, member_id, urgency, domain,
                 lane=config.LANE_QUESTION):
    # lane is part of the cache key, so the two tabs cache independently and
    # clearing one clears both (load_tickets.clear() drops every entry).
    return bq_client.get_tickets(
        status=status,
        date_from=str(date_from) if date_from else None,
        date_to=str(date_to) if date_to else None,
        assignee=assignee,
        member_id=member_id or None,
        urgency=urgency,
        domain=domain,
        lane=lane,
    )

@st.cache_data(ttl=300)
def load_open_stats():
    return bq_client.get_open_stats()

@st.cache_data(ttl=300)
def load_daily_stats():
    return bq_client.get_daily_stats()

@st.cache_data(ttl=300)
def load_report(report_type: str, date_from: str, date_to: str):
    return bq_client.get_report_data(report_type, date_from, date_to)

@st.cache_data(ttl=86400)
def load_space_names():
    # space_id → space_name lookup. Synced monthly by jobs/sync_spaces.py, so a
    # 24h cache is plenty. Used to label which space a ticket was commented in.
    return bq_client.get_space_names()


# ── Sidebar (user account + filters) ──────────────────────────────────────────
with st.sidebar:
    # User account
    avatar_url = getattr(user, "picture", None)
    name       = getattr(user, "name",    None) or current_user
    email      = getattr(user, "email",   None) or ""

    st.markdown(f"""
    <div style="display:flex; align-items:center; gap:10px; padding:4px 0 12px;">
      <div class="mem-avatar {_avatar_class(name)}">{_initials(name)}</div>
      <div>
        <div class="sidebar-user-name">{name}</div>
        <div class="sidebar-user-email">{email}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    if st.button("Sign out", use_container_width=True):
        st.logout()

    st.divider()

    # ── Filters ───────────────────────────────────────────────────────────────
    st.markdown('<p class="sidebar-section-label">Filters</p>', unsafe_allow_html=True)

    today = datetime.date.today()

    # 1. Grant Coach
    @st.cache_data(ttl=300)
    def load_team_members():
        return bq_client.get_team_members()

    team_members = load_team_members()
    filter_assignee = st.selectbox(
        "Grant Coach",
        ["All"] + team_members,
    )

    # 2. Status
    _status_opts = ["All"] + config.TICKET_STATUSES
    filter_status = st.selectbox(
        "Status",
        _status_opts,
        index=_status_opts.index("open"),
        format_func=lambda s: s if s == "All" else s.replace("_", " ").title(),
    )

    # 3. Domain
    filter_domain = st.selectbox(
        "Domain",
        ["All"] + config.DOMAINS,
    )

    # 4. Date range
    date_range_option = st.pills(
        "Date Range",
        ["All", "Today", "This Week", "This Month", "Custom"],
        default="All",
    )
    if date_range_option == "All" or date_range_option is None:
        date_from, date_to = None, None
    elif date_range_option == "Today":
        date_from, date_to = today, today
    elif date_range_option == "This Week":
        date_from = today - datetime.timedelta(days=today.weekday())
        date_to   = today
    elif date_range_option == "This Month":
        date_from = today.replace(day=1)
        date_to   = today
    else:
        custom_range = st.date_input(
            "Select Range",
            value=(today - datetime.timedelta(days=7), today),
        )
        if isinstance(custom_range, (list, tuple)) and len(custom_range) == 2:
            date_from, date_to = custom_range
        else:
            date_from = date_to = custom_range

    # 5. Urgency
    filter_urgency = st.pills(
        "Urgency",
        options=["All", "Normal", "Urgent", "Critical"],
        default="All",
    )

    # 6. Member ID
    filter_member_id = st.text_input(
        "Member ID",
        value=st.session_state.member_id_filter,
    )

    st.divider()
    if st.button("↺  Refresh data", use_container_width=True, type="primary"):
        load_tickets.clear()
        load_open_stats.clear()
        load_daily_stats.clear()
        st.session_state._status_overrides = {}
        st.session_state._lane_overrides   = {}
        st.session_state._ticket_pages     = {config.LANE_QUESTION: 0, config.LANE_GENERAL: 0}
        st.rerun()
    _dm_label = "☀️  Light mode" if st.session_state.dark_mode else "🌙  Dark mode"
    if st.button(_dm_label, use_container_width=True):
        st.session_state.dark_mode = not st.session_state.dark_mode
        st.rerun()
    if st.button("◀  Hide filters", use_container_width=True):
        st.session_state.show_filters = False
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TICKET DETAIL DIALOG
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=120, show_spinner=False)
def _cached_ticket_detail(content_id: str) -> dict:
    return bq_client.get_ticket_detail(content_id)

@st.cache_data(ttl=120, show_spinner=False)
def _cached_thread(thread_id: str):
    return bq_client.get_thread(thread_id)

# These three are read on every dialog rerun (e.g. when a coach picks a
# colleague to tag). Caching keeps a rerun from re-hitting BigQuery 3× and
# flashing the loading spinner. _cached_mn_api_key is invalidated when a key
# is saved in Settings.
@st.cache_data(ttl=300, show_spinner=False)
def _cached_mn_api_key(email: str):
    return bq_client.get_mn_api_key(email)

@st.cache_data(ttl=300, show_spinner=False)
def _cached_upcoming_events():
    return bq_client.get_upcoming_events()

@st.cache_data(ttl=120, show_spinner=False)
def _cached_member_history(member_id, exclude_content_id=None):
    return bq_client.get_member_history(member_id, exclude_content_id=exclude_content_id)

# Standard replies (answer templates) — managed in the 📋 Replies tab,
# offered as an "Insert standard reply" dropdown in both answer dialogs.
# Invalidated whenever a reply is saved or archived.
@st.cache_data(ttl=300, show_spinner=False)
def _cached_standard_replies():
    return bq_client.get_standard_replies()

_STD_REPLY_PLACEHOLDER = "— insert a standard reply —"

def _insert_std_reply(sel_key: str, target_key: str):
    """Selectbox on_change: append the picked reply body to the answer box.

    Runs as a widget callback, i.e. BEFORE the next script run, so assigning
    to the text_area's session_state key here is the supported way to change
    its content. Appends (never replaces) so nothing a coach typed is lost,
    then resets the selectbox so the same reply can be picked again later.
    """
    sel = st.session_state.get(sel_key)
    if not sel or sel == _STD_REPLY_PLACEHOLDER:
        return
    df = _cached_standard_replies()
    match = df[df["title"] == sel]
    if match.empty:
        return
    body = str(match.iloc[0]["body"])
    cur = (st.session_state.get(target_key) or "").rstrip()
    st.session_state[target_key] = f"{cur}\n\n{body}" if cur else body
    st.session_state[sel_key] = _STD_REPLY_PLACEHOLDER

def _std_reply_picker(sel_key: str, target_key: str):
    """Render the dropdown (only when replies exist) above an answer box."""
    try:
        _titles = _cached_standard_replies()["title"].tolist()
    except Exception as _e:
        bq_client.log_event("ERROR", "std_replies.load", "Could not load standard replies", str(_e))
        _titles = []
    if _titles:
        st.selectbox(
            "Insert standard reply",
            [_STD_REPLY_PLACEHOLDER] + _titles,
            key=sel_key,
            on_change=_insert_std_reply,
            args=(sel_key, target_key),
            label_visibility="collapsed",
            help="Appends the template below what you've already typed — edit freely before posting",
        )


def _answer_already_posted(content_id: str, body: str) -> bool:
    """True if this exact answer (same ticket + same rendered body) was already
    posted to Mighty Networks earlier in this session.

    Coaches reported every answer landing on MN twice. The post sits behind an
    edge-triggered button inside an @st.dialog that stays open after a successful
    post, and the call is slow (thread load + up-to-30s POST). A second fire of
    the same click — an impatient re-click, or a Streamlit websocket reconnect
    replaying the last interaction — would post the comment again. This guard
    makes posting idempotent per session. A genuinely different answer body has a
    different signature and is still allowed through."""
    return (content_id, body) in st.session_state.setdefault("_posted_answer_sigs", set())


def _mark_answer_posted(content_id: str, body: str) -> None:
    """Record a successful post so an identical re-fire is skipped. Called only
    AFTER post_mn_comment returns, so a failed post can still be retried."""
    st.session_state.setdefault("_posted_answer_sigs", set()).add((content_id, body))


@st.dialog("Ticket Detail", width="large")
def show_ticket_dialog(content_id: str, thread_id_hint: str = None):
    # ── Data fetch ─────────────────────────────────────────────────────────────
    # All BQ calls happen here before any rendering, so coaches see a spinner
    # instead of a blank dialog while data loads. The thread fetch runs in a
    # background thread (separate cache key — safe for st.cache_data); the ticket
    # detail stays on the main thread as st.cache_data is not thread-safe there.
    with st.spinner("Loading ticket…"):
        try:
            ticket = _cached_ticket_detail(content_id)
        except Exception as _e:
            st.error(f"Could not load ticket — please try again. ({_e})")
            return

        if not ticket:
            st.warning("Ticket not found.")
            return

        thread_id = ticket.get("thread_id") or content_id
        _hint     = thread_id_hint or thread_id
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _executor:
            _fut_thread = _executor.submit(_cached_thread, _hint)
            try:
                thread = _fut_thread.result(timeout=15)
            except Exception as _e:
                thread = pd.DataFrame()   # graceful fallback — show ticket without thread
                bq_client.log_event("WARNING", "app.show_ticket_dialog", f"Thread load failed for {thread_id}", str(_e))

    # ── Render ─────────────────────────────────────────────────────────────────
    status_icon  = STATUS_ICON.get(ticket.get("ticket_status"), "⚪")
    urgency_icon = URGENCY_ICON.get(ticket.get("urgency"), "⚪")
    content_type = ticket.get("content_type") or "—"
    domain_icon  = DOMAIN_ICON.get(ticket.get("domain") or "", "")

    # Header card
    _urg        = (ticket.get("urgency") or "normal").lower()
    _status     = (ticket.get("ticket_status") or "open").lower()
    _domain_str = f"{domain_icon} {ticket.get('domain')}" if domain_icon else ""
    _space_txt  = space_label(ticket.get("space_id"), load_space_names())
    _space_icon = "👤" if _space_txt == MEMBER_BIO_LABEL else "📍"
    _permalink  = ticket.get("member_permalink") or ""
    _state      = ticket.get("member_state") or "—"
    _city       = ticket.get("member_city") or "—"
    _mid        = ticket.get("member_id") or "—"
    _posted     = str(ticket.get("created_at", "—"))[:16]

    st.markdown(f"""
<div class="ticket-dialog-header">
  <div class="ticket-dialog-badge-row">
    <span class="ticket-dialog-name">{ticket.get('member_name','Unknown')}</span>
    <span class="badge badge-{_status}">{_status.replace('_',' ').capitalize()}</span>
    <span class="urg-pill urg-{_urg}">{_urg.capitalize()}</span>
    <span class="ticket-meta-item">{content_type}</span>
    <span class="ticket-meta-item">{_space_icon} {_space_txt}</span>
    {f'<span class="ticket-meta-item">{_domain_str}</span>' if _domain_str else ""}
    {f'<a href="{_permalink}" target="_blank" class="ticket-meta-link">↗ MN Profile</a>' if _permalink else ""}
  </div>
  <div class="ticket-meta-row">
    <span class="ticket-meta-item"><span class="ticket-meta-key">State</span>&nbsp; {_state}</span>
    <span class="ticket-meta-item"><span class="ticket-meta-key">City</span>&nbsp; {_city}</span>
    <span class="ticket-meta-item"><span class="ticket-meta-key">Member ID</span>&nbsp; {_mid}</span>
    <span class="ticket-meta-item"><span class="ticket-meta-key">Posted</span>&nbsp; {_posted}</span>
  </div>
</div>
""", unsafe_allow_html=True)

    if not thread.empty:
        # ── Root post ─────────────────────────────────────────────────────────
        root = thread[thread["content_type"] == "post"]
        if not root.empty:
            r = root.iloc[0]
            is_ticket = r["content_id"] == content_id
            st.markdown("**Original Post**")
            st.markdown(f"""
<div class="post-card">
  <div class="post-card-author">
    {r['author_name']}
    {"&nbsp;<span class='this-ticket-badge'>this ticket</span>" if is_ticket else ""}
  </div>
  <div class="post-card-date">{str(r['created_at'])[:16]}</div>
  <div class="post-card-body">{r['body'] or '<em>empty</em>'}</div>
  {"<div style='margin-top:8px'><a href='" + r['permalink'] + "' target='_blank' class='ticket-meta-link'>↗ View on Mighty Networks</a></div>" if r.get('permalink') else ""}
</div>
""", unsafe_allow_html=True)

        # ── Comments ──────────────────────────────────────────────────────────
        comments = thread[thread["content_type"] == "comment"]
        if not comments.empty:
            st.markdown(f"**Comments ({len(comments)})**")
            for _, item in comments.iterrows():
                is_current = item["content_id"] == content_id
                is_team    = item["author_type"] == "team"
                depth      = int(item.get("depth") or 1)
                indent_px  = (depth - 1) * 20
                role = "assistant" if is_team else "user"
                with st.chat_message(role):
                    label = f"{'　' * (depth - 1)}**{item['author_name']}** · {str(item['created_at'])[:16]}"
                    if is_current:
                        label += " 📌 *this ticket*"
                    st.markdown(label)
                    st.markdown(item["body"] or "_(empty)_")
                    if item.get("permalink"):
                        st.markdown(f"[↗ View]({item['permalink']})")

    st.divider()

    # Answer entry — posts to Mighty Networks via API
    st.markdown("**Post an Answer to Mighty Networks**")
    _mn_key = _cached_mn_api_key(current_user) if current_user else None
    if not _mn_key:
        st.warning("No Mighty Networks API key set. Add yours in the ⚙️ Settings tab.")
    else:
        _post_id   = (ticket.get("thread_id") or content_id).replace("post_", "")
        _mem_id    = ticket.get("member_id")
        _mem_name  = ticket.get("member_name") or ""

        _tag_col, _colleague_col = st.columns([1, 2])
        _tag_member = _tag_col.toggle(
            f"Tag @{_mem_name.split()[0] if _mem_name else 'member'}",
            value=True,
            key=f"tag_{content_id}",
            help="Prepends a @mention so the member gets a notification",
        )
        _colleague_choice = _colleague_col.selectbox(
            "Tag a colleague",
            ["— no colleague —"] + [c["name"] for c in config.TAG_COLLEAGUES],
            key=f"tag_colleague_{content_id}",
            help="Also @mention a colleague so they get notified",
        )
        _extra_mentions = []
        if _colleague_choice and _colleague_choice != "— no colleague —":
            _c = next((c for c in config.TAG_COLLEAGUES if c["name"] == _colleague_choice), None)
            if _c:
                _extra_mentions.append((_c["member_id"], _c["name"]))

        _std_reply_picker(f"stdreply_{content_id}", f"answer_{content_id}")
        answer_body = st.text_area(
            "Answer", key=f"answer_{content_id}",
            label_visibility="collapsed", height=160,
        )

        # ── Follow-up scheduler ───────────────────────────────────────────────
        _first_name = (_mem_name or "").split()[0] if (_mem_name or "").split() else "there"
        _fu_default = (
            f"Hi {_first_name}, just checking in — did everything get resolved? "
            f"Feel free to reach out if there's anything else we can help with!"
        )
        with st.expander("📅 Schedule a follow-up question (optional)"):
            _fu_enabled = st.checkbox(
                "Send follow-up automatically",
                key=f"followup_cb_{content_id}",
                value=False,
            )
            _fu_left, _fu_right = st.columns([5, 1])
            _fu_msg = _fu_left.text_area(
                "Message",
                value=_fu_default,
                key=f"followup_msg_{content_id}",
                height=80,
            )
            _fu_days = _fu_right.number_input(
                "Days", min_value=1, max_value=60, value=7,
                key=f"followup_days_{content_id}",
                help="Days to wait before sending",
            )
        # ─────────────────────────────────────────────────────────────────────

        _btn_post, _btn_close = st.columns([2, 1])
        if _btn_post.button("Post Answer to MN", key=f"post_answer_{content_id}", type="primary", use_container_width=True):
            if answer_body.strip() and _answer_already_posted(
                content_id,
                build_mn_body(answer_body.strip(), _tag_member, _mem_id, _mem_name, extra_mentions=_extra_mentions),
            ):
                st.warning("That exact answer was already posted to Mighty Networks — skipped to avoid a duplicate.")
            elif answer_body.strip():
                try:
                    _body = build_mn_body(answer_body.strip(), _tag_member, _mem_id, _mem_name, extra_mentions=_extra_mentions)
                    _posted = bq_client.post_mn_comment(_post_id, _body, _mn_key)
                    _mark_answer_posted(content_id, _body)
                    _new_comment_id = (_posted or {}).get("id") or (_posted or {}).get("comment_id")
                    bq_client.update_ticket_meta(
                        content_id,
                        "answered",
                        ticket.get("assigned_to") or "",
                        ticket.get("domain") or "",
                    )
                    if _fu_enabled and _fu_msg.strip():
                        _fu_body = build_mn_body(_fu_msg.strip(), True, _mem_id, _mem_name)
                        bq_client.queue_followup(
                            ticket_id=content_id,
                            content_id=_post_id,
                            content_type=ticket.get("content_type", "post"),
                            member_id=str(_mem_id) if _mem_id else "",
                            member_name=_mem_name,
                            message=_fu_body,
                            days=int(_fu_days),
                            scheduled_by=current_user or "",
                        )
                    st.session_state._status_overrides[content_id] = "answered"
                    st.session_state.pop(f"answer_{content_id}", None)
                    st.session_state.pop(f"tag_colleague_{content_id}", None)
                    load_tickets.clear()
                    load_open_stats.clear()
                    load_daily_stats.clear()
                    _thread_link = ticket.get("permalink") or ""
                    if _new_comment_id and _post_id:
                        _thread_link = (
                            f"https://lesko-help-2.mn.co/posts/{_post_id}/comments/{_new_comment_id}"
                        )
                    _suffix = " Follow-up scheduled." if _fu_enabled else ""
                    if _thread_link:
                        st.success(
                            f"Answer posted to Mighty Networks.{_suffix} "
                            f"[↗ View on MN]({_thread_link})"
                        )
                    else:
                        st.success(f"Answer posted to Mighty Networks.{_suffix}")
                except Exception as e:
                    st.error(f"Failed to post: {e}")
            else:
                st.warning("Answer cannot be empty.")
        if _btn_close.button("✅ Answer & Close", key=f"answer_close_{content_id}", use_container_width=True):
            if not answer_body.strip():
                st.warning("Answer cannot be empty. To close without replying, use Close from the ticket list.")
            elif _answer_already_posted(
                content_id,
                build_mn_body(answer_body.strip(), _tag_member, _mem_id, _mem_name, extra_mentions=_extra_mentions),
            ):
                st.warning("That exact answer was already posted to Mighty Networks — skipped to avoid a duplicate.")
            else:
                try:
                    with st.spinner("Posting answer and closing ticket…"):
                        _body = build_mn_body(answer_body.strip(), _tag_member, _mem_id, _mem_name, extra_mentions=_extra_mentions)
                        _posted = bq_client.post_mn_comment(_post_id, _body, _mn_key)
                        _mark_answer_posted(content_id, _body)
                        _new_comment_id = (_posted or {}).get("id") or (_posted or {}).get("comment_id")
                        bq_client.update_ticket_meta(
                            content_id,
                            "closed",
                            ticket.get("assigned_to") or "",
                            ticket.get("domain") or "",
                            closed_by=current_user,
                        )
                    st.session_state._status_overrides[content_id] = "closed"
                    st.session_state.pop(f"answer_{content_id}", None)
                    st.session_state.pop(f"tag_colleague_{content_id}", None)
                    load_tickets.clear()
                    load_open_stats.clear()
                    load_daily_stats.clear()
                    _thread_link = ticket.get("permalink") or ""
                    if _new_comment_id and _post_id:
                        _thread_link = (
                            f"https://lesko-help-2.mn.co/posts/{_post_id}/comments/{_new_comment_id}"
                        )
                    if _thread_link:
                        st.success(
                            f"✅ Answer posted to Mighty Networks and ticket closed. "
                            f"[↗ View on MN]({_thread_link})"
                        )
                    else:
                        st.success("✅ Answer posted to Mighty Networks and ticket closed.")
                except Exception as e:
                    bq_client.log_event("ERROR", "app.answer_and_close",
                        f"failed content_id={content_id}", detail=str(e))
                    st.error(f"Failed to post: {e}")

    st.divider()

    # RSVP section
    st.markdown("**📅 RSVP to Event**")
    _events = _cached_upcoming_events()
    if not _events:
        st.caption("No upcoming events found. The sync job runs daily at 06:00.")
    else:
        _mem_id   = ticket.get("member_id")
        _mem_name = (ticket.get("member_name") or "member").split()[0]
        _rsvp_mn_key = _cached_mn_api_key(current_user) if current_user else None

        def _fmt_event(e):
            starts = str(e.get("starts_at", ""))[:16].replace("T", " ")
            return f"{starts} — {e['title']}"

        _sel = st.selectbox(
            "Select event",
            _events,
            format_func=_fmt_event,
            key=f"rsvp_event_{content_id}",
            label_visibility="collapsed",
        )
        if not _rsvp_mn_key:
            st.warning("Add your MN API key in ⚙️ Settings to RSVP members.")
        elif _sel:
            if st.button(
                f"RSVP {_mem_name} →",
                key=f"rsvp_btn_{content_id}",
                type="primary",
                use_container_width=True,
            ):
                try:
                    bq_client.rsvp_member_to_event(_sel["event_id"], _mem_id, _rsvp_mn_key)
                    bq_client.log_rsvp(content_id, _sel["event_id"], _mem_id, current_user)
                    st.success(f"✅ {ticket.get('member_name','Member')} RSVP'd to **{_sel['title']}**")
                except RuntimeError as e:
                    st.error(f"RSVP failed: {e}")

    st.divider()

    # Placeholder — "Predefined answers" used to live here as a "coming soon"
    # button; it now ships as the "Insert standard reply" dropdown above, so
    # only the AI-generated placeholder remains.
    st.button(
        "🤖 AI-generated answer", disabled=True,
        help="Coming soon", key=f"ai_{content_id}",
        use_container_width=True,
    )

    with st.expander("📋 Call Sheet Report"):
        st.caption("Prompt template wiring coming soon.")
        st.text_input("State",  value=ticket.get("member_state") or "", disabled=True)
        st.text_input("Domain", value=ticket.get("domain") or "",       disabled=True)
        st.button("Generate Report", disabled=True, help="Coming soon", key=f"callsheet_{content_id}")

    with st.expander(f"📋 Member history ({ticket.get('member_name', '')})"):
        history = _cached_member_history(
            ticket["member_id"], exclude_content_id=ticket["content_id"]
        )
        if history.empty:
            st.write("No other tickets from this member.")
        else:
            for _, h in history.iterrows():
                h_icon = STATUS_ICON.get(h["ticket_status"], "⚪")
                h_link = f'&nbsp;<a href="{h["permalink"]}" target="_blank" style="font-size:0.75rem;color:var(--color-link)">↗ MN</a>' if h.get("permalink") else ""
                st.markdown(
                    f'{h_icon} <span style="font-size:0.8rem;color:var(--color-text-muted)">`{str(h["created_at"])[:10]}`</span>'
                    f' — {h["body_preview"]}{h_link}',
                    unsafe_allow_html=True,
                )


# ══════════════════════════════════════════════════════════════════════════════
# GROUP DIALOG — multiple comments from same member in same thread
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=120, show_spinner=False)
def _cached_member_thread(thread_id: str, member_id: str):
    return bq_client.get_member_thread_tickets(thread_id, member_id)


@st.dialog("Member Thread", width="large")
def show_group_dialog(thread_id: str, member_id: str, member_name: str):
    group_tix = _cached_member_thread(thread_id, member_id)
    if group_tix.empty:
        st.warning("No tickets found.")
        return

    open_tix = group_tix[group_tix["ticket_status"].apply(config.is_open_status)]
    done_tix = group_tix[~group_tix["ticket_status"].apply(config.is_open_status)]

    # ── Header ────────────────────────────────────────────────────────────────
    # All tickets in a group share a thread → same space.
    _grp_space = space_label(group_tix.iloc[0].get("space_id"), load_space_names())
    _grp_space_icon = "👤" if _grp_space == MEMBER_BIO_LABEL else "📍"
    st.markdown(f"""
<div class="ticket-dialog-header">
  <span class="ticket-dialog-name">{member_name}</span>
  <span class="ticket-meta-item" style="margin-left:10px">{_grp_space_icon} {_grp_space}</span>
  <span class="ticket-meta-item" style="margin-left:10px">{len(open_tix)} open comment{"s" if len(open_tix) != 1 else ""} · {len(done_tix)} handled</span>
</div>
""", unsafe_allow_html=True)

    # ── Original post (context) ───────────────────────────────────────────────
    thread = _cached_thread(thread_id)

    # ── Full thread ───────────────────────────────────────────────────────────
    if not thread.empty:
        # Collect content_ids that belong to this member's open tickets
        _open_ids = set(open_tix["content_id"].tolist())

        with st.expander("📄 Full thread", expanded=True):
            with st.container(height=520):
                for _, item in thread.iterrows():
                    is_member_ticket = item["content_id"] in _open_ids
                    is_team = item["author_type"] == "team"
                    depth   = int(item.get("depth") or 0)
                    role    = "assistant" if is_team else "user"
                    with st.chat_message(role):
                        label = f"{'　' * depth}**{item['author_name']}** · {str(item['created_at'])[:16]}"
                        if is_member_ticket:
                            label += " 📌 *open ticket*"
                        st.markdown(label)
                        st.markdown(item["body"] or "_(empty)_")
                        if item.get("permalink"):
                            st.markdown(f"[↗ View]({item['permalink']})")

    st.divider()

    # ── Open comments ─────────────────────────────────────────────────────────
    if open_tix.empty:
        st.info("All comments in this thread are already handled.")
    else:
        # Lifecycle statuses only. "Not a question" is no longer a status — it is a
        # lane move, and it lives on the Action dropdown. 'archived' is derived from
        # the go-live cutoff, never something a coach picks.
        all_statuses = [s for s in config.TICKET_STATUSES if s != "archived"]
        _assignee_opts = ["— unassigned —"] + team_members
        _domain_opts   = ["— unset —"] + config.DOMAINS

        # Bulk controls
        st.markdown(f"**Apply to all {len(open_tix)} open comments**")
        bc1, bc2, bc3 = st.columns(3)
        bulk_status = bc1.selectbox(
            "Status", all_statuses,
            key=f"bulk_status_{thread_id}_{member_id}",
            format_func=lambda s: f"{STATUS_ICON.get(s,'')} {s.replace('_',' ').title()}",
        )
        bulk_coach = bc2.selectbox(
            "Grant Coach", _assignee_opts,
            key=f"bulk_coach_{thread_id}_{member_id}",
        )
        bulk_domain = bc3.selectbox(
            "Domain", _domain_opts,
            key=f"bulk_domain_{thread_id}_{member_id}",
        )
        if st.button("💾 Save to all open comments", type="primary", key=f"bulk_save_{thread_id}_{member_id}"):
            _av = "" if bulk_coach  == "— unassigned —" else bulk_coach
            _dv = "" if bulk_domain == "— unset —"      else bulk_domain
            for _, t in open_tix.iterrows():
                bq_client.update_ticket_meta(t["content_id"], bulk_status, _av, _dv)
            load_tickets.clear()
            load_open_stats.clear()
            load_daily_stats.clear()
            st.success(f"Saved {len(open_tix)} comments.")

        st.divider()

        # Individual open comments
        st.markdown(f"**Open comments ({len(open_tix)})**")
        for _, t in open_tix.iterrows():
            urg = (t.get("urgency") or "normal").lower()
            st.markdown(f"""
<div class="comment-card">
  <div class="comment-card-meta">
    <span class="badge badge-open">open</span>
    <span class="urg-pill urg-{urg}">{urg.capitalize()}</span>
    <span class="comment-date">{str(t['created_at'])[:16]}</span>
    {f'<a href="{t["permalink"]}" target="_blank" class="ticket-meta-link" style="margin-left:auto">↗</a>' if t.get("permalink") else ""}
  </div>
  <div class="comment-body">{t.get("body_preview") or "<em>(empty)</em>"}</div>
</div>""", unsafe_allow_html=True)

            with st.expander("Reply & settings for this comment"):
                # ── Post answer to MN ──────────────────────────────────────
                _mn_key = _cached_mn_api_key(current_user) if current_user else None
                if _mn_key:
                    _pid      = thread_id.replace("post_", "")
                    _g_mem_id = t.get("member_id") or group_tix.iloc[0].get("member_id")
                    _gtc, _gac = st.columns([1, 3])
                    _grp_tag = _gtc.toggle(
                        f"Tag @{member_name.split()[0]}",
                        value=True,
                        key=f"grp_tag_{t['content_id']}",
                        help="Prepends a @mention so the member gets a notification",
                    )
                    _std_reply_picker(f"grp_stdreply_{t['content_id']}", f"grp_ans_{t['content_id']}")
                    ans = st.text_area(
                        "Post Answer to Mighty Networks",
                        key=f"grp_ans_{t['content_id']}",
                        height=100,
                        placeholder="Type your answer here…",
                    )
                    if st.button("Post Answer to MN", key=f"grp_post_{t['content_id']}", type="primary"):
                        if ans.strip() and _answer_already_posted(
                            t["content_id"],
                            build_mn_body(ans.strip(), _grp_tag, _g_mem_id, member_name),
                        ):
                            st.warning("That exact answer was already posted to Mighty Networks — skipped to avoid a duplicate.")
                        elif ans.strip():
                            try:
                                _gbody = build_mn_body(ans.strip(), _grp_tag, _g_mem_id, member_name)
                                bq_client.post_mn_comment(_pid, _gbody, _mn_key)
                                _mark_answer_posted(t["content_id"], _gbody)
                                st.session_state.pop(f"grp_ans_{t['content_id']}", None)
                                st.success("Answer posted to Mighty Networks.")
                            except Exception as e:
                                st.error(f"Failed: {e}")
                        else:
                            st.warning("Answer cannot be empty.")
                else:
                    st.caption("No MN API key — add yours in ⚙️ Settings.")

                st.divider()

                # ── Status & coach override ────────────────────────────────
                ov1, ov2 = st.columns(2)
                _cur_status = t.get("ticket_status") or "open"
                _cur_status = _cur_status if _cur_status in all_statuses else "open"
                _cur_coach  = t.get("assigned_to") or "— unassigned —"
                if _cur_coach not in _assignee_opts:
                    _cur_coach = "— unassigned —"
                ov_status = ov1.selectbox(
                    "Status", all_statuses,
                    index=all_statuses.index(_cur_status),
                    key=f"ov_status_{t['content_id']}",
                    format_func=lambda s: f"{STATUS_ICON.get(s,'')} {s.replace('_',' ').title()}",
                )
                ov_coach = ov2.selectbox(
                    "Grant Coach", _assignee_opts,
                    index=_assignee_opts.index(_cur_coach),
                    key=f"ov_coach_{t['content_id']}",
                )
                if st.button("💾 Save this comment", key=f"ov_save_{t['content_id']}"):
                    _av2 = "" if ov_coach == "— unassigned —" else ov_coach
                    bq_client.update_ticket_meta(t["content_id"], ov_status, _av2, "")
                    load_tickets.clear()
                    load_open_stats.clear()
                    load_daily_stats.clear()
                    st.success("Saved.")

    # ── Done comments (grayed out) ────────────────────────────────────────────
    if not done_tix.empty:
        st.divider()
        st.markdown(f"**Already handled ({len(done_tix)})**")
        for _, t in done_tix.iterrows():
            _s = (t.get("ticket_status") or "").lower()
            st.markdown(f"""
<div class="done-comment-card">
  <div class="comment-card-meta">
    <span class="badge badge-{_s}">{_s.replace("_"," ").capitalize()}</span>
    <span class="comment-date">{str(t['created_at'])[:16]}</span>
  </div>
  <div class="done-comment-body">{t.get("body_preview") or "<em>(empty)</em>"}</div>
</div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# ACTION DIALOGS — opened from the ticket table Action dropdown
# ══════════════════════════════════════════════════════════════════════════════

@st.dialog("Flag Ticket", width="small")
def show_flag_dialog(content_id: str, row_dict: dict):
    mem = row_dict.get("member_name") or "Unknown"
    st.markdown(f"Flag ticket from **{mem}** for follow-up review.")
    flag_reason = st.text_area(
        "Report / Reason",
        placeholder="Describe what's wrong or why this needs attention…",
        height=120,
        key=f"flag_reason_{content_id}",
    )
    c1, c2 = st.columns(2)
    if c1.button("Flag ticket", type="primary", use_container_width=True, key=f"flag_confirm_{content_id}"):
        if flag_reason.strip():
            bq_client.update_ticket_meta(
                content_id, "flagged",
                row_dict.get("assigned_to", ""),
                row_dict.get("domain", ""),
                feedback_reason=flag_reason.strip(),
            )
            st.session_state._status_overrides[content_id] = "flagged"
            st.rerun()
        else:
            st.warning("Please add a reason before flagging.")
    if c2.button("Cancel", use_container_width=True, key=f"flag_cancel_{content_id}"):
        st.rerun()


@st.dialog("Delete Post from Mighty Networks", width="small")
def show_delete_dialog(content_id: str, row_dict: dict):
    mem  = row_dict.get("member_name") or "Unknown"
    prev = row_dict.get("body_preview") or ""
    st.error(
        "⚠️ **This will permanently delete this post from Mighty Networks.**\n\n"
        "This action cannot be undone.",
        icon="🗑️",
    )
    st.markdown(f"**Member:** {mem}")
    if prev:
        st.caption(prev[:200] + ("…" if len(prev) > 200 else ""))
    _mn_key = _cached_mn_api_key(current_user) if current_user else None
    if not _mn_key:
        st.warning("No Mighty Networks API key set. Add yours in the ⚙️ Settings tab.")
        if st.button("Close", use_container_width=True, key=f"del_close_{content_id}"):
            st.rerun()
        return
    c1, c2 = st.columns(2)
    if c1.button("🗑️ Delete from MN", type="primary", use_container_width=True, key=f"del_confirm_{content_id}"):
        try:
            bq_client.delete_mn_post(content_id, _mn_key)
            bq_client.update_ticket_meta(
                content_id,
                "cancelled",
                row_dict.get("assigned_to", ""),
                row_dict.get("domain", ""),
            )
            st.session_state._status_overrides[content_id] = "cancelled"
            st.rerun()
        except RuntimeError as e:
            st.error(f"MN API error: {e}")
    if c2.button("Cancel", use_container_width=True, key=f"del_cancel_{content_id}"):
        st.rerun()


@st.dialog("Assign Ticket", width="small")
def show_assign_dialog(content_id: str, row_dict: dict):
    mem = row_dict.get("member_name") or "Unknown"
    st.markdown(f"Assign ticket from **{mem}** to a grant coach.")
    _opts = ["— unassigned —"] + team_members
    _cur  = row_dict.get("assigned_to") or "— unassigned —"
    if _cur not in _opts:
        _cur = "— unassigned —"
    new_coach = st.selectbox("Grant Coach", _opts, index=_opts.index(_cur), key=f"assign_sel_{content_id}")
    if st.button("Save", type="primary", use_container_width=True, key=f"assign_save_{content_id}"):
        _av = "" if new_coach == "— unassigned —" else new_coach
        # Assignment is metadata — write only assigned_to, never touch status.
        bq_client.set_ticket_assignee(content_id, _av)
        load_tickets.clear()
        load_open_stats.clear()
        load_daily_stats.clear()
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE HEADER
# ══════════════════════════════════════════════════════════════════════════════
st.markdown(f"""
<div class="lesko-header-card">
  <div class="header-logo">L</div>
  <div style="flex:1;">
    <span class="header-app-name">Lesko Help Desk</span>
    <span class="header-sub">Grant support workspace</span>
  </div>
  <div class="header-user-pill">
    <div class="header-user-avatar">{_initials(name)}</div>
    <span class="header-user-name">{name.split()[0] if name else ''}</span>
  </div>
</div>
""", unsafe_allow_html=True)

if not st.session_state.show_filters:
    if st.button("▶  Filters", key="show_filters_btn"):
        st.session_state.show_filters = True
        st.rerun()

tab_main, tab_convos, tab_reports, tab_train, tab_replies, tab_settings, tab_admin, tab_inbox = st.tabs(
    ["🎫 Tickets", "💬 Conversations", "📊 Reports", "🔍 Review AI", "📋 Replies", "⚙️ Settings", "👥 Admin", "📬 Inbox"]
)

# The last entry differs per lane: from Tickets you push a row OUT to
# Conversations, from Conversations you pull it BACK. Both are lane moves and
# both feed the classifier.
_ACTION_OPTS = {
    config.LANE_QUESTION: ["— action —", "Answer", "Close", "Flag", "Not a question", "Assign", "Delete"],
    config.LANE_GENERAL:  ["— action —", "Answer", "Close", "Flag", "This is a question", "Assign", "Delete"],
}
# action label → lane it moves the row to
_LANE_MOVES = {
    "Not a question":     config.LANE_GENERAL,
    "This is a question": config.LANE_QUESTION,
}

@st.fragment
def render_ticket_table(tickets, team_members, filter_status="All", lane=config.LANE_QUESTION):
    """Isolated fragment — re-runs only when a widget inside it changes,
    so a status dropdown click does NOT re-run the sidebar, KPIs, or BQ queries.

    `lane` is threaded through every widget key. Tickets and Conversations both
    render on the same Streamlit run, so a bare key like "page_next" would be
    registered twice and Streamlit raises a duplicate-key error."""
    _opts = _ACTION_OPTS[lane]

    if tickets.empty:
        st.info("No tickets match the current filters.")
        return

    _URG_RANK = {"critical": 2, "urgent": 1, "normal": 0}
    _URG_NAME = {2: "critical", 1: "urgent", 0: "normal"}

    # space_id → name, fetched once for the whole list (cached 24h).
    _space_names = load_space_names()

    def _gk(r):
        tid = r.get("thread_id") or ""
        return f"{r['member_id']}|{tid}" if tid else str(r["content_id"])

    tickets = tickets.copy()
    tickets["_gk"] = tickets.apply(_gk, axis=1)

    seen_gk: dict = {}
    for idx, row in tickets.iterrows():
        gk = row["_gk"]
        seen_gk.setdefault(gk, []).append(idx)

    # ── Pagination ────────────────────────────────────────────────────────────
    _PAGE_SIZE  = 25
    _all_keys   = list(seen_gk.keys())
    _total_rows = len(_all_keys)
    _total_pages = max(1, -(-_total_rows // _PAGE_SIZE))  # ceiling division

    # Clamp page to valid range (filters changing can reduce total pages)
    _page = min(st.session_state._ticket_pages.get(lane, 0), _total_pages - 1)
    if _page != st.session_state._ticket_pages.get(lane, 0):
        st.session_state._ticket_pages[lane] = _page

    _page_keys  = _all_keys[_page * _PAGE_SIZE : (_page + 1) * _PAGE_SIZE]
    _page_gk    = {k: seen_gk[k] for k in _page_keys}

    # ── Action short-circuit ──────────────────────────────────────────────────
    # on_change fired on a previous render — process BEFORE drawing any rows
    # so we skip a full 25-row render pass.
    _triggered = st.session_state.pop(f"_act_triggered_{lane}", None)
    if _triggered:
        _t_cid   = _triggered["content_id"]
        _t_act   = _triggered["action"]
        _t_rdict = _triggered.get("row_dict", {})
        _is_grp  = _triggered.get("is_group", False)

        if _is_grp:
            _open_ids = _triggered.get("open_content_ids", [])
            _g_tid    = _triggered.get("thread_id", "")
            _g_mid    = _triggered.get("member_id", "")
            _g_mname  = _triggered.get("member_name", "")
            if _t_act == "Answer":
                st.session_state._open_group = (_g_tid, _g_mid, _g_mname)
                st.rerun(scope="app")  # must reach top-level dialog trigger
            elif _t_act == "Close":
                for _oid in _open_ids:
                    bq_client.update_ticket_meta(_oid, "closed", _t_rdict.get("assigned_to",""), _t_rdict.get("domain",""), closed_by=current_user)
                    st.session_state._status_overrides[_oid] = "closed"
                st.rerun()
            elif _t_act in _LANE_MOVES:
                _to_lane = _LANE_MOVES[_t_act]
                for _oid in _open_ids:
                    bq_client.set_ticket_lane(_oid, _to_lane, feedback_reason="flagged_via_quick_status")
                    st.session_state._lane_overrides[_oid] = _to_lane
                st.rerun()
            else:
                # Flag / Assign — use representative ticket
                st.session_state._pending_action = {"action": _t_act, "content_id": _t_cid, "row": _t_rdict}
                st.rerun(scope="app")  # must reach top-level dialog trigger
        else:
            if _t_act == "Close":
                bq_client.update_ticket_meta(_t_cid, "closed", _t_rdict.get("assigned_to",""), _t_rdict.get("domain",""), closed_by=current_user)
                st.session_state._status_overrides[_t_cid] = "closed"
                st.rerun()
            elif _t_act in _LANE_MOVES:
                _to_lane = _LANE_MOVES[_t_act]
                bq_client.set_ticket_lane(_t_cid, _to_lane, feedback_reason="flagged_via_quick_status")
                st.session_state._lane_overrides[_t_cid] = _to_lane
                st.rerun()
            else:
                st.session_state._pending_action = {"action": _t_act, "content_id": _t_cid, "row": _t_rdict}
                st.rerun(scope="app")  # must reach top-level dialog trigger

    h0, h1, h3, h6 = st.columns([1.3, 5.6, 1.3, 0.6])
    for col, label in zip(
        [h0, h1, h3, h6],
        ["Member", "Question", "Action", "Coach"],
    ):
        col.markdown(f'<span class="tbl-header">{label}</span>', unsafe_allow_html=True)

    _shown = 0
    for gk, indices in _page_gk.items():
        grp = tickets.loc[indices]
        row = grp.iloc[0]

        # Optimistic filter: if status or lane was changed locally and no longer
        # matches this tab, hide the row immediately — no BQ re-query needed.
        # Lane first: a row moved to the other tab is gone from this one whatever
        # its status says.
        _moved_to = st.session_state._lane_overrides.get(row["content_id"])
        if _moved_to and _moved_to != lane:
            continue

        # "Open" spans every live (non-terminal) status, so only hide an open-view
        # row when the new status becomes terminal.
        if filter_status != "All" and len(grp) == 1:
            overridden = st.session_state._status_overrides.get(row["content_id"])
            if overridden:
                if filter_status == "open":
                    if not config.is_open_status(overridden):
                        continue
                elif overridden != filter_status:
                    continue

        if _shown > 0:
            st.markdown('<div class="ticket-divider"></div>', unsafe_allow_html=True)

        _shown += 1
        c0, c1, c3, c6 = st.columns([1.3, 5.6, 1.3, 0.6])

        mem_name = row["member_name"] or "Unknown"
        _row_domain_icon = DOMAIN_ICON.get(row.get("domain") or "", "")
        _row_urg = (row.get("urgency") or "normal").lower()
        _row_status = (row.get("ticket_status") or "open").lower()
        _is_answered = _row_status == "answered"
        _urg_labels = {"normal": "🟢", "urgent": "🟡", "critical": "🔴"}
        _meta_parts = []
        _row_space = space_label(row.get("space_id"), _space_names)
        _meta_parts.append(("👤 " if _row_space == MEMBER_BIO_LABEL else "📍 ") + _row_space)
        if _row_domain_icon:
            _meta_parts.append(_row_domain_icon)
        _fu = _followup_map.get(str(row["content_id"]))
        if _fu:
            if _fu.get("status") == "pending":
                try:
                    import pandas as _pd
                    _fu_ts = _pd.Timestamp(_fu["send_after"])
                    if _fu_ts.tzinfo is None:
                        _fu_ts = _fu_ts.tz_localize("UTC")
                    _days_left = max(0, (_fu_ts - _pd.Timestamp.now(tz="UTC")).days)
                except Exception:
                    _days_left = "?"
                _meta_parts.append(f"⏳ follow-up in {_days_left}d")
            elif _fu.get("status") == "sent":
                _meta_parts.append("✅ follow-up sent")
        if _is_answered:
            _status_html = '<span class="answered-badge">✓ Answered</span>'
        else:
            _status_html = _urg_labels.get(_row_urg, "🟢") + " " + _row_urg
        _marker = '<div class="answered-row-marker"></div>' if _is_answered else ""
        c0.markdown(
            f'{_marker}'
            f'<div class="member-name">{mem_name}</div>'
            f'<div style="font-size:0.7rem;color:var(--color-text-muted);margin-top:2px">'
            f'{"  ·  ".join(_meta_parts) + ("  ·  " if _meta_parts else "") + _status_html}'
            f'</div>',
            unsafe_allow_html=True,
        )
        c0.caption(str(row["created_at"])[:10])

        if len(grp) == 1:
            domain_icon  = _row_domain_icon
            full_text    = str(row["body_preview"] or "")
            safe_text    = full_text.replace("<", "&lt;").replace(">", "&gt;")
            _body_class  = "answered-body" if _is_answered else ""
            c1.markdown(f'<span class="{_body_class}" style="font-size:var(--font-base);color:var(--color-text)">{safe_text}</span>', unsafe_allow_html=True)


            _act_key = f"act_{lane}_{row['content_id']}"
            _cid     = row["content_id"]
            _rdict   = row.to_dict()

            def _on_action_change(cid=_cid, rdict=_rdict, akey=_act_key, ln=lane):
                action = st.session_state.get(akey)
                if action and action != "— action —":
                    st.session_state[f"_act_triggered_{ln}"] = {"action": action, "content_id": cid, "row_dict": rdict}
                    # Reset here — the one place Streamlit lets you write a widget's own
                    # key. Without it the value sticks and on_change re-fires every rerun.
                    st.session_state[akey] = "— action —"

            c3.selectbox(
                "Action",
                _opts,
                index=0,
                key=_act_key,
                on_change=_on_action_change,
                label_visibility="collapsed",
            )

            _ca = row.get("assigned_to")
            _ca = _ca.strip() if isinstance(_ca, str) else ""  # NULL → NaN float in pandas
            c6.markdown(
                f'<div style="text-align:center;font-size:0.85rem;font-weight:600;color:var(--color-text-soft);padding-top:6px">'
                f'{"·" if not _ca else _initials(_ca)}</div>',
                unsafe_allow_html=True,
            )

        else:
            n_open  = int(grp["ticket_status"].apply(config.is_open_status).sum())
            worst   = _URG_NAME[int(grp["urgency"].map(lambda u: _URG_RANK.get(u, 0)).max())]

            _grp_tid   = row.get("thread_id") or ""
            _grp_mid   = str(row.get("member_id") or "")
            _grp_mname = mem_name
            _open_ids_in_grp = grp[grp["ticket_status"].apply(config.is_open_status)]["content_id"].tolist()
            _grp_rdict = row.to_dict()
            _grp_cid   = row["content_id"]

            c1.markdown(
                f'<small style="color:var(--color-primary);font-weight:500">'
                f'<strong>{len(grp)} comments</strong> in thread'
                f'{"  ·  " + str(n_open) + " open" if n_open else "  ·  all handled"}</small>',
                unsafe_allow_html=True,
            )

            _grp_act_key = f"act_g_{lane}_{_grp_mid}_{_grp_tid.replace('-','_')}"

            def _on_grp_action(tid=_grp_tid, mid=_grp_mid, mname=_grp_mname,
                                open_ids=_open_ids_in_grp, rdict=_grp_rdict, cid=_grp_cid,
                                akey=_grp_act_key, ln=lane):
                action = st.session_state.get(akey)
                if action and action != "— action —":
                    st.session_state[f"_act_triggered_{ln}"] = {
                        "action":           action,
                        "content_id":       cid,
                        "row_dict":         rdict,
                        "is_group":         True,
                        "thread_id":        tid,
                        "member_id":        mid,
                        "member_name":      mname,
                        "open_content_ids": open_ids,
                    }
                    # Reset here so the value can't stick and re-fire on later reruns.
                    st.session_state[akey] = "— action —"

            c3.selectbox(
                "Action", _opts, index=0,
                key=_grp_act_key, on_change=_on_grp_action,
                label_visibility="collapsed",
            )

            _ca = row.get("assigned_to")
            _ca = _ca.strip() if isinstance(_ca, str) else ""  # NULL → NaN float in pandas
            c6.markdown(
                f'<div style="text-align:center;font-size:0.85rem;font-weight:600;color:var(--color-text-soft);padding-top:6px">'
                f'{"·" if not _ca else _initials(_ca)}</div>',
                unsafe_allow_html=True,
            )

    if _shown == 0:
        st.info("No tickets match the current filters.")

    # ── Page navigation ───────────────────────────────────────────────────────
    if _total_pages > 1:
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        _nc1, _nc2, _nc3 = st.columns([1, 2, 1])
        if _nc1.button("← Prev", disabled=_page == 0, use_container_width=True, key=f"page_prev_{lane}"):
            st.session_state._ticket_pages[lane] -= 1
            st.rerun()
        _nc2.markdown(
            f'<div style="text-align:center;font-size:0.82rem;color:var(--color-text-muted);padding-top:8px">'
            f'Page {_page + 1} of {_total_pages} &nbsp;·&nbsp; {_total_rows} tickets</div>',
            unsafe_allow_html=True,
        )
        if _nc3.button("Next →", disabled=_page >= _total_pages - 1, use_container_width=True, key=f"page_next_{lane}"):
            st.session_state._ticket_pages[lane] += 1
            st.rerun()





# ── MAIN TAB ──────────────────────────────────────────────────────────────────
with tab_main:
    tickets     = load_tickets(
        filter_status, date_from, date_to,
        filter_assignee, filter_member_id,
        filter_urgency, filter_domain,
    )
    open_stats  = load_open_stats()
    daily_stats = load_daily_stats()
    _followup_map = bq_client.get_followup_statuses(tickets["content_id"].tolist()) if not tickets.empty else {}

    # ── KPI toggle ────────────────────────────────────────────────────────────
    _kpi_label = "▲ Hide stats" if st.session_state.show_kpis else "▼ Show stats"
    if st.button(_kpi_label, key="toggle_kpis"):
        st.session_state.show_kpis = not st.session_state.show_kpis
        st.rerun()

    # ── KPI Row A ─────────────────────────────────────────────────────────────
    if st.session_state.show_kpis:
        a1, a2, a3, a4 = st.columns(4)
        a1.markdown(kpi_card("Open",     int(open_stats.get("open",     0)), "open"),     unsafe_allow_html=True)
        a2.markdown(kpi_card("Normal",   int(open_stats.get("normal",   0)), "normal"),   unsafe_allow_html=True)
        a3.markdown(kpi_card("Urgent",   int(open_stats.get("urgent",   0)), "urgent"),   unsafe_allow_html=True)
        a4.markdown(kpi_card("Critical", int(open_stats.get("critical", 0)), "critical"), unsafe_allow_html=True)

        st.markdown("<div style='height:var(--space-3)'></div>", unsafe_allow_html=True)

        answered_today = int(daily_stats.get("answered_today", 0))
        in_today       = int(daily_stats.get("in_today", 0))
        total_open     = int(open_stats.get("open", 0))
        b1, b2, b3 = st.columns(3)
        b1.markdown(kpi_card("New questions today",                        in_today),                        unsafe_allow_html=True)
        b2.markdown(kpi_card(f"Answered today (from {total_open:,} open)", answered_today),                  unsafe_allow_html=True)
        b3.markdown(kpi_card("Daily avg (30d)",                            daily_stats.get("daily_avg", 0)), unsafe_allow_html=True)

    # ── Bulk Close ────────────────────────────────────────────────────────────
    with st.expander("🗂️ Bulk Close Tickets"):
        st.caption("Close multiple tickets at once. Tickets with a pending follow-up question are always skipped.")
        _bc_c1, _bc_c2, _bc_c3 = st.columns(3)
        _bc_status = _bc_c1.selectbox(
            "Status", ["answered", "open", "flagged", "— any open status —"],
            key="bc_status",
        )
        _bc_coach = _bc_c2.selectbox(
            "Grant coach", ["— all coaches —"] + team_members,
            key="bc_coach",
        )
        _bc_before = _bc_c3.date_input(
            "Created before", value=None, key="bc_before",
            help="Leave blank to include all dates",
        )

        _bc_status_val  = "" if _bc_status  == "— any open status —" else _bc_status
        _bc_coach_val   = "" if _bc_coach   == "— all coaches —"     else _bc_coach
        _bc_before_val  = str(_bc_before) if _bc_before else ""

        _bc_prev_col, _bc_go_col = st.columns([2, 1])
        if _bc_prev_col.button("Preview", key="bc_preview"):
            with st.spinner("Counting…"):
                _bc_result = bq_client.preview_bulk_close(
                    status_filter=_bc_status_val,
                    assigned_to=_bc_coach_val,
                    before_date=_bc_before_val,
                )
            st.session_state._bc_preview = _bc_result

        if st.session_state.get("_bc_preview"):
            _p = st.session_state._bc_preview
            _skip_note = f" — {_p['skipped_followup']} skipped (follow-up pending)" if _p["skipped_followup"] else ""
            st.info(f"**{_p['will_close']} ticket(s) will be closed**{_skip_note}")
            if _p["will_close"] > 0:
                if _bc_go_col.button(f"✅ Close {_p['will_close']} tickets", key="bc_execute", type="primary"):
                    with st.spinner("Closing tickets…"):
                        _bc_closed = bq_client.execute_bulk_close(
                            status_filter=_bc_status_val,
                            assigned_to=_bc_coach_val,
                            before_date=_bc_before_val,
                            closed_by=current_user or "",
                        )
                    st.session_state._bc_preview = None
                    load_tickets.clear()
                    load_open_stats.clear()
                    load_daily_stats.clear()
                    st.success(f"Closed {_bc_closed} tickets.")
                    st.rerun()

    # ── Ticket list ───────────────────────────────────────────────────────────
    # Count unique member+thread groups — this is what the user actually sees,
    # not raw ticket rows (multiple comments from one member in one thread = 1 row).
    _unique_groups = tickets.apply(
        lambda r: f"{r['member_id']}|{r['thread_id']}" if r.get("thread_id") else str(r["content_id"]),
        axis=1,
    ).nunique() if not tickets.empty else 0
    _PAGE_SIZE = 25
    _n_pages = max(1, -(-_unique_groups // _PAGE_SIZE))
    _page_info = f" — page {st.session_state._ticket_pages[config.LANE_QUESTION] + 1}/{_n_pages}" if _n_pages > 1 else ""
    st.markdown(f'<div class="section-card-title" style="padding:6px 0 10px">Tickets ({_unique_groups}){_page_info}</div>', unsafe_allow_html=True)

    # render_ticket_table is an @st.fragment — a status dropdown change inside it
    # only re-runs THIS fragment, not the sidebar, KPIs, or BQ queries above.
    render_ticket_table(tickets, team_members, filter_status, lane=config.LANE_QUESTION)

    # Dialogs can't be opened from inside @st.fragment, so the fragment sets
    # session state and st.rerun() brings us here to open the dialog.

    if st.session_state._open_group:
        _tid, _mid, _mname = st.session_state._open_group
        st.session_state._open_group = None
        show_group_dialog(thread_id=_tid, member_id=_mid, member_name=_mname)

    if st.session_state._pending_action:
        _pa = st.session_state._pending_action
        st.session_state._pending_action = None
        if _pa["action"] == "Answer":
            show_ticket_dialog(_pa["content_id"], thread_id_hint=_pa["row"].get("thread_id"))
        elif _pa["action"] == "Flag":
            show_flag_dialog(_pa["content_id"], _pa["row"])
        elif _pa["action"] == "Assign":
            show_assign_dialog(_pa["content_id"], _pa["row"])
        elif _pa["action"] == "Delete":
            show_delete_dialog(_pa["content_id"], _pa["row"])

    st.markdown("</div>", unsafe_allow_html=True)


# ── CONVERSATIONS TAB ─────────────────────────────────────────────────────────
# The general lane: member posts and comments the classifier did not read as a
# grant question. Same table, same actions, no KPI cards — these are not tickets
# against a response target, they are community activity worth a reply.
#
# Anything created before the two-lane go-live lands on 'archived' rather than
# here; set the sidebar Status filter to Archived to see that history.
#
# Note the dialogs are NOT re-dispatched at the bottom of this tab. The block in
# the Tickets tab runs on every rerun whichever tab is showing, and a Streamlit
# dialog is an overlay, so one dispatch serves both lanes. Adding a second would
# just consume the same session state twice.
with tab_convos:
    convos = load_tickets(
        filter_status, date_from, date_to,
        filter_assignee, filter_member_id,
        filter_urgency, filter_domain,
        lane=config.LANE_GENERAL,
    )

    st.caption(
        "Posts and comments that are not grant questions. Reply, close, or send one "
        "back to Tickets with **This is a question** — that also teaches the classifier."
    )

    _convo_groups = convos.apply(
        lambda r: f"{r['member_id']}|{r['thread_id']}" if r.get("thread_id") else str(r["content_id"]),
        axis=1,
    ).nunique() if not convos.empty else 0
    _c_pages = max(1, -(-_convo_groups // 25))
    _c_page_info = f" — page {st.session_state._ticket_pages[config.LANE_GENERAL] + 1}/{_c_pages}" if _c_pages > 1 else ""
    st.markdown(
        f'<div class="section-card-title" style="padding:6px 0 10px">Conversations ({_convo_groups}){_c_page_info}</div>',
        unsafe_allow_html=True,
    )

    render_ticket_table(convos, team_members, filter_status, lane=config.LANE_GENERAL)


# ── REPORTS TAB ───────────────────────────────────────────────────────────────
with tab_reports:
    st.subheader("Reports")

    r1, r2 = st.columns(2)
    with r1:
        r_date_from = st.date_input(
            "From", value=today - datetime.timedelta(days=30), key="r_from"
        )
    with r2:
        r_date_to = st.date_input("To", value=today, key="r_to")

    st.divider()

    st.markdown("#### Volume — Tickets In vs Answered")
    vol = load_report("volume", str(r_date_from), str(r_date_to))
    if not vol.empty:
        st.bar_chart(vol.set_index("date")[["tickets_in", "tickets_closed"]])
    else:
        st.caption("No data for this period.")

    st.divider()

    st.markdown("#### Response Time")
    rt = load_report("response_time", str(r_date_from), str(r_date_to))
    if not rt.empty:
        avg_min = round(rt["minutes_to_response"].mean(), 1)
        med_min = round(rt["minutes_to_response"].median(), 1)
        sla_pct = round((rt["minutes_to_response"] < 1440).mean() * 100, 1)
        rr1, rr2, rr3 = st.columns(3)
        rr1.metric("Avg time to first response", f"{avg_min} min")
        rr2.metric("Median",                     f"{med_min} min")
        rr3.metric("% answered within 24 h",     f"{sla_pct}%")
    else:
        st.caption("No data for this period.")

    st.divider()

    st.markdown("#### Team Productivity — Tickets Closed")
    tp = load_report("team_productivity", str(r_date_from), str(r_date_to))
    if not tp.empty:
        st.bar_chart(tp.set_index("assigned_to")["tickets_closed"])
    else:
        st.caption("No data for this period.")

    st.divider()

    st.markdown("#### Domain Breakdown")
    db = load_report("domain_breakdown", str(r_date_from), str(r_date_to))
    if not db.empty:
        st.bar_chart(db.set_index("domain")["tickets"])
    else:
        st.caption("No data for this period.")

    st.divider()
    st.button("📥 Export to Excel", disabled=True, help="Coming soon")


# ── REVIEW AI CLASSIFICATIONS TAB ─────────────────────────────────────────────
with tab_train:
    st.subheader("Review AI Classifications")
    st.caption(
        "Everything below was classified as **not a question** by the AI. "
        "Scan the list and click **This is a question** if the AI got it wrong. "
        "Your corrections are sent to the training system to improve accuracy over time."
    )

    # ── Filters ───────────────────────────────────────────────────────────────
    _PERIOD_OPTS = {
        "Last 24 hours": 1,
        "Last 48 hours": 2,
        "Last week":     7,
        "Last month":    30,
        "Last year":     365,
    }
    _rf1, _rf2, _rf3 = st.columns([2, 2, 1])
    _period_label = _rf1.selectbox(
        "Period", list(_PERIOD_OPTS.keys()),
        index=0, key="review_period",
        label_visibility="collapsed",
    )
    _name_filter = _rf2.text_input(
        "Member name", placeholder="Filter by member name…",
        key="review_name", label_visibility="collapsed",
    )
    if _rf3.button("↺ Refresh", key="review_refresh", use_container_width=True):
        st.cache_data.clear()
        st.session_state._reviewed_ids = set()
        st.rerun()

    _days = _PERIOD_OPTS[_period_label]

    # Track which items were actioned this session (optimistic hide before reload)
    if "_reviewed_ids" not in st.session_state:
        st.session_state._reviewed_ids = set()

    @st.cache_data(ttl=300, show_spinner=False)
    def load_review_queue(days: int):
        return bq_client.get_unreviewed_rejects(days=days)

    with st.spinner("Loading…"):
        review_df = load_review_queue(_days)

    # Deduplicate (safety net against duplicate content_ids in grant_tickets)
    if not review_df.empty:
        review_df = review_df.drop_duplicates(subset=["content_id"])

    # Apply session-state filter (items actioned this session disappear instantly)
    if not review_df.empty and st.session_state._reviewed_ids:
        review_df = review_df[~review_df["content_id"].isin(st.session_state._reviewed_ids)]

    # Apply member name filter
    if _name_filter.strip() and not review_df.empty:
        review_df = review_df[
            review_df["member_name"].fillna("").str.contains(_name_filter.strip(), case=False, na=False)
        ]

    st.caption(f"{len(review_df)} item{'s' if len(review_df) != 1 else ''} to review")
    st.divider()

    if review_df.empty:
        st.success("All clear — nothing flagged for review in this period.")
    else:
        _TYPE_ICON = {"post": "📝", "article": "📄", "comment": "💬"}

        for _, item in review_df.iterrows():
            cid      = item["content_id"]
            ctype    = item.get("content_type") or "post"
            ticon    = _TYPE_ICON.get(ctype, "📝")
            name     = item.get("member_name") or "Unknown"
            posted   = str(item.get("created_at", ""))[:10]
            body     = item.get("body") or ""
            preview  = body[:220] + ("…" if len(body) > 220 else "")
            link     = item.get("permalink") or ""

            with st.container():
                _c1, _c2 = st.columns([5, 1])
                with _c1:
                    st.markdown(
                        f"{ticon} **{name}** &nbsp;·&nbsp; "
                        f"<span style='color:var(--color-text-muted);font-size:0.85rem'>{ctype} · {posted}</span>"
                        + (f"&nbsp;&nbsp;<a href='{link}' target='_blank' style='font-size:0.8rem;color:var(--color-link)'>↗ MN</a>" if link else ""),
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f"<div style='color:var(--color-text-soft);font-size:0.9rem;margin-top:2px'>{preview}</div>",
                        unsafe_allow_html=True,
                    )
                with _c2:
                    if st.button(
                        "This is a question",
                        key=f"isq_{cid}",
                        use_container_width=True,
                        type="primary",
                    ):
                        # A lane move, not a status change — the item keeps
                        # whatever lifecycle it had and reappears under Tickets.
                        bq_client.set_ticket_lane(
                            cid, config.LANE_QUESTION,
                            feedback_reason="coach_review",
                        )
                        st.session_state._reviewed_ids.add(cid)
                        st.rerun()
            st.divider()


# ── REPLIES TAB — shared standard replies (answer templates) ─────────────────
with tab_replies:
    st.subheader("📋 Standard Replies")
    st.caption(
        "Reusable answer templates shared by the whole team. When answering a "
        "ticket, pick one from the **Insert standard reply** dropdown above the "
        "answer box — it appends below whatever you've typed, so you can still "
        "personalize before posting. Blank lines become paragraph breaks in "
        "Mighty Networks; `[link text](https://url)` becomes a clickable link."
    )

    try:
        _sr_df = _cached_standard_replies()
    except Exception as _e:
        bq_client.log_event("ERROR", "std_replies.tab", "Could not load standard replies", str(_e))
        st.error(f"Could not load standard replies: {_e}")
        _sr_df = None

    if _sr_df is not None:
        # ── Add new ───────────────────────────────────────────────────────────
        with st.expander("➕ Add a standard reply", expanded=_sr_df.empty):
            _new_title = st.text_input(
                "Title", key="sr_new_title",
                placeholder="e.g. Grants.gov registration checklist",
                help="What coaches see in the dropdown — keep it short and findable",
            )
            _new_body = st.text_area(
                "Reply text", key="sr_new_body", height=180,
                placeholder="The answer text that gets inserted…",
            )
            if st.button("Save reply", key="sr_new_save", type="primary"):
                if not _new_title.strip() or not _new_body.strip():
                    st.warning("Both a title and the reply text are needed.")
                elif _new_title.strip().lower() in (_sr_df["title"].str.strip().str.lower().tolist()):
                    st.warning("A reply with this title already exists — edit it below instead.")
                else:
                    try:
                        bq_client.save_standard_reply(None, _new_title.strip(), _new_body.strip(), current_user)
                        _cached_standard_replies.clear()
                        st.session_state.pop("sr_new_title", None)
                        st.session_state.pop("sr_new_body", None)
                        st.success("Saved.")
                        st.rerun()
                    except Exception as _e:
                        bq_client.log_event("ERROR", "std_replies.add", "Could not save standard reply", str(_e))
                        st.error(f"Could not save: {_e}")

        # ── Existing replies ──────────────────────────────────────────────────
        if _sr_df.empty:
            st.info("No standard replies yet — add the first one above.")
        else:
            st.markdown(f"**{len(_sr_df)} repl{'y' if len(_sr_df) == 1 else 'ies'}**")
            for _, _sr in _sr_df.iterrows():
                _rid = _sr["reply_id"]
                with st.expander(f"📄 {_sr['title']}"):
                    _ed_title = st.text_input("Title", value=_sr["title"], key=f"sr_title_{_rid}")
                    _ed_body = st.text_area("Reply text", value=_sr["body"], key=f"sr_body_{_rid}", height=180)
                    _meta = f"Added by {_sr['created_by']}"
                    if _sr.get("updated_by") and isinstance(_sr.get("updated_by"), str):
                        _meta += f" · last edited by {_sr['updated_by']}"
                    st.caption(_meta)
                    _c_save, _c_arch, _ = st.columns([1, 1, 2])
                    if _c_save.button("Save changes", key=f"sr_save_{_rid}", type="primary", use_container_width=True):
                        if not _ed_title.strip() or not _ed_body.strip():
                            st.warning("Both a title and the reply text are needed.")
                        else:
                            try:
                                bq_client.save_standard_reply(_rid, _ed_title.strip(), _ed_body.strip(), current_user)
                                _cached_standard_replies.clear()
                                st.success("Saved.")
                                st.rerun()
                            except Exception as _e:
                                bq_client.log_event("ERROR", "std_replies.edit", f"Could not update reply {_rid}", str(_e))
                                st.error(f"Could not save: {_e}")
                    if _c_arch.button("Archive", key=f"sr_arch_{_rid}", use_container_width=True,
                                      help="Removes it from the dropdown — the text is kept and an admin can restore it"):
                        try:
                            bq_client.archive_standard_reply(_rid)
                            _cached_standard_replies.clear()
                            st.rerun()
                        except Exception as _e:
                            bq_client.log_event("ERROR", "std_replies.archive", f"Could not archive reply {_rid}", str(_e))
                            st.error(f"Could not archive: {_e}")


# ── SETTINGS TAB ──────────────────────────────────────────────────────────────
with tab_settings:
    st.subheader("Your Mighty Networks API Key")
    st.caption(
        "Required to post answers directly to Mighty Networks from the ticket dialog. "
        "Each team member needs their own key. Generate one in your MN admin panel under "
        "**Admin → Settings → API Keys**."
    )

    @st.dialog("Add Mighty Networks API Key")
    def api_key_dialog():
        st.caption("Your key is stored securely in BigQuery and never shown again.")
        new_key = st.text_input("Paste your API key", type="password", placeholder="mn_live_...")
        c1, c2 = st.columns(2)
        if c1.button("Save", type="primary", use_container_width=True):
            if new_key.strip():
                bq_client.save_mn_api_key(current_user, new_key.strip())
                _cached_mn_api_key.clear()
                st.success("Saved.")
                st.rerun()
            else:
                st.warning("Please enter a key.")
        if c2.button("Cancel", use_container_width=True):
            st.rerun()

    _has_key = _cached_mn_api_key(current_user) is not None if current_user else False
    if _has_key:
        st.success("✓ API key configured")
        if st.button("Replace key"):
            api_key_dialog()
    else:
        st.warning("No API key set")
        if st.button("Add API Key", type="primary"):
            api_key_dialog()

    st.divider()
    st.subheader("Classifier Prompt Settings")
    st.caption(
        "The AI classifier reads every community post and decides whether it "
        "needs a staff response. The prompt below drives that decision. It is "
        "updated automatically every week by the Dataform pipeline when enough "
        "team feedback has been collected."
    )

    @st.cache_data(ttl=300)
    def load_prompt_history():
        return bq_client.get_prompt_history()

    prompt_history = load_prompt_history()

    if prompt_history.empty:
        st.info("No prompt versions found in grant_prompt_config.")
    else:
        current = prompt_history[prompt_history["is_current"] == True]
        past    = prompt_history[prompt_history["is_current"] == False]

        st.markdown("### Current Prompt")
        if not current.empty:
            row = current.iloc[0]
            active_since = str(row["created_at"])[:10]

            total  = int(row["total_classified"])
            as_q   = int(row["classified_as_question"])
            q_rate = round(as_q / total * 100, 1) if total > 0 else 0
            fp     = int(row["false_positives"])
            cq     = int(row["confirmed_questions"])

            s1, s2, s3, s4, s5 = st.columns(5)
            s1.metric("Version",              f"v{int(row['version'])}")
            s2.metric("Active Since",         active_since)
            s3.metric("Posts Classified",     total)
            s4.metric("Question Rate",        f"{q_rate}%")
            s5.metric("Feedback This Period", f"{fp} FP · {cq} CQ",
                      help="FP = false positives flagged by team · CQ = confirmed questions")

            if row["change_reason"] and str(row["change_reason"]).strip():
                st.info(f"**Last change:** {row['change_reason']}")

            with st.expander("View full prompt text"):
                st.markdown(f'<pre class="prompt-block">{row["prompt_text"]}</pre>', unsafe_allow_html=True)

        st.divider()

        st.markdown("### Prompt History")
        if past.empty:
            st.caption("No previous versions — this is the first prompt.")
        else:
            for _, row in past.iterrows():
                version_label = f"v{int(row['version'])}"
                active_from   = str(row["created_at"])[:10]
                active_to     = str(row["superseded_at"])[:10] if row["superseded_at"] else "—"
                total         = int(row["total_classified"])
                as_q          = int(row["classified_as_question"])
                q_rate        = round(as_q / total * 100, 1) if total > 0 else 0
                fp            = int(row["false_positives"])
                cq            = int(row["confirmed_questions"])

                with st.expander(
                    f"{version_label} · Active {active_from} → {active_to} · "
                    f"{total} classified · {q_rate}% questions · {fp} FP / {cq} CQ"
                ):
                    if row["change_reason"] and str(row["change_reason"]).strip():
                        st.markdown(f"**Why it was replaced:** {row['change_reason']}")
                        st.divider()
                    st.markdown(f'<pre class="prompt-block">{row["prompt_text"]}</pre>', unsafe_allow_html=True)


# ── ADMIN TAB ─────────────────────────────────────────────────────────────────
with tab_admin:
    _admin_api_key = _cached_mn_api_key(current_user) if current_user else None

    st.subheader("Grant Coaches")
    st.caption("Coaches listed here appear as assignees in the ticket list. Promoting a member to coach also gives them host role in Mighty Networks so they can generate their own API key.")

    @st.cache_data(ttl=60)
    def load_coaches():
        return bq_client.get_grant_coaches()

    coaches_df = load_coaches()

    if not coaches_df.empty:
        for _, coach in coaches_df.iterrows():
            cc1, cc2, cc3 = st.columns([3, 2, 0.8])
            cc1.markdown(f"**{coach['full_name']}**")
            cc2.caption(coach.get("email") or "")
            if cc3.button("Remove", key=f"remove_coach_{coach['member_id']}"):
                _rid = int(coach["member_id"])
                concurrent.futures.ThreadPoolExecutor(max_workers=1).submit(
                    bq_client.remove_grant_coach, _rid
                )
                load_coaches.clear()
                st.rerun()
    else:
        st.info("No grant coaches added yet.")

    st.divider()
    st.markdown("#### Add a Grant Coach")

    # Live BQ search — the community has 24k+ members so in-memory caching
    # is not viable. Query runs on each rerun when ≥3 chars are typed.
    @st.cache_data(ttl=60, show_spinner="Searching…")
    def _search_members_live(q: str):
        return bq_client.search_members(q, limit=20)

    _existing_coach_ids = set(coaches_df["member_id"].tolist()) if not coaches_df.empty else set()

    search_query = st.text_input("Search member by name or email", placeholder="e.g. Jane Smith")

    _q = search_query.strip()
    if len(_q) >= 3:
        _raw = _search_members_live(_q)
        results = _raw[~_raw["member_id"].isin(_existing_coach_ids)].head(20)

        if results.empty:
            st.caption("No members found.")
        else:
            for _, member in results.iterrows():
                m1, m2, m3 = st.columns([3, 2.5, 1.2])
                m1.markdown(f"**{member['full_name']}**")
                m2.caption(member.get("email_address") or "")

                if m3.button("Make Coach", key=f"promote_{member['member_id']}", type="primary"):
                    if not _admin_api_key:
                        st.error("No MN API key found. Add yours in the ⚙️ Settings tab first.")
                    else:
                        _mid   = int(member["member_id"])
                        _fname = str(member["full_name"])
                        _email = str(member.get("email_address") or "")
                        _by    = current_user or "admin"
                        _key   = _admin_api_key

                        try:
                            bq_client.add_grant_coach(_mid, _fname, _email, _by)
                            load_coaches.clear()
                        except Exception as _e:
                            bq_client.log_event("ERROR", "make_coach.add", f"Failed to add coach {_fname}", str(_e))
                            st.error(f"Could not add coach to database: {_e}")
                            st.stop()

                        try:
                            bq_client.mn_promote_to_host(_mid, _key)
                        except Exception as _e:
                            bq_client.log_event("ERROR", "make_coach.promote", f"Failed to promote {_fname} to host", str(_e))
                            st.warning(f"Coach added to database, but MN host promotion failed: {_e}")

                        st.session_state["invite_name"] = _fname
                        st.rerun()

    if "invite_name" in st.session_state:
        @st.dialog(f"Invite {st.session_state['invite_name']}")
        def _invite_dialog():
            app_url = st.secrets.get("app_url", "https://grant-helpdesk-170880920649.europe-west1.run.app")
            st.markdown("Share this link with the new grant coach:")
            st.code(app_url, language=None)
            st.caption("They can sign in with email/password or Google. On first login they'll be prompted to add their MN API key.")
            if st.button("Done", use_container_width=True):
                del st.session_state["invite_name"]
                st.rerun()
        _invite_dialog()

    # ── Error Log ─────────────────────────────────────────────────────────────
    st.divider()
    _el_col1, _el_col2, _el_col3 = st.columns([3, 2, 1])
    _el_col1.subheader("🔴 Error Log")
    _el_level = _el_col2.selectbox(
        "Level", ["All", "ERROR", "WARNING", "INFO"],
        index=0, key="error_log_level", label_visibility="collapsed"
    )
    _el_refresh = _el_col3.button("↺ Refresh", key="error_log_refresh", use_container_width=True)

    @st.cache_data(ttl=60, show_spinner=False)
    def load_app_logs(level_filter: str):
        lvl = None if level_filter == "All" else level_filter
        return bq_client.get_app_logs(limit=100, level=lvl)

    if _el_refresh:
        load_app_logs.clear()

    _log_df = load_app_logs(_el_level)

    if _log_df.empty:
        st.info("No log entries found.")
    else:
        # ERROR → red, WARNING → orange, INFO → violet; anything else grey.
        _LEVEL_COLOR = {"ERROR": "var(--on-tint-danger)", "WARNING": "var(--on-tint-warning)", "INFO": "var(--on-tint-info)"}
        _LEVEL_BG    = {"ERROR": "var(--tint-danger)",    "WARNING": "var(--tint-warning)",    "INFO": "var(--tint-info)"}
        for _, row in _log_df.iterrows():
            _lvl = str(row.get("level") or "INFO")
            _fg  = _LEVEL_COLOR.get(_lvl, "var(--color-text-soft)")
            _bg  = _LEVEL_BG.get(_lvl, "var(--tint-neutral)")
            _ts  = str(row.get("created_at", ""))[:19].replace("T", " ")
            _src = str(row.get("source") or "")
            _msg = str(row.get("message") or "")
            _det = str(row.get("detail") or "")
            st.markdown(f"""
<div style="background:{_bg};border:1px solid var(--color-divider);border-radius:var(--radius-md);
            padding:8px 12px;margin-bottom:6px;font-size:0.82rem;line-height:1.5">
  <span style="color:{_fg};font-weight:600">{_lvl}</span>
  <span style="color:var(--color-text-muted);margin-left:10px">{_ts}</span>
  <span style="color:var(--color-text-muted);margin-left:10px;font-family:var(--font-mono)">{_src}</span>
  <div style="color:var(--color-text);margin-top:3px">{_msg}</div>
  {f'<div style="color:var(--color-text-muted);font-size:0.78rem;margin-top:2px;white-space:pre-wrap">{_det[:300]}</div>' if _det and _det != "None" else ""}
</div>""", unsafe_allow_html=True)


# ── INBOX TAB ─────────────────────────────────────────────────────────────────
_FEEDBACK_TYPES = {
    "review":     ("⭐", "Review",     "Share how things are going — what's working, what's not, how you feel about the workflow."),
    "problem":    ("🔴", "Problem",    "Something is broken, confusing, or getting in your way. Tell me exactly what happened."),
    "suggestion": ("💡", "Suggestion", "An idea, improvement, or feature you'd like to see. No idea is too small."),
}
# Studiolo's four: orange = in progress, violet = primary, green = done.
# The badge takes a 12% wash of the hue behind and the hue as text.
_FEEDBACK_STATUS_COLORS = {
    "open":  "#e47d17",
    "noted": "#543ff8",
    "done":  "#20a375",
}


@st.fragment
def render_inbox(current_user):
    # ── Hero banner ───────────────────────────────────────────────────────────
    st.markdown("""
    <div class="inbox-hero">
      <div class="inbox-hero-title">📬 Team Inbox</div>
      <div class="inbox-hero-body">
        This is your direct line to me. Submit a review, flag a problem, or drop a suggestion —
        <strong>you cannot give me enough new input.</strong> Every submission becomes a ticket
        and I will personally reply with exactly what we will do about it.
      </div>
    </div>
    """, unsafe_allow_html=True)

    col_form, col_inbox = st.columns([1, 1.6], gap="large")

    # ── Submit form ───────────────────────────────────────────────────────────
    with col_form:
        st.markdown("### Submit something")

        fb_type = st.radio(
            "What kind of input is this?",
            list(_FEEDBACK_TYPES.keys()),
            format_func=lambda k: f"{_FEEDBACK_TYPES[k][0]}  {_FEEDBACK_TYPES[k][1]}",
            horizontal=False,
            key="fb_type_radio",
        )
        st.caption(_FEEDBACK_TYPES[fb_type][2])

        fb_title = st.text_input("Title", placeholder="Short summary — one line", key="fb_title")
        fb_body  = st.text_area(
            "Details",
            placeholder="Be as specific as possible. The more context you give, the better I can act on it.",
            height=160,
            key="fb_body",
        )

        if st.button("Send →", type="primary", use_container_width=True, key="fb_submit"):
            if not fb_title.strip():
                st.warning("Please add a title.")
            elif not fb_body.strip():
                st.warning("Please add some details.")
            elif not current_user:
                st.error("Could not identify your user — please reload.")
            else:
                bq_client.submit_team_feedback(
                    submitted_by=current_user,
                    feedback_type=fb_type,
                    title=fb_title.strip(),
                    body=fb_body.strip(),
                )
                st.success("Sent! I'll reply here as soon as possible.")
                st.cache_data.clear()
                st.rerun()

    # ── Inbox list ────────────────────────────────────────────────────────────
    with col_inbox:
        st.markdown("### All submissions")

        @st.cache_data(ttl=60)
        def load_team_feedback():
            return bq_client.get_team_feedback()

        fb_df = load_team_feedback()

        if fb_df.empty:
            st.info("No submissions yet — be the first!")
        else:
            _fc1, _fc2 = st.columns(2)
            _filter_type   = _fc1.selectbox(
                "Type", ["All"] + list(_FEEDBACK_TYPES.keys()),
                format_func=lambda k: "All" if k == "All" else f"{_FEEDBACK_TYPES[k][0]} {_FEEDBACK_TYPES[k][1]}",
                key="fb_filter_type",
            )
            _filter_status = _fc2.selectbox("Status", ["All", "open", "noted", "done"], key="fb_filter_status")

            rows = fb_df.copy()
            if _filter_type   != "All": rows = rows[rows["feedback_type"] == _filter_type]
            if _filter_status != "All": rows = rows[rows["status"]        == _filter_status]

            st.caption(f"{len(rows)} submission{'s' if len(rows) != 1 else ''}")

            for _, row in rows.iterrows():
                icon, label, _ = _FEEDBACK_TYPES.get(row["feedback_type"], ("📝", row["feedback_type"], ""))
                status_color   = _FEEDBACK_STATUS_COLORS.get(row["status"], "#94a3b8")
                date_str       = str(row["created_at"])[:10]

                with st.expander(
                    f"{icon} **{row['title']}**  ·  {row['submitted_by'].split('@')[0]}  ·  {date_str}",
                    expanded=False,
                ):
                    st.markdown(
                        f'<span class="feedback-badge" style="background:{status_color}1f;color:{status_color}">'
                        f'{row["status"].upper()}</span>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(row["body"])

                    if row.get("reply_text"):
                        st.divider()
                        # BQ NULLs surface as float NaN through pandas; NaN is not
                        # "missing" so .get()'s default never fires and NaN.split()
                        # crashes. Coerce anything non-string before splitting.
                        _rb = row.get("replied_by")
                        _rb = _rb.split("@")[0] if isinstance(_rb, str) and _rb else "admin"
                        st.markdown(
                            f'<div class="reply-block">'
                            f'<div class="reply-meta">Reply from {_rb} · {str(row.get("replied_at",""))[:10]}</div>'
                            f'<div>{row["reply_text"]}</div></div>',
                            unsafe_allow_html=True,
                        )

                    if current_user == "martin.j.menke@gmail.com":
                        st.divider()
                        _reply_text = st.text_area(
                            "Your reply", key=f"reply_text_{row['feedback_id']}",
                            value=row.get("reply_text") or "",
                            placeholder="What will we do about this?",
                            height=80,
                        )
                        _new_status = st.selectbox(
                            "Update status", ["open", "noted", "done"],
                            index=["open", "noted", "done"].index(row["status"]) if row["status"] in ["open", "noted", "done"] else 0,
                            key=f"reply_status_{row['feedback_id']}",
                        )
                        if st.button("Save reply", key=f"reply_save_{row['feedback_id']}", type="primary"):
                            bq_client.reply_team_feedback(
                                feedback_id=row["feedback_id"],
                                reply_text=_reply_text.strip(),
                                replied_by=current_user,
                                new_status=_new_status,
                            )
                            st.cache_data.clear()
                            st.rerun()


with tab_inbox:
    render_inbox(current_user)
