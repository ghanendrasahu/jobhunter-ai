# ruff: noqa: E501
"""Shared Streamlit design system for the deployed app fleet.

One identity across every dashboard:
  * dark "midnight" canvas, Inter type, indigo accent (#8B93FF)
  * 32/24/20/16/14/13 type scale, 1120px content cap
  * semantic colour tokens (success / warning / danger / neutral)
  * Lucide-style inline SVG icons instead of emoji
  * Streamlit chrome (Deploy button, menu, footer) hidden; a slim header
    keeps the sidebar toggle reachable

Vendored copy: keep byte-identical across the fleet. Canonical source:
``render-configs/fleet_ui.py``; sync and drift check with
``render-configs/sync_fleet_ui.py``.

Usage:
    import ui
    ui.setup("Overview", layout="wide")
    ui.page_header("Credit Risk", "Estimate ...", eyebrow="Credit Risk Lab")
    ui.section("Applicant details", "...")
    ui.empty_state("No assessment yet", "Fill in the form ...")
    ui.metric_card("Default probability", "18.4%", delta=4.2, suffix="pp",
                   good_direction="down", caption="vs. previous run")
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import streamlit as st

# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------
BG = "#0B0D12"
SURFACE = "#111521"
SURFACE_2 = "#151A27"
BORDER = "#232B3D"
BORDER_STRONG = "#2F3A50"
TEXT = "#E8EBF5"
MUTED = "#9AA4B8"
PRIMARY = "#8B93FF"
SUCCESS = "#46D39A"
WARNING = "#F2B544"
DANGER = "#F17C7C"

FONT = "Inter, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"

FONT_IMPORT = "@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');"

# ---------------------------------------------------------------------------
# Icons (24x24, stroke = currentColor)
# ---------------------------------------------------------------------------
_ICONS: dict[str, str] = {
    "sparkles": (
        '<path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/>'
    ),
    "message": '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "upload": (
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        '<path d="m17 8-5-5-5 5"/><path d="M12 3v12"/>'
    ),
    "file": (
        '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>'
        '<path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M8 13h8"/><path d="M8 17h8"/>'
    ),
    "chart": '<path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/>',
    "shield": '<path d="M20 13c0 5-3.5 7.5-8 9-4.5-1.5-8-4-8-9V6l8-3 8 3Z"/>',
    "alert": (
        '<path d="m21.7 18-8-14a2 2 0 0 0-3.4 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3Z"/>'
        '<path d="M12 9v4"/><path d="M12 17h.01"/>'
    ),
    "check": '<path d="M21.8 10A10 10 0 1 1 17 3.3"/><path d="m9 11 3 3L22 4"/>',
    "arrow-right": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    "arrow-up": '<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>',
    "arrow-down": '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
    "briefcase": (
        '<rect x="2" y="7" width="20" height="14" rx="2"/>'
        '<path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/>'
    ),
    "activity": '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
    "sliders": (
        '<path d="M4 21v-7"/><path d="M4 10V3"/><path d="M12 21v-9"/>'
        '<path d="M12 8V3"/><path d="M20 21v-5"/><path d="M20 12V3"/>'
        '<path d="M2 14h4"/><path d="M10 8h4"/><path d="M18 16h4"/>'
    ),
    "play": '<path d="m6 3 14 9-14 9V3Z"/>',
    "refresh": (
        '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/>'
        '<path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/>'
        '<path d="M8 16H3v5"/>'
    ),
    "download": (
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        '<path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>'
    ),
    "trash": (
        '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>'
        '<path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'
    ),
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "bot": (
        '<path d="M12 8V4H8"/><rect x="4" y="8" width="16" height="12" rx="2"/>'
        '<path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/>'
    ),
    "pin": '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/>',
    "close": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "database": (
        '<ellipse cx="12" cy="5" rx="8" ry="3"/>'
        '<path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/>'
        '<path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>'
    ),
}


def svg(name: str, size: int = 20, stroke: float = 1.8) -> str:
    """Return an inline SVG icon (no emoji anywhere in the UI)."""
    body = _ICONS.get(name, _ICONS["sparkles"])
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{stroke}" '
        f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{body}</svg>'
    )


def mark(size: int = 38) -> str:
    """Shared fleet mark: rounded indigo tile with a GS monogram."""
    return (
        f'<span class="ui-mark" style="width:{size}px;height:{size}px">'
        '<svg width="100%" height="100%" viewBox="0 0 40 40" aria-hidden="true">'
        '<defs><linearGradient id="ui-g" x1="4" y1="2" x2="36" y2="38" '
        'gradientUnits="userSpaceOnUse"><stop stop-color="#A7AEFF"/>'
        '<stop offset="0.55" stop-color="#8B93FF"/><stop offset="1" stop-color="#5C66E8"/>'
        "</linearGradient></defs>"
        '<rect width="40" height="40" rx="11" fill="url(#ui-g)"/>'
        '<text x="20" y="26" text-anchor="middle" font-family="Inter, sans-serif" '
        'font-size="15" font-weight="700" fill="#0B0D12" letter-spacing="-0.4">GS</text>'
        "</svg></span>"
    )


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
CSS = f"""
<style>
{FONT_IMPORT}

