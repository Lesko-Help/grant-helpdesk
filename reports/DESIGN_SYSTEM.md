# Lesko UI — Design System Spec

> **September 2026 — look and feel is now Studiolo.** The layer structure below
> still holds (tokens → base → components → Streamlit overrides → zone CSS), but
> the values changed: four colours only (violet `#543ff8`, red `#ed1748`, green
> `#20a375`, orange `#e47d17`, each with a deepened twin), neutral grey for
> everything else, the system font at 14px, one visible hairline `#d5d8e0` on
> every card, no shadows at rest. `lesko-ui/tokens.css` is the source of truth
> and `tests/test_theme.py` fails the build on any colour outside that set. The
> token values quoted in the sections below are the pre-Studiolo ones and are
> kept for history.

This document defines the building blocks for a unified CSS design system, shared across the grant-helpdesk app and all future Lesko apps.

---

## File Structure

```
lesko-ui/                  ← shared package, lives outside any single app
├── tokens.css             ← Layer 1: all design tokens (colors, spacing, type, radius, shadow)
├── base.css               ← Layer 2: reset + global font/background
├── components.css         ← Layer 3: reusable component classes (badge, card, avatar…)
├── streamlit.css          ← Layer 4: Streamlit widget overrides
├── ui_theme.py            ← Python bridge: constants + CSS injector
└── components.py          ← Python HTML helpers (kpi_card, badge, avatar…)

grant-helpdesk/
├── app.py
├── static/
│   ├── sidebar.css        ← Zone 1 styles
│   ├── header.css         ← Zone 2 + 3 styles
│   ├── kpi.css            ← Zone 4 styles
│   └── tickets.css        ← Zone 5 + 6 styles
└── (symlink or copy of lesko-ui/)
```

---

## Layer 1 — Design Tokens

The single source of truth. Every visual decision is a named variable. No magic numbers anywhere in component CSS.

```css
:root {
    /* ── Brand colors ── */
    --color-indigo:  #4a52a3;
    --color-yellow:  #f5c520;
    --color-green:   #2e9b2e;
    --color-blue:    #2d6ee0;
    --color-red:     #e03c3c;

    /* ── Semantic colors (what the color MEANS, not what it is) ── */
    --color-primary:    var(--color-indigo);
    --color-success:    var(--color-green);
    --color-warning:    var(--color-yellow);
    --color-danger:     var(--color-red);
    --color-info:       var(--color-blue);

    /* ── Surface colors ── */
    --color-bg:         #e8eef6;   /* page background */
    --color-surface:    #ffffff;   /* cards, sidebar, header */
    --color-surface-2:  #f5f7fb;   /* input fields, hover rows */

    /* ── Text colors ── */
    --color-text:       #111827;   /* primary text */
    --color-text-muted: #6b7280;   /* labels, captions */
    --color-text-faint: #9ca3af;   /* placeholders, dates */

    /* ── Spacing scale (4px base grid) ── */
    --space-1:  4px;
    --space-2:  8px;
    --space-3:  12px;
    --space-4:  16px;
    --space-5:  20px;
    --space-6:  24px;
    --space-8:  32px;
    --space-10: 40px;

    /* ── Border radius ── */
    --radius-sm:   8px;    /* small chips, metric cards */
    --radius-md:   12px;   /* comments, inner frames */
    --radius-lg:   16px;   /* sidebar frames, buttons */
    --radius-xl:   20px;   /* section cards, header */
    --radius-pill: 999px;  /* badges, pills, avatars */

    /* ── Typography ── */
    --font-family:  "Inter", "Helvetica Neue", Arial, sans-serif;
    --font-xs:   0.68rem;  /* uppercase labels, tiny metadata */
    --font-sm:   0.82rem;  /* captions, secondary info */
    --font-base: 0.9rem;   /* body text, ticket content */
    --font-md:   1rem;     /* card titles, tab labels */
    --font-lg:   1.3rem;   /* dialog headings */
    --font-xl:   1.5rem;   /* page headings */

    /* ── KPI values (special large numbers) ── */
    --font-kpi-lg: 2.4rem;
    --font-kpi-md: 2rem;

    /* ── Shadows ── */
    --shadow-card:  0 4px 24px rgba(74,82,163,0.10);
    --shadow-modal: 0 8px 32px rgba(74,82,163,0.18);
}
```

---

## Layer 2 — Base

Normalize browser defaults. Applied globally.

```css
/* base.css */
html, body, * {
    font-family: var(--font-family);
    font-size: 14px;
}
hr {
    border-color: #e0e6f0;
}
```

---

## Layer 3 — Components

Reusable building blocks. Defined once, used everywhere. No inline styles — only class names.

### Cards
```css
.card {
    background: var(--color-surface);
    border-radius: var(--radius-xl);
    padding: var(--space-5) var(--space-6);
    box-shadow: var(--shadow-card);
}
```

### Badges (status)
```css
.badge             { padding: var(--space-1) var(--space-2); border-radius: var(--radius-pill); font-size: var(--font-xs); font-weight: 500; }
.badge-open        { background: #e1edfb; color: #1d4e8c; }
.badge-answered    { background: #d6f0d6; color: #1f6a1f; }
.badge-closed      { background: #d6f0d6; color: #1f6a1f; }
.badge-cancelled   { background: #fde0e0; color: #8a1f1f; }
.badge-flagged     { background: #fdf3d4; color: #7a5f00; }
.badge-not_a_question { background: #f0f0f0; color: #666; }
```

### Urgency pills
```css
.urg-pill    { padding: var(--space-1) var(--space-2); border-radius: var(--radius-pill); font-size: var(--font-xs); font-weight: 500; }
.urg-normal  { background: #e6f4e6; color: #1f6a1f; }
.urg-urgent  { background: #fdf3d4; color: #7a5f00; }
.urg-critical{ background: #fde0e0; color: #8a1f1f; }
```

### Avatars
```css
.avatar        { width: 28px; height: 28px; border-radius: var(--radius-pill); display: inline-flex; align-items: center; justify-content: center; font-size: var(--font-xs); font-weight: 500; }
.avatar-indigo { background: var(--color-indigo); color: white; }
.avatar-green  { background: var(--color-green);  color: white; }
.avatar-blue   { background: var(--color-blue);   color: white; }
.avatar-red    { background: var(--color-red);     color: white; }
.avatar-yellow { background: var(--color-yellow);  color: #5a4400; }
```

---

## Layer 4 — Streamlit Overrides

Override Streamlit's widget styles to match the design system.

```css
/* streamlit.css */
.stApp                                    { background-color: var(--color-bg); }
section[data-testid="stMain"] > div      { background-color: var(--color-bg); }
[data-testid="stSidebar"]                { background-color: var(--color-surface); border-right: 1px solid var(--color-bg); }
button[data-baseweb="tab"]               { border-radius: var(--radius-lg); font-size: var(--font-sm); font-weight: 500; }
button[data-baseweb="tab"][aria-selected="true"] { background-color: var(--color-primary); color: white; }
button[data-testid="baseButton-primary"] { background-color: var(--color-primary); border-radius: var(--radius-pill); }
```

---

## UI Zones

The app is divided into 6 visual zones. Each zone has its own CSS file and its own design rules.

```
┌─────────────┬──────────────────────────────────────────┐
│             │  ZONE 2: App Header                      │
│  ZONE 1:    ├──────────────────────────────────────────┤
│  Sidebar    │  ZONE 3: Tab Navigation                  │
│  Filter     ├──────────────────────────────────────────┤
│  Panel      │  ZONE 4: KPI Cards                       │
│             ├──────────────────────────────────────────┤
│             │  ZONE 5: Ticket Table                    │
│             │  ┌────────────────────────────────────┐  │
│             │  │  ZONE 6: Ticket Row                 │  │
│             │  └────────────────────────────────────┘  │
└─────────────┴──────────────────────────────────────────┘
```

---

### Zone 1 — Sidebar Filter Panel

Compact, utilitarian, low visual weight. Supports the content, does not compete with it.

| Property | Value |
|---|---|
| Background | `--color-surface` |
| Font size (labels) | `--font-xs`, uppercase, letter-spaced |
| Font size (values) | `--font-sm` |
| Input fields | `--color-surface-2` background, no border, `--radius-lg` |
| Padding | tight — `--space-3` internal |
| Right border | 1px `--color-bg` separating from main content |
| Dividers | subtle `--color-bg` |

---

### Zone 2 — App Header

Brand identity. Appears once. Sets the tone.