:root {{
  --ui-bg: {BG};
  --ui-surface: {SURFACE};
  --ui-surface-2: {SURFACE_2};
  --ui-border: {BORDER};
  --ui-border-strong: {BORDER_STRONG};
  --ui-text: {TEXT};
  --ui-muted: {MUTED};
  --ui-primary: {PRIMARY};
  --ui-success: {SUCCESS};
  --ui-warning: {WARNING};
  --ui-danger: {DANGER};
  --ui-radius: 12px;
  --ui-radius-sm: 9px;
}}

/* ---------- canvas ---------- */
html, body, [data-testid="stAppViewContainer"], .stApp {{
  background: var(--ui-bg) !important;
  color: var(--ui-text);
  font-family: {FONT};
}}
h1, h2, h3, h4, h5, h6, p, li, label, input, textarea, button, select, option,
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2, [data-testid="stMarkdownContainer"] h3,
[data-testid="stWidgetLabel"] p, [data-testid="stMetricLabel"] p,
[data-testid="stCaptionContainer"] p {{
  font-family: {FONT} !important;
}}
.stApp {{ background: var(--ui-bg) !important; }}
[data-testid="stHeader"] {{
  background: transparent !important; height: 48px !important; min-height: 48px !important;
}}
[data-testid="stDecoration"], [data-testid="stStatusWidget"], #MainMenu, footer,
.stDeployButton {{ display: none !important; }}
[data-testid="stToolbar"] {{ background: transparent !important; padding: 0 !important; }}
[data-testid="stToolbar"] [data-testid="stActionButton"],
[data-testid="stToolbar"] [data-testid="stMainMenuButton"] {{ display: none !important; }}
[data-testid="stExpandSidebarButton"] {{
  border-radius: 9px !important;
  border: 1px solid var(--ui-border) !important;
  background: var(--ui-surface) !important;
}}
[data-testid="stExpandSidebarButton"]:hover {{ background: var(--ui-surface-2) !important; }}
[data-testid="stExpandSidebarButton"] span[data-testid="stIconMaterial"] {{ font-size: 20px !important; }}
[data-testid="stAppViewContainer"] > section {{ background: var(--ui-bg); }}
[data-testid="stAppViewContainer"] > section > div {{ padding-top: 0; }}

.block-container, [data-testid="stMainBlockContainer"] {{
  max-width: 1120px !important;
  padding-left: 1.5rem !important;
  padding-right: 1.5rem !important;
  padding-top: 3.4rem !important;
  padding-bottom: 4rem !important;
}}