| Property | Value |
|---|---|
| Background | `--color-surface` card |
| Border radius | `--radius-xl` |
| Height | fixed, compact (~60px) |
| Logo block | `--color-primary` square, `--radius-lg`, white letter |
| App name | `--font-md`, weight 500, `--color-text` |
| Subtitle | `--font-xs`, `--color-text-muted` |
| User pill | avatar + first name, right-aligned, `--color-surface-2` background |

---

### Zone 3 — Tab Navigation

Wayfinding. Which tab am I on?

| Property | Value |
|---|---|
| Container | `--color-surface` pill, `--radius-pill`, `--space-1` padding |
| Tab default | `--color-text-muted`, no background |
| Tab active | `--color-primary` background, white text, `--radius-lg` |
| Font | `--font-sm`, weight 500 |
| Gap between tabs | `--space-1` |

---

### Zone 4 — KPI Cards

Data at a glance. Numbers are the largest thing on screen.

| Property | Value |
|---|---|
| Background | `--color-surface` |
| Border radius | `--radius-xl` |
| Value font size | `--font-kpi-lg` (2.4rem), weight 600, `--color-text` |
| Label font size | `--font-sm`, `--color-text-muted` |
| Accent | small colored dot — NOT large colored backgrounds |
| Goal card exception | full `--color-primary` background, inverted white text |
| Internal padding | `--space-5` vertical, `--space-6` horizontal |

---

### Zone 5 — Ticket Table (container)

The workspace. Structured and scannable.

| Property | Value |
|---|---|
| Background | `--color-surface` card wrapping the list |
| Column headers | `--font-xs`, uppercase, `--color-text-faint`, letter-spaced |
| Dividers | 1px `--color-bg` between rows |
| Row spacing | `--space-3` vertical padding per row |
| Pagination | `--font-sm`, centered, `--color-text-muted` |

---

### Zone 6 — Ticket Row

The atomic unit. The thing the team interacts with most.

| Element | Property | Value |
|---|---|---|
| Member name | font | `--font-base`, weight 500, clickable |
| Date | font | `--font-xs`, `--color-text-faint`, below name |
| Question text | color | `--color-primary` tint, truncated with hover tooltip |
| Urgency dot | size | 10px circle, color maps to urgency level |
| Status dropdown | style | no border, compact, inline |
| Coach initials | style | small avatar, right-aligned, `--color-primary` text |
| Open button → | style | 24px `--color-primary` circle, far right |
| Row hover | background | `--color-surface-2` |
| Group row | treatment | "N comments in thread · N open" label instead of text preview |

---

## What the Design Team Must Deliver

For each zone, the design team must confirm or define:

| Decision | Sidebar | Header | Tabs | KPI | Table | Row |
|---|---|---|---|---|---|---|
| Background color | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Font size | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Font weight | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Padding / spacing | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Border / shadow | ✓ | ✓ | — | ✓ | ✓ | ✓ |
| Hover state | — | — | ✓ | — | — | ✓ |
| Active / selected state | — | — | ✓ | — | — | ✓ |

### Preferred deliverable format

A **Figma file** with:
- Color styles panel (all named brand + semantic + surface colors)
- Text styles panel (all named type sizes and weights)
- Component page with every zone rendered in every state (default / hover / active / disabled)

From a complete Figma file, every token and every CSS file can be built in a single pass with no guessing.

---

## The Golden Rule

> **No magic numbers in HTML strings.**
> Every `style=""` attribute must either reference a CSS class or use a `var(--…)` token.
> If you find yourself writing `style="padding:37px"` — stop, add a token, use a class.

---

## Tokens That Need Design Team Sign-off

The following values are currently set ad-hoc in the app. Design team should confirm or replace before CSS is built.

| Token | Current value | Confirmed? |
|---|---|---|
| `--color-indigo` | `#4a52a3` | ☐ |
| `--color-yellow` | `#f5c520` | ☐ |
| `--color-green` | `#2e9b2e` | ☐ |
| `--color-blue` | `#2d6ee0` | ☐ |
| `--color-red` | `#e03c3c` | ☐ |
| `--color-bg` | `#e8eef6` | ☐ |
| `--color-surface` | `#ffffff` | ☐ |
| `--color-surface-2` | `#f5f7fb` | ☐ |
| `--font-family` | `"Inter"` | ☐ |
| Spacing base unit | `4px` | ☐ |
| Card border radius | `20px` (currently inconsistent) | ☐ |