/* ---------- typography ---------- */
h1, h2, h3, h4, h5, h6 {{ font-family: {FONT}; color: var(--ui-text); letter-spacing: -0.02em; }}
h1 {{ font-size: 32px; line-height: 1.15; font-weight: 700; margin: 0 0 .35rem; }}
h2 {{ font-size: 24px; line-height: 1.25; font-weight: 650; margin: 0 0 .3rem; }}
h3 {{ font-size: 20px; line-height: 1.3; font-weight: 600; }}
[data-testid="stHeading"] h1 {{ font-size: 32px !important; }}
[data-testid="stHeading"] h2 {{ font-size: 24px !important; }}
[data-testid="stHeading"] h3,
[data-testid="stMarkdownContainer"] h3 {{ font-size: 20px !important; line-height: 1.3 !important; }}
p, li, label, .stMarkdown {{ font-size: 15px; line-height: 1.62; }}
small, .stCaption, [data-testid="stCaptionContainer"] p, [data-testid="stCaptionContainer"] {{
  font-size: 13px !important; color: var(--ui-muted) !important;
}}
a {{ color: var(--ui-primary); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
code {{ background: var(--ui-surface-2); color: #C9D0E0; border-radius: 6px; padding: .1rem .35rem; font-size: .85em; }}
hr {{ border-color: var(--ui-border); }}

/* ---------- header ---------- */
.ui-header {{
  display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem;
  padding-bottom: 1.1rem; margin-bottom: 1.4rem; border-bottom: 1px solid var(--ui-border);
}}
.ui-header-main {{ display: flex; align-items: flex-start; gap: .9rem; flex: 1 1 auto; min-width: 0; }}
.ui-mark {{
  display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto;
  border-radius: 11px; overflow: hidden; box-shadow: 0 8px 22px -12px rgba(139,147,255,.9);
}}
.ui-eyebrow {{
  font-size: 12px; font-weight: 600; letter-spacing: .12em; text-transform: uppercase;
  color: var(--ui-muted); margin-bottom: .35rem;
}}
.ui-title {{ font-size: 32px !important; line-height: 1.12; font-weight: 700; letter-spacing: -.025em; margin: 0; }}
.ui-subtitle {{ font-size: 15px !important; line-height: 1.6; color: var(--ui-muted); margin: .45rem 0 0; max-width: 76ch; }}
.ui-header-badge {{
  flex: 0 0 auto; display: inline-flex; align-items: center; gap: .4rem;
  padding: .35rem .7rem; border-radius: 999px; font-size: 12px; font-weight: 600;
  border: 1px solid var(--ui-border); background: var(--ui-surface); color: var(--ui-muted);
  white-space: nowrap;
}}
.ui-header-badge.ok {{ color: var(--ui-success); border-color: rgba(70,211,154,.35); background: rgba(70,211,154,.08); }}
.ui-header-badge.warn {{ color: var(--ui-warning); border-color: rgba(242,181,68,.35); background: rgba(242,181,68,.08); }}
.ui-header-badge.bad {{ color: var(--ui-danger); border-color: rgba(241,124,124,.35); background: rgba(241,124,124,.08); }}

/* ---------- section ---------- */
.ui-section {{ margin: 1.4rem 0 .8rem; }}
.ui-section h2 {{ font-size: 20px !important; font-weight: 650; margin: 0; }}
.ui-section p {{ font-size: 14px !important; color: var(--ui-muted); margin: .25rem 0 0; }}

/* ---------- cards ---------- */
.ui-card {{
  background: var(--ui-surface); border: 1px solid var(--ui-border);
  border-radius: var(--ui-radius); padding: 1.1rem 1.2rem;
}}
.ui-card + .ui-card {{ margin-top: .75rem; }}

/* ---------- result panel ---------- */
.ui-result {{
  background: var(--ui-surface); border: 1px solid var(--ui-border);
  border-radius: var(--ui-radius); padding: 1.25rem 1.25rem 1.1rem;
}}
.ui-result-head {{ display: flex; align-items: center; justify-content: space-between; gap: .75rem; }}
.ui-result-label {{ font-size: 13px; color: var(--ui-muted); }}
.ui-result-value {{ font-size: 40px !important; font-weight: 700; letter-spacing: -.03em; line-height: 1.05; margin: .3rem 0 .15rem; }}
.ui-result-note {{ font-size: 13px; color: var(--ui-muted); line-height: 1.55; }}
.ui-meter {{ height: 8px; border-radius: 999px; background: #1B2234; overflow: hidden; margin: .95rem 0 .55rem; }}
.ui-meter > span {{ display: block; height: 100%; border-radius: 999px; }}
.ui-kv {{ display: flex; justify-content: space-between; gap: 1rem; padding: .5rem 0; border-top: 1px solid var(--ui-border); font-size: 13px; }}
.ui-kv:first-of-type {{ border-top: 0; padding-top: .2rem; }}
.ui-kv dt {{ color: var(--ui-muted); margin: 0; }}
.ui-kv dd {{ color: var(--ui-text); font-weight: 600; margin: 0; text-align: right; }}

/* ---------- empty state ---------- */
.ui-empty {{
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  text-align: center; gap: .45rem; padding: 2.6rem 1.5rem;
  background: var(--ui-surface); border: 1px dashed var(--ui-border-strong);
  border-radius: var(--ui-radius);
}}
.ui-empty-icon {{
  display: inline-flex; align-items: center; justify-content: center;
  width: 44px; height: 44px; border-radius: 12px; margin-bottom: .35rem;
  color: var(--ui-primary); background: rgba(139,147,255,.10);
  border: 1px solid rgba(139,147,255,.22);
}}
.ui-empty-title {{ font-size: 16px; font-weight: 600; color: var(--ui-text); }}
.ui-empty-body {{ font-size: 14px; color: var(--ui-muted); max-width: 52ch; line-height: 1.6; }}
.ui-empty-hint {{ font-size: 13px; color: var(--ui-muted); margin-top: .35rem; }}

/* ---------- error state ---------- */
.ui-error {{
  display: flex; gap: .9rem; align-items: flex-start;
  padding: 1rem 1.1rem; border-radius: var(--ui-radius);
  background: rgba(241,124,124,.06); border: 1px solid rgba(241,124,124,.28);
}}
.ui-error-icon {{ color: var(--ui-danger); flex: 0 0 auto; margin-top: .1rem; }}
.ui-error-title {{ font-size: 15px; font-weight: 600; color: var(--ui-text); margin: 0 0 .2rem; }}
.ui-error-body {{ font-size: 14px; color: var(--ui-muted); line-height: 1.55; margin: 0; }}
.ui-error-hint {{ font-size: 13px; color: var(--ui-muted); margin: .45rem 0 0; }}

/* ---------- metric ---------- */
.ui-metric-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(155px, 1fr));
  gap: .75rem;
}}
.ui-metric {{
  background: var(--ui-surface); border: 1px solid var(--ui-border);
  border-radius: var(--ui-radius); padding: 1rem 1.1rem; height: 100%;
}}
.ui-metric-label {{ font-size: 13px; font-weight: 500; color: var(--ui-muted); margin-bottom: .4rem; }}
.ui-metric-value {{ font-size: 28px !important; font-weight: 650; letter-spacing: -.025em; line-height: 1.1; color: var(--ui-text); }}
.ui-metric-delta {{ display: inline-flex; align-items: center; gap: .25rem; margin-top: .5rem; font-size: 13px; font-weight: 600; }}
.ui-metric-delta.good {{ color: var(--ui-success); }}
.ui-metric-delta.bad {{ color: var(--ui-danger); }}
.ui-metric-delta.neutral {{ color: var(--ui-muted); }}
.ui-metric-caption {{ font-size: 13px; color: var(--ui-muted); margin-top: .35rem; }}

/* ---------- widgets ---------- */
/* field shells: Streamlit <=1.49 (BaseWeb) and >=1.50 (react-aria) */
[data-testid="stTextInput"] [data-baseweb="input"],
[data-testid="stNumberInput"] [data-baseweb="input"],
[data-testid="stTextArea"] [data-baseweb="textarea"],
[data-testid="stDateInput"] [data-baseweb="input"],
[data-testid="stSelectbox"] [data-baseweb="select"] > div,
[data-testid="stTextInput"] .react-aria-TextField > div,
[data-testid="stNumberInput"] .react-aria-TextField > div,
[data-testid="stTextArea"] .react-aria-TextField > div,
[data-testid="stDateInput"] .react-aria-TextField > div,
[data-testid="stSelectbox"] [role="group"] {{
  background-color: var(--ui-surface) !important;
  background-image: none !important;
  border: 1px solid var(--ui-border) !important;
  border-radius: var(--ui-radius-sm) !important;
  min-height: 42px;
  box-shadow: none !important;
}}
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stDateInput"] input,
[data-testid="stSelectbox"] input,
[data-testid="stSelectbox"] [role="combobox"] {{
  background: transparent !important;
  border: 0 !important;
  color: var(--ui-text) !important;
  font-size: 14px !important;
  box-shadow: none !important;
}}
[data-testid="stSelectbox"] input::placeholder,
[data-testid="stTextInput"] input::placeholder,
[data-testid="stNumberInput"] input::placeholder,
[data-testid="stTextArea"] textarea::placeholder {{ color: #6F7A90 !important; }}
[data-testid="stTextInput"] [data-baseweb="input"]:focus-within,
[data-testid="stNumberInput"] [data-baseweb="input"]:focus-within,
[data-testid="stTextArea"] [data-baseweb="textarea"]:focus-within,
[data-testid="stSelectbox"] [data-baseweb="select"] > div:focus-within,
[data-testid="stTextInput"] .react-aria-TextField > div:focus-within,
[data-testid="stNumberInput"] .react-aria-TextField > div:focus-within,
[data-testid="stTextArea"] .react-aria-TextField > div:focus-within,
[data-testid="stSelectbox"] [role="group"]:focus-within {{
  border-color: var(--ui-primary) !important;
  box-shadow: 0 0 0 3px rgba(139,147,255,.16) !important;
}}
[data-testid="stNumberInput"] button {{ color: var(--ui-muted) !important; background: transparent !important; }}
[data-testid="stNumberInput"] button:hover {{ color: var(--ui-text) !important; }}
[data-testid="stSelectbox"] button {{ color: var(--ui-muted) !important; background: transparent !important; }}
/* Streamlit >=1.50 nests a light base-input shell inside the number field */
[data-testid="stNumberInput"] [data-baseweb="base-input"] {{
  background: transparent !important;
  border-color: transparent !important;
  box-shadow: none !important;
}}
/* the selectbox value is a plain div, not the hidden input */
[data-testid="stSelectbox"] [data-baseweb="select"] div[value],
[data-testid="stSelectbox"] [data-baseweb="select"] [role="combobox"] {{
  color: var(--ui-text) !important;
}}
/* slider value + tick labels */
[data-testid="stSlider"] [data-testid="stSliderThumbValue"] p {{
  color: var(--ui-text) !important; font-size: 13px !important; font-weight: 600 !important;
}}
[data-testid="stSlider"] [data-testid="stSliderTickBar"] p {{
  color: var(--ui-muted) !important; font-size: 12px !important;
}}
[role="listbox"] {{
  background: var(--ui-surface) !important;
  border: 1px solid var(--ui-border) !important;
  border-radius: var(--ui-radius-sm) !important;
}}
[role="option"] {{ color: var(--ui-text) !important; font-size: 14px !important; }}
[role="option"]:hover, [role="option"][aria-selected="true"] {{ background: var(--ui-surface-2) !important; }}
[data-testid="stWidgetLabel"] p, label p {{ font-size: 13px !important; font-weight: 500 !important; color: #C3CADB !important; }}

.stButton > button, [data-testid="stBaseButton-secondary"] {{
  width: 100%;
  background: var(--ui-surface-2) !important;
  color: var(--ui-text) !important;
  border: 1px solid var(--ui-border-strong) !important;
  border-radius: var(--ui-radius-sm) !important;
  padding: .55rem 1rem !important;
  font-size: 14px !important;
  font-weight: 600 !important;
  transition: background .15s ease, border-color .15s ease, transform .15s ease;
}}
.stButton > button:hover, [data-testid="stBaseButton-secondary"]:hover {{
  background: #1B2234 !important; border-color: #3A4660 !important;
}}
.stButton > button:active {{ transform: translateY(1px); }}
.stButton > button[kind="primary"],
[data-testid="stBaseButton-primary"],
[data-testid="stBaseButton-primaryFormSubmit"],
[data-testid="stFormSubmitButton"] button[kind="primary"] {{
  background: var(--ui-primary) !important;
  color: #0B0D12 !important;
  border: 1px solid var(--ui-primary) !important;
  font-weight: 650 !important;
  box-shadow: 0 8px 20px -12px rgba(139,147,255,.85);
}}
.stButton > button[kind="primary"]:hover,
[data-testid="stBaseButton-primary"]:hover,
[data-testid="stBaseButton-primaryFormSubmit"]:hover {{
  background: #9CA3FF !important; border-color: #9CA3FF !important;
}}
.stButton > button:disabled, [data-testid="stBaseButton-primary"]:disabled {{
  opacity: .45 !important; cursor: not-allowed;
}}

/* file uploader */
[data-testid="stFileUploaderDropzone"] {{
  background: var(--ui-surface) !important;
  border: 1px dashed var(--ui-border-strong) !important;
  border-radius: var(--ui-radius) !important;
  padding: 1.35rem 1.2rem !important;
}}
[data-testid="stFileUploaderDropzone"] span,
[data-testid="stFileUploaderDropzone"] small,
[data-testid="stFileUploaderDropzone"] div {{ color: var(--ui-muted) !important; font-size: 13px !important; }}
[data-testid="stFileUploaderDropzone"] svg {{ color: var(--ui-primary) !important; }}
[data-testid="stFileUploaderDropzone"] button {{
  background: var(--ui-surface-2) !important; color: var(--ui-text) !important;
  border: 1px solid var(--ui-border-strong) !important; border-radius: 8px !important;
}}

/* tabs */
[data-baseweb="tab-list"] {{ gap: .15rem; border-bottom: 1px solid var(--ui-border); }}
button[data-baseweb="tab"] {{
  color: var(--ui-muted) !important; font-size: 14px !important; font-weight: 600 !important;
  padding: .6rem .85rem !important; background: transparent !important;
}}
button[data-baseweb="tab"]:hover {{ color: var(--ui-text) !important; }}
button[data-baseweb="tab"][aria-selected="true"] {{ color: var(--ui-text) !important; }}
[data-baseweb="tab-highlight"] {{ background: var(--ui-primary) !important; height: 2px !important; }}
[data-baseweb="tab-border"] {{ background: var(--ui-border) !important; }}

/* forms */
[data-testid="stForm"], .stForm {{
  background: var(--ui-surface) !important;
  border: 1px solid var(--ui-border) !important;
  border-radius: var(--ui-radius) !important;
  padding: 1.15rem 1.2rem !important;
}}

/* expander */
[data-testid="stExpander"] details {{
  background: var(--ui-surface) !important;
  border: 1px solid var(--ui-border) !important;
  border-radius: var(--ui-radius) !important;
  overflow: hidden;
}}
[data-testid="stExpander"] summary {{ font-size: 14px !important; font-weight: 600 !important; color: var(--ui-text) !important; }}
[data-testid="stExpander"] summary:hover {{ color: var(--ui-primary) !important; }}

/* alerts */
[data-testid="stAlert"] {{
  border-radius: var(--ui-radius) !important;
  border: 1px solid var(--ui-border) !important;
  background: var(--ui-surface) !important;
  font-size: 14px !important;
}}
[data-testid="stAlert"] p {{ font-size: 14px !important; }}

/* metrics (native) */
[data-testid="stMetric"] {{
  background: var(--ui-surface); border: 1px solid var(--ui-border);
  border-radius: var(--ui-radius); padding: .9rem 1rem;
}}
[data-testid="stMetricLabel"] p {{ font-size: 13px !important; color: var(--ui-muted) !important; }}
[data-testid="stMetricValue"] {{ font-size: 26px !important; font-weight: 650 !important; letter-spacing: -.02em; }}

/* radio / checkbox */
[role="radiogroup"] label p, [data-testid="stCheckbox"] label p {{ font-size: 14px !important; }}
[data-testid="stSidebar"] [role="radiogroup"] {{ gap: 2px; }}
[data-testid="stSidebar"] [role="radiogroup"] label {{
  padding: .5rem .65rem; border-radius: 9px; width: 100%;
  border-left: 2px solid transparent;
}}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {{ background: var(--ui-surface-2); }}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
  background: rgba(139,147,255,.10); border-left-color: var(--ui-primary);
}}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {{ color: var(--ui-text) !important; font-weight: 600 !important; }}

/* sidebar */
[data-testid="stSidebar"] {{
  background: #0E1118 !important;
  border-right: 1px solid var(--ui-border);
}}
[data-testid="stSidebar"] > div:first-child {{ padding-top: 1.4rem; }}
[data-testid="stSidebar"] hr {{ margin: 1rem 0; }}
[data-testid="stSidebar"] .block-container {{ padding-top: 1.2rem !important; }}
[data-testid="stSidebar"] [data-testid="stMetric"] {{ background: var(--ui-surface); padding: .65rem .75rem; }}
[data-testid="stSidebar"] [data-testid="stMetricValue"] {{ font-size: 20px !important; }}

.ui-brand {{ display: flex; align-items: center; gap: .65rem; margin-bottom: .2rem; }}
.ui-brand-name {{ font-size: 16px; font-weight: 650; letter-spacing: -.01em; color: var(--ui-text); }}
.ui-brand-sub {{ font-size: 12px; color: var(--ui-muted); }}

/* ---------- navigation ---------- */
[data-testid="stSidebarNav"] {{ padding-top: .35rem; }}
[data-testid="stSidebarNavItems"] {{ gap: 3px; }}
[data-testid="stSidebarNavLink"] {{
  border-radius: 9px; padding: .48rem .65rem !important;
  border-left: 2px solid transparent;
}}
[data-testid="stSidebarNavLink"]:hover {{ background: var(--ui-surface-2) !important; }}
[data-testid="stSidebarNavLink"][aria-current="page"] {{
  background: rgba(139,147,255,.10) !important;
  border-left-color: var(--ui-primary);
}}
[data-testid="stSidebarNavLink"] span {{
  color: var(--ui-muted) !important; font-size: 14px !important; font-weight: 500 !important;
  letter-spacing: -.005em;
}}
[data-testid="stSidebarNavLink"][aria-current="page"] span {{
  color: var(--ui-text) !important; font-weight: 600 !important;
}}
[data-testid="stSidebarNavLink"] span[role="img"] {{ display: none !important; }}
[data-testid="stSidebarNavSeparator"] {{ display: none !important; }}

/* ---------- bordered containers ---------- */
[data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"] {{
  background: var(--ui-surface) !important;
  border: 1px solid var(--ui-border) !important;
  border-radius: var(--ui-radius) !important;
  padding: 1.15rem 1.2rem !important;
}}

/* ---------- pills + segmented controls ---------- */
[data-testid="stButtonGroup"] {{ gap: .4rem; flex-wrap: wrap; margin-top: .4rem; }}
[data-testid="stButtonGroup"] button[role="radio"] {{
  background: var(--ui-surface) !important;
  border: 1px solid var(--ui-border) !important;
  border-radius: 999px !important;
  color: var(--ui-muted) !important;
  font-size: 13px !important; font-weight: 600 !important;
  padding: .38rem .8rem !important;
  min-height: 34px;
}}
[data-testid="stButtonGroup"] button[role="radio"]:hover {{
  border-color: var(--ui-border-strong) !important; color: var(--ui-text) !important;
}}
[data-testid="stButtonGroup"] button[role="radio"][aria-checked="true"] {{
  background: rgba(139,147,255,.14) !important;
  border-color: rgba(139,147,255,.45) !important;
  color: var(--ui-text) !important;
}}
[data-testid="stButtonGroup"] button[role="radio"] span[role="img"] {{ display: none !important; }}

/* ---------- progress + chat ---------- */
[data-testid="stProgress"] > div {{ background: #1B2234 !important; }}
[data-testid="stProgress"] > div > div {{ background: var(--ui-primary) !important; }}
[data-testid="stChatMessage"] {{
  background: var(--ui-surface) !important;
  border: 1px solid var(--ui-border) !important;
  border-radius: var(--ui-radius) !important;
  padding: .85rem 1rem !important;
}}
[data-testid="stChatInput"] {{
  background: var(--ui-surface) !important;
  border: 1px solid var(--ui-border) !important;
  border-radius: var(--ui-radius) !important;
}}
[data-testid="stChatInput"]:focus-within {{ border-color: var(--ui-primary) !important; }}
[data-testid="stPageLink"] a {{
  display: inline-flex; align-items: center; gap: .4rem;
  color: var(--ui-primary) !important; font-weight: 600; font-size: 14px;
  border: 1px solid var(--ui-border); background: var(--ui-surface);
  border-radius: 9px; padding: .5rem .85rem;
}}
[data-testid="stPageLink"] a:hover {{ border-color: var(--ui-primary); text-decoration: none; }}
[data-testid="stPageLink"] a span[role="img"] {{ display: none !important; }}

/* ---------- meter ---------- */
.ui-meter-label {{
  display: flex; justify-content: space-between; gap: .75rem;
  font-size: 13px; color: var(--ui-muted); margin-top: .2rem;
}}

/* ---------- mobile ---------- */
@media (max-width: 900px) {{
  .block-container, [data-testid="stMainBlockContainer"] {{
    padding-left: 1rem !important; padding-right: 1rem !important; padding-top: 3.4rem !important;
  }}
  .ui-title {{ font-size: 26px !important; }}
  .ui-subtitle {{ font-size: 14px !important; }}
  .ui-header {{ flex-direction: column; gap: .6rem; }}
  .ui-header-badge {{ align-self: flex-start; }}
  .ui-metric-value {{ font-size: 24px !important; }}
}}
@media (max-width: 640px) {{
  .ui-title {{ font-size: 24px !important; }}
  .ui-empty {{ padding: 2rem 1rem; }}
  [data-testid="stHorizontalBlock"] {{ gap: .5rem; }}
}}
</style>
"""


def setup(
    page_title: str,
    *,
    icon: str | Path | None = None,
    layout: Literal["centered", "wide"] = "wide",
    sidebar_state: Literal["auto", "expanded", "collapsed"] = "auto",
) -> None:
    """Configure the page and inject the shared theme. Call once, first."""
    icon_value: str | None = None
    if icon is not None:
        if isinstance(icon, Path):
            icon_value = str(icon) if icon.exists() else None
        else:
            icon_value = icon
    st.set_page_config(
        page_title=page_title,
        page_icon=icon_value,
        layout=layout,
        initial_sidebar_state=sidebar_state,
    )
    st.markdown(CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------
def sidebar_brand(name: str, subtitle: str = "Data & AI portfolio") -> None:
    """Brand block for the top of a sidebar."""
    st.markdown(
        f'<div class="ui-brand">{mark(32)}'
        f'<div><div class="ui-brand-name">{name}</div>'
        f'<div class="ui-brand-sub">{subtitle}</div></div></div>',
        unsafe_allow_html=True,
    )


def page_header(
    title: str,
    subtitle: str = "",
    *,
    eyebrow: str = "",
    badge: str = "",
    badge_tone: str = "neutral",
    icon_name: str = "sparkles",
    show_mark: bool = True,
) -> None:
    """Page title block with the shared mark and an optional status pill."""
    badge_html = ""
    if badge:
        badge_html = f'<span class="ui-header-badge {badge_tone}">{svg("info", 13)}{badge}</span>'
    eyebrow_html = f'<div class="ui-eyebrow">{eyebrow}</div>' if eyebrow else ""
    mark_html = (
        mark(42)
        if show_mark
        else (f'<span class="ui-empty-icon" style="margin:0">{svg(icon_name, 20)}</span>')
    )
    st.markdown(
        f'<div class="ui-header"><div class="ui-header-main">{mark_html}'
        f'<div>{eyebrow_html}<h1 class="ui-title">{title}</h1>'
        f'<p class="ui-subtitle">{subtitle}</p></div></div>{badge_html}</div>',
        unsafe_allow_html=True,
    )


def section(title: str, description: str = "") -> None:
    desc = f"<p>{description}</p>" if description else ""
    st.markdown(
        f'<div class="ui-section"><h2>{title}</h2>{desc}</div>',
        unsafe_allow_html=True,
    )


def empty_state(title: str, body: str = "", *, hint: str = "", icon_name: str = "sparkles") -> None:
    hint_html = f'<div class="ui-empty-hint">{hint}</div>' if hint else ""
    st.markdown(
        f'<div class="ui-empty"><span class="ui-empty-icon">{svg(icon_name, 22)}</span>'
        f'<div class="ui-empty-title">{title}</div>'
        f'<div class="ui-empty-body">{body}</div>{hint_html}</div>',
        unsafe_allow_html=True,
    )


def error_state(
    message: str,
    *,
    title: str = "Something went wrong",
    hint: str = "Try again in a moment.",
) -> None:
    hint_html = f'<p class="ui-error-hint">{hint}</p>' if hint else ""
    st.markdown(
        f'<div class="ui-error"><span class="ui-error-icon">{svg("alert", 20)}</span>'
        f'<div><p class="ui-error-title">{title}</p>'
        f'<p class="ui-error-body">{message}</p>{hint_html}</div></div>',
        unsafe_allow_html=True,
    )


def _metric_html(
    label: str,
    value: str,
    delta: float | None = None,
    suffix: str = "",
    good_direction: str | None = None,
    caption: str = "",
) -> str:
    delta_html = ""
    if delta is not None:
        tone = "neutral"
        if good_direction in ("up", "down") and delta != 0:
            rising = delta > 0
            tone = "good" if (rising == (good_direction == "up")) else "bad"
        arrow = "arrow-up" if delta > 0 else "arrow-down"
        delta_html = (
            f'<div class="ui-metric-delta {tone}">{svg(arrow, 13)}{delta:+.1f}{suffix}</div>'
        )
    caption_html = f'<div class="ui-metric-caption">{caption}</div>' if caption else ""
    return (
        f'<div class="ui-metric"><div class="ui-metric-label">{label}</div>'
        f'<div class="ui-metric-value">{value}</div>{delta_html}{caption_html}</div>'
    )


def metric_card(
    label: str,
    value: str,
    *,
    delta: float | None = None,
    suffix: str = "",
    good_direction: str | None = None,
    caption: str = "",
) -> None:
    """Metric card whose delta colour reflects whether the change is good.

    good_direction="up"  -> an increase is good (success/green)
    good_direction="down"-> an increase is bad  (danger/red)
    good_direction=None  -> neutral (grey) regardless of sign
    """
    st.markdown(
        _metric_html(label, value, delta, suffix, good_direction, caption),
        unsafe_allow_html=True,
    )


def metric_grid(items: list[dict]) -> None:
    """Responsive KPI grid: 4 across on desktop, 2x2 on narrow screens.

    Each item accepts: label, value, delta, suffix, good_direction, caption.
    """
    cards = "".join(
        _metric_html(
            str(item.get("label", "")),
            str(item.get("value", "")),
            item.get("delta"),
            str(item.get("suffix", "")),
            item.get("good_direction"),
            str(item.get("caption", "")),
        )
        for item in items
    )
    st.markdown(f'<div class="ui-metric-grid">{cards}</div>', unsafe_allow_html=True)


def badge(text: str, tone: str = "neutral") -> str:
    """Inline status pill (returns HTML for embedding in custom markup)."""
    return f'<span class="ui-header-badge {tone}">{text}</span>'


def style_fig(fig, height: int | None = None):
    """Apply the shared Plotly look. Returns the figure for chaining."""
    fig.update_layout(
        template=None,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, size=13, color="#C3CADB"),
        margin=dict(l=6, r=6, t=12, b=6),
        colorway=[PRIMARY, SUCCESS, WARNING, DANGER, "#67C7F0", "#C084FC"],
        hoverlabel=dict(
            bgcolor=SURFACE_2,
            bordercolor=BORDER,
            font=dict(color=TEXT, size=13, family=FONT),
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=12),
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        xaxis=dict(
            gridcolor="#1E2535",
            zeroline=False,
            linecolor=BORDER,
            tickfont=dict(size=12),
            automargin=True,
        ),
        yaxis=dict(
            gridcolor="#1E2535",
            zeroline=False,
            linecolor=BORDER,
            tickfont=dict(size=12),
            automargin=True,
        ),
    )
    if height:
        fig.update_layout(height=height)
    return fig


def app_icon(assets_dir: Path) -> Path | None:
    """Return the shared PNG icon if it has been generated in the repo."""
    for name in ("icon.png", "app_icon.png"):
        candidate = assets_dir / name
        if candidate.exists():
            return candidate
    return None


def meter(value: float, *, tone: str = "primary", caption: str = "") -> None:
    """Horizontal probability meter with an optional caption below it."""
    pct = max(0.0, min(1.0, float(value))) * 100
    colour = {
        "primary": PRIMARY,
        "success": SUCCESS,
        "warning": WARNING,
        "danger": DANGER,
    }.get(tone, PRIMARY)
    caption_html = f'<div class="ui-meter-label"><span>{caption}</span></div>' if caption else ""
    st.markdown(
        f'<div class="ui-meter"><span style="width:{pct:.1f}%;background:{colour}"></span></div>'
        f"{caption_html}",
        unsafe_allow_html=True,
    )
