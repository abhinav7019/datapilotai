"""
DataPilot AI - single file (analysis + Power BI style dashboard + 3D look)
==========================================================================
Install once (inside your .venv):
    python -m pip install -r requirements.txt

Run:
    python -m streamlit run app.py --server.address localhost

Accounts: people register and log in; every project, chat, report and file is private to its owner.

Database (see datapilot_db.py and DEPLOY.md):
    SQLite  (default, no install)  -> datapilot.db + datapilot_storage/ next to app.py
    MySQL   (set DATAPILOT_DB=mysql and the MYSQL_* variables)
Files (datasets, original uploads, reports) are kept on disk, or inside the database with
    DATAPILOT_STORAGE=db  (for hosts whose disk is wiped on restart).
"""

import hashlib
import inspect
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
import warnings
from contextlib import contextmanager
from datetime import datetime, timedelta
from html import escape as esc
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

warnings.filterwarnings("ignore")
st.set_page_config(page_title="DataPilot AI", page_icon="📊", layout="wide")

# Hosting: values from .streamlit/secrets.toml (or the host's secret manager) become settings.
try:
    for _k in ("DATAPILOT_DB", "DATAPILOT_HOME", "DATAPILOT_STORAGE", "DATAPILOT_CLAIM_LEGACY",
               "MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"):
        if _k in st.secrets and not os.environ.get(_k):
            os.environ[_k] = str(st.secrets[_k])
except Exception:
    pass                                                  # no secrets file: environment variables only
import datapilot_db as dpdb                               # noqa: E402
import datapilot_tools as tools                           # noqa: E402
import datapilot_fx as fx                                 # noqa: E402
import datapilot_flex as flex                             # noqa: E402
import streamlit.components.v1 as components             # noqa: E402

dpdb.configure()


def _stretch(fn):
    return {"width": "stretch"} if "width" in inspect.signature(fn).parameters \
        else {"use_container_width": True}


W_BTN = _stretch(st.button)
W_DL = _stretch(st.download_button)
W_DF = _stretch(st.dataframe)
W_ED = _stretch(st.data_editor)
W_PLOT = _stretch(st.plotly_chart)
_STRETCH = W_PLOT


# ======================================================================
# 3D look for the WHOLE app (tabs, inputs, buttons, tables, cards)
# ======================================================================
# ----------------------------------------------------------------------
# Theme engine: presets + custom background / accent colours
# ----------------------------------------------------------------------
THEMES = {
    "Midnight Blue": dict(bg="#0a1024", accent="#00b4d8", classic=True),
    "Ocean Teal": dict(bg="#041f26", accent="#14c4b4"),
    "Purple Night": dict(bg="#150d2e", accent="#a06bff"),
    "Sunset": dict(bg="#2a0f1a", accent="#ff7a59"),
    "Forest": dict(bg="#0b1f14", accent="#3ddc84"),
    "Charcoal": dict(bg="#16181d", accent="#8ab4ff"),
    "Pure Black": dict(bg="#000000", accent="#00e5ff"),
    "Light Blue": dict(bg="#f3f6fb", accent="#2563eb"),
    "Light Warm": dict(bg="#fbf6ee", accent="#e07a1f"),
    "Flex Dark": dict(bg=flex.FLEX_DARK["bg"], accent=flex.FLEX_DARK["accent"]),
    "Flex Light": dict(bg=flex.FLEX_LIGHT["bg"], accent=flex.FLEX_LIGHT["accent"]),
    "Custom": None,
}


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v))) for v in c)


def _mix(a, b, t):
    """Blend colour a towards colour b by fraction t (0 = a, 1 = b)."""
    return _hex([x + (y - x) * t for x, y in zip(_rgb(a), _rgb(b))])


def _lum(h):
    r, g, b = _rgb(h)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def _rel_lum(h):
    def f(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(h)
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contrast(a, b):
    la, lb = _rel_lum(a), _rel_lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _best_ink(bg):
    """White or near-black text, whichever is easier to read on this colour."""
    return "#ffffff" if _contrast("#ffffff", bg) >= _contrast("#06121a", bg) else "#06121a"


def build_theme(name, bg, accent, solid=False):
    """Turn (preset or custom bg + accent) into every colour the page needs."""
    p = THEMES.get(name)
    if p:
        bg, accent = p["bg"], p["accent"]
    try:
        _ = (_rgb(bg), _rgb(accent))          # validate only (a bare expression would be shown on the page)
    except Exception:
        bg, accent = "#0a1024", "#00b4d8"
    dark = _lum(bg) < 0.5
    if dark:
        ink = "#e8ecff"
        t = {"ink": ink, "soft": _mix(ink, bg, .45), "panel": _mix(bg, "#ffffff", .09),
             "panel2": _mix(bg, "#ffffff", .16), "edge": _mix(bg, "#000000", .55),
             "edge2": _mix(bg, "#000000", .7), "inp": _mix(bg, "#ffffff", .05),
             "btn1": _mix(accent, bg, .55), "btn2": _mix(accent, bg, .75),
             "tab1": _mix(bg, "#ffffff", .16), "tab2": _mix(bg, "#ffffff", .09),
             "shadow": "#0008", "shadow-lg": "#000a", "shadow-in": "#000b",
             "line": "#ffffff22", "hi": "#ffffff33",
             "tshadow": f"0 2px 0 #0006, 0 8px 24px {accent}55",
             "glow1": _mix(bg, accent, .2), "glow2": _mix(bg, accent, .3),
             "hero": f"linear-gradient(135deg, {_mix(accent, bg, .55)}, {_mix(bg, '#000000', .15)} 60%, "
                     f"{_mix(accent, bg, .7)})"}
        if p and p.get("classic"):      # the original look, exactly
            t.update({"soft": "#9fb3ff", "panel": "#16224f", "panel2": "#1d2b5e", "edge": "#0a1230",
                      "edge2": "#08102a", "inp": "#0e1740", "btn1": "#2c43a8", "btn2": "#1a2a6c",
                      "tab1": "#26388a", "tab2": "#16224f", "glow1": "#1b2a5a", "glow2": "#0f4c5c",
                      "hero": "linear-gradient(135deg, #2a43a0, #0e1a45 60%, #0f4c5c)"})
    else:
        t = {"ink": "#1b2440", "soft": "#5b6785", "panel": "#ffffff", "panel2": _mix(bg, "#000000", .04),
             "edge": _mix(bg, "#000000", .14), "edge2": _mix(bg, "#000000", .22), "inp": "#ffffff",
             "btn1": _mix(accent, "#000000", .2), "btn2": _mix(accent, "#000000", .4),
             "tab1": "#ffffff", "tab2": _mix(bg, "#000000", .04),
             "shadow": "#1b244026", "shadow-lg": "#1b244033", "shadow-in": "#1b244022",
             "line": "#1b244022", "hi": "#ffffffaa", "tshadow": "none",
             "glow1": _mix(bg, accent, .12), "glow2": _mix(bg, accent, .06),
             "hero": f"linear-gradient(135deg, {accent}, {_mix(accent, '#000000', .4)})"}
    t.update({"accent": accent, "acc1": _mix(accent, "#ffffff", .15), "acc2": _mix(accent, "#000000", .25),
              "btn-ink": _best_ink(t["btn1"]),
              "hero-ink": "#ffffff", "bg": bg})
    t["on-acc"] = _best_ink(_mix(t["acc1"], t["acc2"], .5))
    _r, _g, _b = _rgb(t["panel"])
    t["glass"] = f"rgba({_r},{_g},{_b},{.72 if dark else .8})"
    t["page"] = bg if solid else (f"radial-gradient(1200px 600px at 10% -10%, {t['glow1']} 0%, transparent 60%), "
                                  f"radial-gradient(900px 500px at 100% 0%, {t['glow2']} 0%, transparent 55%), {bg}")
    if name in ("Flex Dark", "Flex Light"):          # the portfolio-style palette (see datapilot_flex.py)
        t.update(flex.FLEX_VARS[dark])
        t["page"] = bg
    t["dark"] = dark
    return t


def theme_cfg():
    """Theme choice currently on screen (live widgets first, then the saved settings)."""
    s = S()
    ss = st.session_state
    cfg = dict(theme_name=ss.get("th_name", s["theme_name"]), theme_bg=ss.get("th_bg", s["theme_bg"]),
                theme_accent=ss.get("th_accent", s["theme_accent"]),
                theme_solid=bool(ss.get("th_solid", s["theme_solid"])),
                look=ss.get("th_look", s.get("look", "Flex")),
                flex_dark=bool(ss.get("flex_dark", s.get("flex_dark", True))),
                bg3d=ss.get("th_bg3d", s.get("bg3d", fx.DEFAULT_BG)),
                fx=bool(ss.get("th_fx", s.get("fx", True))))
    if cfg["look"] == "Flex":                         # Flex has its own two palettes: dark charcoal / light cream
        cfg["theme_name"] = "Flex Dark" if cfg["flex_dark"] else "Flex Light"
        cfg["theme_solid"] = True
    return cfg


def current_theme():
    c = theme_cfg()
    return build_theme(c["theme_name"], c["theme_bg"], c["theme_accent"], c["theme_solid"])


def default_template():
    """Chart style that matches the page, unless the user chose another style in Settings."""
    t = S()["template"]
    if t in ("plotly_dark", "plotly_white"):
        return "plotly_dark" if current_theme()["dark"] else "plotly_white"
    return t


STATIC_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@400;600;800&display=swap');
html, body, .stApp, .stApp * { font-family: 'Sora', sans-serif; }
.stApp { background: var(--page); }
.stApp, .stApp p, .stApp label, .stApp li, .stApp span, .stApp h1, .stApp h2, .stApp h3,
.stApp [data-testid="stMarkdownContainer"], .stApp [data-testid="stCaptionContainer"] { color: var(--ink); }
.stApp [data-testid="stCaptionContainer"] { color: var(--soft); }
header[data-testid="stHeader"] { background: transparent; }
[data-testid="stSidebar"] { background: var(--panel); border-right: 1px solid var(--line); }
.block-container { padding-top: 1.5rem; max-width: 1400px; }
h1, h2, h3 { font-weight: 800 !important; letter-spacing: -0.02em; text-shadow: var(--tshadow); }

/* keep Streamlit's own icon font (otherwise arrows show as words) */
.stApp [data-testid="stIconMaterial"], .stApp .material-symbols-rounded {
  font-family: 'Material Symbols Rounded' !important; }
@keyframes floaty { 0%,100% { transform: rotateX(5deg) rotateY(-3deg) translateY(0); }
  50% { transform: rotateX(5deg) rotateY(-3deg) translateY(-6px); } }
/* hero banner */
.hero { perspective: 900px; margin: 4px 0 22px; }
.hero-in { padding: 26px 32px; border-radius: 22px; background: var(--hero);
  transform: rotateX(5deg) rotateY(-3deg); border: 1px solid var(--line);
  animation: floaty 6s ease-in-out infinite;
  box-shadow: 0 1px 0 var(--hi) inset, 0 8px 0 var(--edge), 0 18px 0 var(--edge2), 0 44px 60px var(--shadow-lg); }
.hero-in h1 { margin: 0; font-size: 2.6rem; transform: translateZ(40px); color: var(--hero-ink) !important; }
.hero-in p { margin: 6px 0 0; color: #ffffffcc !important; }

/* tabs as raised keys */
[data-baseweb="tab-list"] { gap: 10px; padding: 6px 0 16px; flex-wrap: wrap; }
button[data-baseweb="tab"] { height: auto; padding: 10px 16px; border-radius: 12px;
  background: linear-gradient(var(--tab1), var(--tab2)); border: 1px solid var(--line);
  box-shadow: 0 5px 0 var(--edge), 0 12px 18px var(--shadow); transition: all .15s ease; }
button[data-baseweb="tab"]:hover { transform: translateY(-2px); }
button[data-baseweb="tab"][aria-selected="true"] {
  background: linear-gradient(var(--acc1), var(--acc2)); transform: translateY(3px);
  box-shadow: 0 2px 0 var(--edge), 0 6px 10px var(--shadow); }
button[data-baseweb="tab"][aria-selected="true"] p { color: var(--on-acc) !important; }
[data-baseweb="tab-highlight"], [data-baseweb="tab-border"] { display: none; }

/* inputs pressed into the surface */
[data-baseweb="select"] > div, [data-baseweb="input"], [data-baseweb="textarea"] {
  background: var(--inp) !important; border-radius: 12px !important;
  border: 1px solid var(--line) !important;
  box-shadow: inset 0 3px 7px var(--shadow-in), 0 1px 0 var(--hi); }
input, textarea { color: var(--ink) !important; }
[data-baseweb="popover"] ul, [data-baseweb="popover"] [role="listbox"] { background: var(--panel) !important; }
[data-baseweb="popover"] li, [data-baseweb="popover"] li * { color: var(--ink) !important; }
[data-testid="stFileUploader"] section { background: var(--inp); border-radius: 16px;
  box-shadow: inset 0 4px 10px var(--shadow-in); border: 1px dashed var(--accent); }

/* raised buttons */
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {
  border-radius: 12px; background: linear-gradient(var(--btn1), var(--btn2));
  border: 1px solid var(--line); box-shadow: 0 5px 0 var(--edge), 0 12px 18px var(--shadow);
  transition: all .12s; }
.stButton > button *, .stDownloadButton > button *, [data-testid="stFormSubmitButton"] > button * {
  color: var(--btn-ink) !important; }
.stButton > button:hover, .stDownloadButton > button:hover { transform: translateY(-2px); }
.stButton > button:active, .stDownloadButton > button:active {
  transform: translateY(4px); box-shadow: 0 1px 0 var(--edge); }

/* raised panels */
[data-testid="stMetric"] { background: linear-gradient(145deg, var(--panel2), var(--panel));
  border-radius: 16px; padding: 12px 16px; border: 1px solid var(--line);
  transform: perspective(700px) rotateX(5deg);
  box-shadow: 0 5px 0 var(--edge), 0 16px 26px var(--shadow-lg); }
[data-testid="stMetricValue"] { text-shadow: 0 3px 0 var(--shadow); }
[data-testid="stDataFrame"], [data-testid="stDataEditor"] { border-radius: 16px; overflow: hidden;
  box-shadow: 0 6px 0 var(--edge), 0 22px 36px var(--shadow-lg); }
[data-testid="stAlert"] { border-radius: 14px; box-shadow: 0 5px 0 var(--edge), 0 12px 20px var(--shadow); }
[data-testid="stExpander"] { border-radius: 14px; border: 1px solid var(--line);
  background: var(--panel); box-shadow: 0 5px 0 var(--edge); }
[data-testid="stPlotlyChart"] { border-radius: 18px; padding: 8px;
  background: linear-gradient(160deg, var(--panel2), var(--panel)); border: 1px solid var(--line);
  box-shadow: 0 1px 0 var(--hi) inset, 0 6px 0 var(--edge), 0 24px 40px var(--shadow-lg);
  transition: transform .25s ease; }
[data-testid="stPlotlyChart"]:hover { transform: translateY(-4px); }

/* 3D KPI cards */
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 22px; perspective: 1000px; margin: 8px 0 26px; }
.kpi { padding: 18px 20px; border-radius: 18px; border: 1px solid var(--line);
  background: linear-gradient(145deg, var(--panel2), var(--panel));
  box-shadow: 0 1px 0 var(--hi) inset, 0 -4px 10px var(--shadow-in) inset,
              0 6px 0 var(--edge), 0 14px 0 var(--edge2), 0 28px 40px var(--shadow-lg);
  transform: rotateX(6deg); transform-style: preserve-3d;
  transition: transform .25s ease, box-shadow .25s ease; }
.kpi:hover { transform: rotateX(0deg) translateY(-8px) scale(1.02);
  box-shadow: 0 8px 0 var(--edge), 0 18px 0 var(--edge2), 0 36px 50px var(--shadow-lg); }
.kpi .lbl { font-size: .78rem; color: var(--soft); }
.kpi .val { font-size: 2rem; font-weight: 800; margin: 2px 0 4px;
  transform: translateZ(30px); text-shadow: 0 3px 0 var(--shadow); }
.kpi .up { color: #1fbf86; font-weight: 600; font-size: .85rem; }
.kpi .down { color: #ff6b81; font-weight: 600; font-size: .85rem; }
.kpi .flat { color: var(--soft); font-size: .85rem; }
.kpi:nth-child(1) { border-top: 4px solid #00b4d8; }
.kpi:nth-child(2) { border-top: 4px solid #feca57; }
.kpi:nth-child(3) { border-top: 4px solid #f368e0; }
.kpi:nth-child(4) { border-top: 4px solid #38e8a8; }
.kpi:nth-child(5) { border-top: 4px solid #ff6b6b; }
.kpi:nth-child(6) { border-top: 4px solid #a29bfe; }
@media (max-width: 768px) {
  .block-container { padding: 1rem .6rem; }
  .hero-in { padding: 16px 18px; transform: none; animation: none; }
  .hero-in h1 { font-size: 1.7rem; transform: none; }
  .kpi, [data-testid="stMetric"] { transform: none; }
  .kpi-grid { grid-template-columns: repeat(2, 1fr); gap: 12px; }
  .kpi .val { font-size: 1.5rem; transform: none; }
  button[data-baseweb="tab"] { padding: 8px 10px; font-size: .8rem; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
"""

CHIP_CSS = """
/* data status chips */
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 2px 0 14px; }
.chip { padding: 6px 12px; border-radius: 999px; font-size: .82rem; background: var(--panel);
  border: 1px solid var(--line); color: var(--ink); }
"""

FX_CSS = """
/* layers: 3D background canvas sits behind the app, content above it */
[data-testid="stAppViewContainer"] { position: relative; z-index: 1; }
[data-testid="stAppViewContainer"], [data-testid="stMain"] { background: transparent !important; }
[data-testid="stElementContainer"]:has(iframe[height="0"]), .element-container:has(iframe[height="0"]) {
  position: absolute; width: 0; height: 0; overflow: hidden; margin: 0; padding: 0; }
.react-aria-SelectionIndicator { background-color: var(--accent) !important; }
[data-testid="stToggle"] [data-selected="true"] > div, label[data-selected="true"] > div:not(:first-child) { }
/* light that follows the mouse on tilting cards */
.kpi, .feat, [data-testid="stMetric"] { position: relative; }
.kpi::after, .feat::after, [data-testid="stMetric"]::after { content: ""; position: absolute; inset: 0;
  border-radius: inherit; pointer-events: none; opacity: 0; transition: opacity .25s;
  background: radial-gradient(260px circle at var(--mx, 50%) var(--my, 0%), #ffffff2a, transparent 62%); }
.kpi:hover::after, .feat:hover::after, [data-testid="stMetric"]:hover::after { opacity: 1; }
/* feature cards (login page) */
.feat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 14px; margin: 4px 0 18px; }
.feat { background: var(--glass); border: 1px solid var(--line); border-radius: 18px; padding: 16px 18px;
  box-shadow: 0 10px 28px var(--shadow); backdrop-filter: blur(10px); }
.feat .ic { font-size: 1.7rem; display: block; margin-bottom: 6px; }
.feat b { display: block; font-size: 1.02rem; margin-bottom: 4px; color: var(--ink); }
.feat .t { font-size: .86rem; color: var(--soft); line-height: 1.45; }
@keyframes heroShift { 0% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } 100% { background-position: 0% 50%; } }
@keyframes cubeSpin { from { transform: rotateX(-24deg) rotateY(0deg); } to { transform: rotateX(-24deg) rotateY(360deg); } }
@keyframes dpUp { from { opacity: 0; transform: translateY(18px); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) { .cube, .hero-in, .kpi, [data-testid="stPlotlyChart"] { animation: none !important; } }
"""

MODERN_CSS = """
/* ===== Modern look: flat glass, soft shadows, pill tabs ===== */
.hero { perspective: none; }
.hero-in { transform: none !important; animation: heroShift 16s ease-in-out infinite !important;
  background-size: 220% 220% !important; border-radius: 26px; padding: 30px 38px;
  position: relative; overflow: hidden; box-shadow: 0 24px 60px var(--shadow-lg); }
.cube-wrap { position: absolute; right: 56px; top: 50%; width: 90px; height: 90px; margin-top: -45px;
  perspective: 700px; pointer-events: none; }
.cube { position: relative; width: 90px; height: 90px; transform-style: preserve-3d; animation: cubeSpin 18s linear infinite; }
.cube i { position: absolute; inset: 0; border: 2px solid #ffffffb0; border-radius: 10px;
  background: linear-gradient(135deg, #ffffff33, #ffffff0a); }
.cube i:nth-child(1) { transform: translateZ(45px); }
.cube i:nth-child(2) { transform: rotateY(180deg) translateZ(45px); }
.cube i:nth-child(3) { transform: rotateY(90deg) translateZ(45px); }
.cube i:nth-child(4) { transform: rotateY(-90deg) translateZ(45px); }
.cube i:nth-child(5) { transform: rotateX(90deg) translateZ(45px); }
.cube i:nth-child(6) { transform: rotateX(-90deg) translateZ(45px); }
@media (max-width: 760px) { .cube-wrap { display: none; } }
.kpi, [data-testid="stMetric"], [data-testid="stExpander"], [data-baseweb="tab-list"] {
  background: var(--glass) !important; backdrop-filter: blur(12px) saturate(1.2); }
[data-testid="stSidebar"] > div:first-child { background: var(--glass); backdrop-filter: blur(16px); }
.kpi, [data-testid="stPlotlyChart"], [data-testid="stMetric"], [data-testid="stDataFrame"], [data-testid="stExpander"] {
  animation: dpUp .6s cubic-bezier(.2, .7, .2, 1) backwards; }
.hero-in::before { content: ""; position: absolute; inset: 0; pointer-events: none;
  background: radial-gradient(560px 240px at 88% -30%, #ffffff44, transparent 62%); }
.hero-in h1 { transform: none !important; font-size: 2.35rem; text-shadow: none; }
h1, h2, h3 { text-shadow: none; }
[data-testid="stSidebar"] { background: linear-gradient(180deg, var(--panel), var(--bg)); }

[data-baseweb="tab-list"] { gap: 4px; padding: 6px; margin-bottom: 12px; background: var(--panel);
  border: 1px solid var(--line); border-radius: 18px; }
button[data-baseweb="tab"] { background: transparent; border: 0; box-shadow: none; border-radius: 12px;
  padding: 8px 14px; }
button[data-baseweb="tab"]:hover { transform: none; background: var(--panel2); }
button[data-baseweb="tab"][aria-selected="true"] { transform: none;
  background: linear-gradient(135deg, var(--acc1), var(--acc2)); box-shadow: 0 8px 20px var(--shadow); }
[role="tablist"] { gap: 4px; padding: 6px; margin-bottom: 12px; background: var(--panel); border: 1px solid var(--line); border-radius: 18px; }
[role="tab"] { border-radius: 12px; padding: 8px 14px; }
[role="tab"][aria-selected="true"] { background: linear-gradient(135deg, var(--acc1), var(--acc2)); box-shadow: 0 8px 20px var(--shadow); }

.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {
  box-shadow: 0 6px 16px var(--shadow); }
.stButton > button:hover, .stDownloadButton > button:hover { transform: translateY(-1px);
  box-shadow: 0 10px 22px var(--shadow-lg); }
.stButton > button:active, .stDownloadButton > button:active { transform: translateY(0);
  box-shadow: 0 2px 6px var(--shadow); }
[data-baseweb="select"] > div, [data-baseweb="input"], [data-baseweb="textarea"] { box-shadow: none; }

.kpi-grid { perspective: none; gap: 18px; }
.kpi { transform: none; border-radius: 20px; box-shadow: 0 10px 30px var(--shadow); }
.kpi:hover { transform: translateY(-4px); box-shadow: 0 18px 40px var(--shadow-lg); }
.kpi .val { transform: none; text-shadow: none; }
[data-testid="stMetric"] { transform: none; border-radius: 18px; box-shadow: 0 8px 24px var(--shadow); }
[data-testid="stMetricValue"] { text-shadow: none; }
[data-testid="stDataFrame"], [data-testid="stDataEditor"] { box-shadow: 0 8px 24px var(--shadow); }
[data-testid="stAlert"] { box-shadow: none; border: 1px solid var(--line); }
[data-testid="stExpander"] { box-shadow: 0 6px 20px var(--shadow); border-radius: 16px; }
[data-testid="stPlotlyChart"] { box-shadow: 0 10px 30px var(--shadow); }
[data-testid="stPlotlyChart"]:hover { transform: translateY(-2px); box-shadow: 0 16px 40px var(--shadow-lg); }
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-thumb { background: var(--line); border-radius: 10px; }
"""


def apply_theme():
    t = current_theme()
    root = ":root{color-scheme:" + ("dark" if t["dark"] else "light") + ";" + \
        ";".join(f"--{k}:{v}" for k, v in t.items() if k != "dark") + "}"
    look = theme_cfg()["look"]
    css = root + STATIC_CSS + CHIP_CSS + FX_CSS + (MODERN_CSS if look == "Modern" else "") + \
        (flex.FLEX_CSS if look == "Flex" else "")
    if look == "Flex":
        css = flex.FONT_IMPORT + css
    st.markdown("<style>" + css + "</style>", unsafe_allow_html=True)
    c = theme_cfg()
    html = fx.fx_html(c["bg3d"], t["accent"], c["fx"], t["dark"],
                      (0.5 if t["dark"] else 0.35) if look == "Flex" else None)       # 3D background + effects
    if hasattr(st, "iframe"):                  # newer Streamlit: st.components.v1.html is being retired
        st.iframe(html, height=1)
    else:
        components.html(html, height=0)


def hero_html(sub):
    """Banner with a spinning 3D cube (the cube is shown by the Modern look)."""
    return ('<div class="hero"><div class="hero-in"><div class="cube-wrap"><div class="cube">' + "<i></i>" * 6 +
            f'</div></div><h1>📊 DataPilot AI</h1><p>{sub}</p></div></div>')



# ======================================================================
# Preparing the data (automatic cleaning)
# ======================================================================
def prepare(df):
    """Tidy the data and return (clean_df, list_of_cleaning_notes)."""
    notes = []
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    df = df.replace(r"^\s*$", np.nan, regex=True)

    before = df.shape
    df = df.dropna(how="all").dropna(axis=1, how="all")
    if df.shape != before:
        notes.append("Removed fully empty rows/columns.")

    for col in df.columns:
        if df[col].dtype == object or pd.api.types.is_string_dtype(df[col]):   # text (pandas 2 and 3)
            df[col] = df[col].apply(lambda v: v.strip() if isinstance(v, str) else v)
            nums = pd.to_numeric(df[col], errors="coerce")
            filled = df[col].notna().sum()
            if filled and nums.notna().sum() == filled:
                df[col] = nums
                continue
            looks_date = any(k in col.lower() for k in ("date", "time", "month", "day"))
            sample = df[col].dropna().astype(str).head(20)
            if looks_date or sample.str.contains(r"[-/]\d").mean() > 0.8:
                parsed = pd.to_datetime(df[col], errors="coerce")
                if filled and parsed.notna().sum() >= 0.9 * filled:
                    df[col] = parsed

    dups = int(df.duplicated().sum())
    if dups:
        df = df.drop_duplicates()
        notes.append(f"Removed {dups} duplicate rows.")

    return df.reset_index(drop=True), notes


prepare_cached = st.cache_data(show_spinner=False, max_entries=8)(prepare)   # faster reruns

MAX_MB = 50                    # biggest file we accept
MAX_ROWS = 200_000             # rows kept for analysis (keeps the app fast)
MISSING_MODES = ["Keep as is", "Fill numbers with the average", "Fill numbers with the median",
                 "Fill empty cells with the previous value", "Remove rows with missing values"]


def handle_missing(df, mode):
    """Apply the user's choice for empty cells. Returns (df, notes)."""
    df, notes = df.copy(), []
    if mode == MISSING_MODES[0]:
        return df, notes
    before, rows = int(df.isna().sum().sum()), len(df)
    if mode in MISSING_MODES[1:3]:
        num = df.select_dtypes(include="number").columns
        for c in num:
            if df[c].isna().any():
                df[c] = df[c].fillna(df[c].mean() if mode == MISSING_MODES[1] else df[c].median())
        for c in df.columns:
            if c not in num and not pd.api.types.is_datetime64_any_dtype(df[c]) and df[c].isna().any():
                df[c] = df[c].fillna("Unknown")
        notes.append("Filled empty numbers with the " + ("average" if mode == MISSING_MODES[1] else "median")
                     + " and empty text with 'Unknown'.")
    elif mode == MISSING_MODES[3]:
        df = df.ffill().bfill()
        notes.append("Filled empty cells with the previous value in the same column.")
    else:
        df = df.dropna().reset_index(drop=True)
        notes.append(f"Removed {rows - len(df):,} rows that had missing values.")
    notes.append(f"Empty cells: {before:,} -> {int(df.isna().sum().sum()):,}.")
    return df, notes


def read_json_upload(up):
    text = up.getvalue().decode("utf-8-sig")
    try:
        data = json.loads(text)
    except ValueError:                       # maybe one JSON object per line
        return pd.read_json(io.StringIO(text), lines=True)
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
        data = lists[0] if lists else [data]
    return pd.json_normalize(data)


def read_sqlite_upload(up):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        f.write(up.getvalue())
        path = f.name
    try:
        con = sqlite3.connect(path)
        try:
            tables = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            if not tables:
                raise ValueError("No tables were found in this database file.")
            t = st.selectbox("Table", tables)
            return pd.read_sql_query('SELECT * FROM "' + t.replace('"', '""') + f'" LIMIT {MAX_ROWS}', con)
        finally:
            con.close()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def read_google_sheet(url):
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", url or "")
    if not m:
        raise ValueError("That does not look like a Google Sheets link.")
    gid = re.search(r"[#&?]gid=(\d+)", url)
    export = (f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv"
              + (f"&gid={gid.group(1)}" if gid else ""))
    r = requests.get(export, timeout=20)
    if r.status_code != 200 or "text/html" in r.headers.get("content-type", ""):
        raise ValueError("Could not open the sheet. Share it as 'Anyone with the link can view' and try again.")
    if len(r.content) > MAX_MB * 1024 * 1024:
        raise ValueError(f"The sheet is bigger than {MAX_MB} MB.")
    return pd.read_csv(io.BytesIO(r.content))


def split_columns(df):
    nums = df.select_dtypes(include="number").columns.tolist()
    dates = df.select_dtypes(include=["datetime", "datetimetz"]).columns.tolist()
    cats = [c for c in df.columns if c not in nums and c not in dates]
    cats = [c for c in cats if 1 < df[c].nunique() <= 30]
    return nums, dates, cats


# ======================================================================
# Automatic insights
# ======================================================================
def fmt(v):
    if isinstance(v, (int, np.integer)):
        return f"{v:,}"
    return f"{v:,.2f}"


def make_insights(df, measure, agg):
    nums, dates, cats = split_columns(df)
    out = []

    miss = df.isna().sum()
    miss = miss[miss > 0]
    if miss.empty:
        out.append("✅ No missing values - the data is complete.")
    else:
        worst = miss.sort_values(ascending=False).head(3)
        txt = ", ".join(f"**{c}** ({n} missing, {n / len(df):.0%})" for c, n in worst.items())
        out.append(f"⚠️ Missing values found in: {txt}.")

    for c in nums[:6]:
        s = df[c].dropna()
        if s.empty:
            continue
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        outliers = int(((s < q1 - 1.5 * iqr) | (s > q3 + 1.5 * iqr)).sum()) if iqr > 0 else 0
        line = (f"📈 **{c}**: average {fmt(s.mean())}, median {fmt(s.median())}, "
                f"range {fmt(s.min())} to {fmt(s.max())}")
        if outliers:
            line += f", {outliers} unusual value(s) (outliers)"
        out.append(line + ".")

    if measure:
        for c in cats[:3]:
            g = df.groupby(c)[measure].agg(agg).sort_values(ascending=False)
            if len(g) >= 2 and g.sum() != 0 and agg in ("sum", "count"):
                share = g.iloc[0] / g.sum()
                out.append(f"🏆 By **{c}**, the top {agg} of **{measure}** is **{g.index[0]}** "
                           f"({fmt(g.iloc[0])}, {share:.0%} of total); lowest is "
                           f"**{g.index[-1]}** ({fmt(g.iloc[-1])}).")
            elif len(g) >= 2:
                out.append(f"🏆 By **{c}**, highest {agg} of **{measure}** is **{g.index[0]}** "
                           f"({fmt(g.iloc[0])}); lowest is **{g.index[-1]}** ({fmt(g.iloc[-1])}).")

    if dates and measure:
        d = dates[0]
        t = df.dropna(subset=[d, measure]).sort_values(d)
        if len(t) >= 4:
            half = len(t) // 2
            first, second = t[measure].iloc[:half].mean(), t[measure].iloc[half:].mean()
            if first != 0:
                chg = (second - first) / abs(first)
                word = "increased" if chg > 0 else "decreased"
                out.append(f"🕒 Over time ({d}), average **{measure}** {word} by "
                           f"{abs(chg):.0%} from the first half to the second half.")

    if len(nums) >= 2:
        corr = df[nums].corr().abs()
        pairs = [(corr.loc[a, b], a, b) for i, a in enumerate(nums) for b in nums[i + 1:]]
        pairs = [p for p in pairs if not np.isnan(p[0])]
        if pairs:
            r, a, b = max(pairs)
            if r >= 0.5:
                sign = "positive" if df[a].corr(df[b]) > 0 else "negative"
                out.append(f"🔗 Strongest relationship: **{a}** and **{b}** "
                           f"({sign}, correlation {df[a].corr(df[b]):.2f}).")
            else:
                out.append("🔗 No strong relationships between the numeric columns.")
    return out


insights_cached = st.cache_data(show_spinner=False, max_entries=16)(make_insights)


# ======================================================================
# Reports
# ======================================================================
def build_excel(df, insights):
    out = io.BytesIO()
    nums = df.select_dtypes(include="number")
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        pd.DataFrame({"Insights": [i.replace("**", "") for i in insights]}).to_excel(
            xw, sheet_name="Insights", index=False)
        df.to_excel(xw, sheet_name="Data", index=False)
        if not nums.empty:
            nums.describe().T.to_excel(xw, sheet_name="Statistics")
            if nums.shape[1] > 1:
                nums.corr().to_excel(xw, sheet_name="Correlation")
        for ws in xw.book.worksheets:
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col[:200])
                ws.column_dimensions[col[0].column_letter].width = min(width + 2, 60)
    return out.getvalue()


# ======================================================================
# Optional AI (Ollama on your computer, or the Claude API online)
# ======================================================================
AI_ENGINES = ["Ollama (local, private)", "Claude API (online)"]
CLAUDE_MODEL = "claude-sonnet-5-5"
AI_CHART_TYPES = ["Column", "Bar (horizontal)", "Line", "Area", "Pie", "Donut", "Scatter", "Histogram", "Box"]
AI_SYSTEM = ("You are a clear, practical data analyst. Use only the data given. "
             "Do not invent numbers. Answer in simple language.")


def llm_chat(system, user, engine, api_key="", model=""):
    """Send one question to the chosen AI engine and return the text answer."""
    if engine.startswith("Claude"):
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise RuntimeError("Enter your Claude API key (or set the ANTHROPIC_API_KEY environment variable).")
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                   "content-type": "application/json"},
                          json={"model": model or CLAUDE_MODEL, "max_tokens": 1500, "system": system,
                                "messages": [{"role": "user", "content": user}]}, timeout=120)
        if r.status_code != 200:
            try:
                why = r.json().get("error", {}).get("message", "")
            except Exception:
                why = r.text[:200]
            raise RuntimeError(f"Claude API error {r.status_code}: {why}")
        return "".join(b.get("text", "") for b in r.json().get("content", []))
    tags = requests.get("http://localhost:11434/api/tags", timeout=3).json()
    models = [m["name"] for m in tags.get("models", [])]
    if not models:
        raise RuntimeError("Ollama has no models. Run: ollama pull llama3.2:3b")
    use = next((m for m in models if "llama3.2" in m), models[0])
    r = requests.post("http://localhost:11434/api/chat",
                      json={"model": use, "stream": False, "messages": [
                          {"role": "system", "content": system}, {"role": "user", "content": user}]},
                      timeout=300)
    r.raise_for_status()
    return r.json()["message"]["content"]


def ai_explain(df, insights, question, engine=AI_ENGINES[0], api_key="", model=""):
    context = (f"Columns: {list(df.columns)}\n"
               f"Statistics:\n{df.describe().round(2).to_string()}\n"
               f"Insights:\n" + "\n".join(insights) +
               f"\nSample rows:\n{df.head(8).to_csv(index=False)}")
    return llm_chat(AI_SYSTEM + "\n\n" + context, question, engine, api_key, model)


def parse_chart_json(text, df):
    """Turn the AI's JSON reply into a chart setting, checking every column really exists."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("The AI did not return a chart setting. Try rephrasing your request.")
    d = json.loads(m.group(0))
    cols = list(df.columns)
    nums = df.select_dtypes(include="number").columns.tolist()
    typ = d.get("type") if d.get("type") in AI_CHART_TYPES else "Column"
    x = d.get("x")
    if x not in cols:
        raise ValueError(f"The AI chose a column that does not exist ({x!r}). Try rephrasing.")
    y = d.get("y") if d.get("y") in nums else None
    agg = d.get("agg") if d.get("agg") in AGG_CHOICES else "sum"
    color = d.get("color") if d.get("color") in cols and d.get("color") != x else None
    if typ == "Histogram" and y is None and x in nums:
        y = x
    if y is None:                                  # no number asked for -> count the rows
        y, agg = "Number of records", "sum"
        if typ in ("Scatter", "Histogram", "Box"):
            typ = "Column"
    if typ == "Scatter" and x not in nums:
        typ = "Column"
    return dict(type=typ, x=x, y=y, z=y, color=color, agg=agg, topn=12, palette=S()["palette"],
                template=default_template(), title=str(d.get("title") or "")[:80], height=450, labels=False)


def ai_chart_cfg(df, question, engine, api_key="", model=""):
    system = ("You turn a question about a table into ONE chart setting. Reply with ONLY a JSON object "
              "and no other text, in this shape: "
              '{"type": one of ' + json.dumps(AI_CHART_TYPES) + ', "x": a column name, '
              '"y": a numeric column name or null, "agg": one of ["sum","mean","median","count","max","min"], '
              '"color": a column name or null, "title": a short title}. '
              "Use only these columns: " + json.dumps([str(c) for c in df.columns]) + ". "
              "Numeric columns: " + json.dumps(df.select_dtypes(include="number").columns.tolist()) + ".")
    return parse_chart_json(llm_chat(system, question, engine, api_key, model), df)


# ======================================================================
# Power BI style dashboard (KPI cards, editable charts, 3D charts)
# ======================================================================
PALETTES = {
    "Vivid": px.colors.qualitative.Vivid,
    "Bold": px.colors.qualitative.Bold,
    "Pastel": px.colors.qualitative.Pastel,
    "Ocean": ["#00b4d8", "#0077b6", "#90e0ef", "#48cae4", "#023e8a", "#ade8f6"],
    "Sunset": ["#ff6b6b", "#feca57", "#ff9f43", "#ee5a24", "#f368e0", "#a29bfe"],
    "Safe": px.colors.qualitative.Safe,
}
TEMPLATES = ["plotly_dark", "plotly_white", "ggplot2", "seaborn", "simple_white"]
TYPES_2D = ["Column", "Bar (horizontal)", "Stacked column", "Line", "Area", "Scatter",
            "Bubble", "Pie", "Donut", "Histogram", "Box", "Violin", "Heatmap",
            "Treemap", "Sunburst", "Funnel"]
TYPES_3D = ["3D scatter", "3D surface", "3D bar"]
AGGS = ["sum", "mean", "median", "count", "max", "min", "nunique"]


# ----------------------------------------------------------------------
# KPI helpers
# ----------------------------------------------------------------------
def short(v):
    if v is None or pd.isna(v):
        return "-"
    a = abs(v)
    for lim, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= lim:
            return f"{v / lim:,.2f}{suf}"
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"


def kpi_value(series, agg):
    return getattr(series.dropna(), agg)()


def kpi_cards(df, nums, dates):
    st.subheader("KPI cards")
    n = st.slider("Number of KPI cards", 1, 6,
                  min(int(S()["kpi_cards"]), max(1, len(nums) + 1)), key="kpi_n")
    cols = st.columns(n)
    spec = []
    for i, c in enumerate(cols):
        with c:
            opts = ["(row count)"] + nums
            col = st.selectbox(f"KPI {i + 1} column", opts,
                               index=min(i, len(opts) - 1), key=f"kpi_c{i}")
            agg = st.selectbox("Calculation", AGGS, index=0 if i % 2 == 0 else 1,
                               key=f"kpi_a{i}")
            spec.append((col, agg))

    sorted_df = df.sort_values(dates[0]) if dates else df
    half = len(sorted_df) // 2
    kp = []
    html = ['<div class="kpi-grid">']
    for col, agg in spec:
        if col == "(row count)":
            val, label = len(df), "Rows"
            delta = None
        else:
            val, label = kpi_value(df[col], agg), f"{agg.title()} of {col}"
            delta = None
            if dates and half >= 2:
                a = kpi_value(sorted_df[col].iloc[:half], agg)
                b = kpi_value(sorted_df[col].iloc[half:], agg)
                if a and not pd.isna(a):
                    delta = (b - a) / abs(a)
        if delta is None:
            d_html = '<div class="flat">no trend</div>'
        else:
            cls, arrow = ("up", "▲") if delta >= 0 else ("down", "▼")
            d_html = f'<div class="{cls}">{arrow} {abs(delta):.1%} vs first half</div>'
        kp.append(dict(label=label, value=short(val), delta=delta))
        html.append(f'<div class="kpi"><div class="lbl">{label}</div>'
                    f'<div class="val">{short(val)}</div>{d_html}</div>')
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)
    return kp


# ----------------------------------------------------------------------
# Chart builder
# ----------------------------------------------------------------------
def grouped(df, x, y, agg, color, topn):
    keys = [x] + ([color] if color and color != x else [])
    g = df.groupby(keys, dropna=True)[y].agg(agg).reset_index()
    order = g.groupby(x)[y].sum().sort_values(ascending=False).index[:topn]
    return g[g[x].isin(order)].sort_values(y, ascending=False)


def bar3d(df, x, y, series, agg, pal, topn):
    s = series or "_all"
    d = df.assign(_all="All") if not series else df
    p = d.pivot_table(index=x, columns=s, values=y, aggfunc=agg).fillna(0)
    p = p.loc[p.sum(axis=1).sort_values(ascending=False).index[:topn]]
    vx = [0, 0, 1, 1, 0, 0, 1, 1]
    vy = [0, 1, 1, 0, 0, 1, 1, 0]
    vz = [0, 0, 0, 0, 1, 1, 1, 1]
    ti = [7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2]
    tj = [3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3]
    tk = [0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6]
    X, Y, Z, I, J, K, C = [], [], [], [], [], [], []
    for r, _ in enumerate(p.index):
        for c, _ in enumerate(p.columns):
            h, o = float(p.iat[r, c]), len(X)
            X += [r + 0.15 + 0.7 * v for v in vx]
            Y += [c + 0.15 + 0.7 * v for v in vy]
            Z += [h * v for v in vz]
            I += [o + t for t in ti]
            J += [o + t for t in tj]
            K += [o + t for t in tk]
            C += [h] * 8
    fig = go.Figure(go.Mesh3d(x=X, y=Y, z=Z, i=I, j=J, k=K, intensity=C,
                              colorscale=[[0, pal[0]], [1, pal[min(3, len(pal) - 1)]]],
                              flatshading=True, showscale=True,
                              colorbar=dict(title=f"{agg} {y}")))
    fig.update_layout(scene=dict(
        xaxis=dict(tickvals=[i + .5 for i in range(len(p.index))],
                   ticktext=[str(v) for v in p.index], title=x),
        yaxis=dict(tickvals=[i + .5 for i in range(len(p.columns))],
                   ticktext=[str(v) for v in p.columns], title=series or ""),
        zaxis=dict(title=f"{agg} of {y}")))
    return fig


def make_fig(df, c):
    t, x, y, z, col = c["type"], c["x"], c["y"], c["z"], c["color"]
    agg, topn = c["agg"], c["topn"]
    pal = PALETTES[c["palette"]]
    kw = dict(template=c["template"], color_discrete_sequence=pal)
    lab = ".2s" if c["labels"] else False
    sample = df.sample(min(len(df), 5000), random_state=1)

    if t in ("Column", "Bar (horizontal)", "Stacked column", "Line", "Area", "Pie", "Donut",
             "Funnel", "Treemap", "Sunburst"):
        g = grouped(df, x, y, agg, col, topn)
        if t == "Column":
            fig = px.bar(g, x=x, y=y, color=col, barmode="group", text_auto=lab, **kw)
        elif t == "Stacked column":
            fig = px.bar(g, x=x, y=y, color=col or x, barmode="stack", text_auto=lab, **kw)
        elif t == "Bar (horizontal)":
            fig = px.bar(g.sort_values(y), x=y, y=x, color=col, orientation="h",
                         text_auto=lab, **kw)
        elif t == "Line":
            fig = px.line(g.sort_values(x), x=x, y=y, color=col, markers=True, **kw)
        elif t == "Area":
            fig = px.area(g.sort_values(x), x=x, y=y, color=col, **kw)
        elif t in ("Pie", "Donut"):
            fig = px.pie(g.groupby(x)[y].sum().reset_index(), names=x, values=y,
                         hole=0.5 if t == "Donut" else 0, **kw)
        elif t == "Funnel":
            fig = px.funnel(g.groupby(x)[y].sum().reset_index().sort_values(y, ascending=False),
                            x=y, y=x, **kw)
        else:
            path = [x] + ([col] if col else [])
            g = g[g[y] > 0]
            fig = (px.treemap if t == "Treemap" else px.sunburst)(
                g, path=path, values=y, template=c["template"],
                color_discrete_sequence=pal)
    elif t in ("Scatter", "Bubble"):
        size = sample[z].abs() if t == "Bubble" and z else None
        fig = px.scatter(sample, x=x, y=y, color=col, size=size, opacity=.8, **kw)
    elif t == "Histogram":
        fig = px.histogram(df, x=y, color=col, nbins=30, **kw)
    elif t in ("Box", "Violin"):
        fn = px.box if t == "Box" else px.violin
        fig = fn(df, x=x, y=y, color=col, **kw)
    elif t == "Heatmap":
        if col:
            p = df.pivot_table(index=x, columns=col, values=y, aggfunc=agg)
            fig = px.imshow(p, text_auto=".2s", aspect="auto", template=c["template"],
                            color_continuous_scale="Viridis")
        else:
            nm = df.select_dtypes("number")
            fig = px.imshow(nm.corr().round(2), text_auto=True, aspect="auto",
                            template=c["template"], color_continuous_scale="RdBu_r",
                            zmin=-1, zmax=1)
    elif t == "3D scatter":
        fig = px.scatter_3d(sample, x=x, y=y, z=z, color=col, opacity=.85, **kw)
    elif t == "3D surface":
        if not col:
            raise ValueError("3D surface needs a Color / Series column as the second axis.")
        p = df.pivot_table(index=x, columns=col, values=y, aggfunc=agg).fillna(0)
        fig = go.Figure(go.Surface(z=p.values, x=[str(v) for v in p.columns],
                                   y=[str(v) for v in p.index], colorscale="Viridis"))
        fig.update_layout(template=c["template"],
                          scene=dict(xaxis_title=col, yaxis_title=x, zaxis_title=y))
    else:
        fig = bar3d(df, x, y, col, agg, pal, topn)
        fig.update_layout(template=c["template"])

    fig.update_layout(title=c["title"] or f"{t}: {y} by {x}", height=c["height"],
                      margin=dict(l=20, r=20, t=60, b=20))
    if c["template"] == "plotly_dark":
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig


def tile_defaults(i, cols, nums, dates, cats):
    c0 = cats[0] if cats else cols[0]
    c1 = cats[1] if len(cats) > 1 else None
    n0 = nums[0] if nums else cols[0]
    n1 = nums[1] if len(nums) > 1 else n0
    d = [("Line" if dates else "Column", dates[0] if dates else c0, n0, None),
         ("Column", c0, n0, c1),
         ("Donut", c1 or c0, n0, None),
         ("Scatter", n0, n1, c0 if cats else None),
         ("3D bar", c0, n0, c1),
         ("Histogram", c0, n0, None)]
    return d[i % len(d)]


def chart_tile(i, df, cols, nums, dates, cats):
    typ, x, y, col = tile_defaults(i, cols, nums, dates, cats)
    box = st.container()
    with st.expander(f"⚙️ Edit chart {i + 1}", expanded=False):
        k = f"tile{i}_"
        a, b, c = st.columns(3)
        types = TYPES_2D + TYPES_3D
        c_type = a.selectbox("Chart type", types, index=types.index(typ), key=k + "type")
        c_x = b.selectbox("X / Category", cols, index=cols.index(x), key=k + "x")
        yopts = nums or cols
        c_y = c.selectbox("Y / Value", yopts, index=yopts.index(y) if y in yopts else 0,
                          key=k + "y")
        a, b, c = st.columns(3)
        copts = ["(none)"] + cols
        c_col = a.selectbox("Color / Series", copts,
                            index=copts.index(col) if col in copts else 0, key=k + "col")
        zopts = nums or cols
        c_z = b.selectbox("Z / Size (3D, bubble)", zopts,
                          index=min(2, len(zopts) - 1), key=k + "z")
        c_agg = c.selectbox("Calculation", AGGS, key=k + "agg")
        a, b, c = st.columns(3)
        c_top = a.slider("Show top N", 3, 50, 12, key=k + "top")
        c_pal = b.selectbox("Colors", list(PALETTES), index=_idx(list(PALETTES), S()["palette"]),
                            key=k + "pal")
        c_tpl = c.selectbox("Style", TEMPLATES, index=_idx(TEMPLATES, default_template()),
                            key=k + "tpl" + ("d" if current_theme()["dark"] else "l"))
        a, b, c = st.columns(3)
        c_title = a.text_input("Title", key=k + "title")
        c_h = b.slider("Height", 280, 800, 420, key=k + "h")
        c_lab = c.checkbox("Data labels", key=k + "lab")
    cfg = dict(type=c_type, x=c_x, y=c_y, z=c_z, color=None if c_col == "(none)" else c_col,
               agg=c_agg, topn=c_top, palette=c_pal, template=c_tpl, title=c_title,
               height=c_h, labels=c_lab)
    with box:
        try:
            fig = make_fig(df, cfg)
            st.session_state.setdefault("_figs_tmp", {})[i] = fig
            st.plotly_chart(fig, key=k + "plot", config={
                "editable": True, "displaylogo": False, "scrollZoom": True,
                "edits": {"titleText": True, "legendPosition": True, "annotationText": True},
                "toImageButtonOptions": {"format": "png", "scale": 2}}, theme=None, **_STRETCH)
            st.download_button("Download interactive chart (HTML)", fig.to_html(include_plotlyjs="cdn"),
                               f"chart_{i + 1}.html", "text/html", key=k + "dl")
        except Exception as exc:
            st.error(f"This combination can't be drawn: {exc}. Open 'Edit chart' and change a field.")
    return cfg


# ----------------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------------
def render(df, nums, dates, cats, pre_filters=None, total_rows=None):
    st.session_state.pop("bi_export", None)
    st.session_state.pop("bi_figs", None)
    st.session_state.pop("bi_cfgs", None)
    st.session_state["_figs_tmp"] = {}
    st.header("Power BI style dashboard")
    st.caption("Use the 🎛️ Slicers in the sidebar and the quick filters below, pick your KPIs, then edit each "
               "chart. The PDF, PowerPoint and HTML in the Download tab are built from what you see here.")
    if df.empty:
        st.warning("No rows match the slicers in the sidebar. Press 'Reset slicers' to see the dashboard.")
        return

    fdf, flt = df.copy(), list(pre_filters or [])
    with st.expander("🎚️ Quick filters", expanded=False):
        if dates:
            d = dates[0]
            lo, hi = df[d].min().date(), df[d].max().date()
            rng = st.date_input(f"{d} range", (lo, hi), min_value=lo, max_value=hi,
                                key=f"dash_date_{lo}_{hi}")
            if isinstance(rng, (tuple, list)) and len(rng) == 2:
                fdf = fdf[(fdf[d].dt.date >= rng[0]) & (fdf[d].dt.date <= rng[1])]
                if (rng[0], rng[1]) != (lo, hi):
                    flt.append(f"{d}: {rng[0]} to {rng[1]}")
        for c in cats[:4]:
            opts = sorted(df[c].dropna().astype(str).unique())
            sel = st.multiselect(c, opts, key=f"dash_f_{c}_{abs(hash(tuple(opts))) % 10 ** 6}")
            if sel:
                fdf = fdf[fdf[c].astype(str).isin(sel)]
                flt.append(f"{c}: " + ", ".join(sel))
    if fdf.empty:
        st.warning("No rows match these filters.")
        return
    st.caption(f"Showing {len(fdf):,} of {total_rows or len(df):,} rows.")

    kp = kpi_cards(fdf, nums, dates)

    st.subheader("Charts")
    n = st.slider("Number of charts", 1, 8, int(S()["dash_charts"]), key="dash_n")
    cols = list(fdf.columns)
    grid = st.columns(2)
    specs, cfgs = [], []
    for i in range(n):
        with grid[i % 2]:
            cfg = chart_tile(i, fdf, cols, nums, dates, cats)
        cfgs.append(cfg)
        try:
            specs.append(chart_spec(fdf, cfg))
        except Exception:
            pass  # a chart that cannot be summarised is simply left out of the exports
    tmp = st.session_state.get("_figs_tmp", {})
    st.session_state["bi_figs"] = [tmp[i] for i in sorted(tmp) if i < n]
    st.session_state["bi_cfgs"] = cfgs
    st.session_state["bi_export"] = dict(kpis=kp, specs=specs, filters=flt, rows=len(fdf),
                                         total=total_rows or len(df), missing=int(fdf.isna().sum().sum()))


# ======================================================================
# Export: Power BI dashboard -> PowerPoint / PDF (for presenting)
# ======================================================================
KIND = {"Column": "column", "Stacked column": "stacked", "Bar (horizontal)": "bar",
        "Funnel": "bar", "Line": "line", "Area": "area", "Pie": "pie", "Donut": "donut",
        "Treemap": "pie", "Sunburst": "pie", "Scatter": "scatter", "Bubble": "scatter",
        "3D scatter": "scatter", "3D bar": "column3d"}
HEX = ["#00b4d8", "#1f4e79", "#feca57", "#f368e0", "#38b000", "#ff6b6b", "#a29bfe", "#ff9f43"]
CALC = {"sum": "total", "mean": "average", "median": "median", "count": "count",
        "max": "maximum", "min": "minimum", "nunique": "unique count"}


def clean(s):
    return "".join(ch for ch in str(s).replace("**", "") if ord(ch) < 0x2000).strip()


def delta_text(d):
    return "Overall figure" if d is None else f"{d:+.1%} vs first half"


def chart_spec(df, c):
    """Turn one dashboard chart setting into plain data + a plain-language takeaway."""
    t, x, y, col, agg = c["type"], c["x"], c["y"], c["color"], c["agg"]
    kind = KIND.get(t, "column")
    sp = dict(kind=kind, cats=[], series={}, pts={}, xl=x, yl=y)

    if t == "Histogram":
        s = df[y].dropna()
        cnt, edges = np.histogram(s, bins=10)
        i = int(cnt.argmax())
        sp.update(kind="column", cats=[f"{short(a)}-{short(b)}" for a, b in zip(edges[:-1], edges[1:])],
                  series={"Records": [int(v) for v in cnt]}, xl=y, yl="Records",
                  ctitle=c["title"] or f"Distribution of {y}",
                  headline=f"Most {y} values fall between {short(edges[i])} and {short(edges[i + 1])}",
                  bullets=[f"{int(cnt[i]):,} of {len(s):,} records ({cnt[i] / len(s):.0%}) are in this range",
                           f"Overall range: {short(s.min())} to {short(s.max())}"])
        return sp

    if kind == "scatter" and x != y and pd.api.types.is_numeric_dtype(df[x]):
        d = df.dropna(subset=[x, y])
        d = d.sample(min(len(d), 300), random_state=1)
        grp = [(str(k), g) for k, g in d.groupby(col)] \
            if col and col not in (x, y) and d[col].nunique() <= 6 else [(y, d)]
        r = d[x].corr(d[y])
        if np.isnan(r):
            head = f"{y} against {x}"
        else:
            word = "strong" if abs(r) >= .7 else "moderate" if abs(r) >= .4 else "weak"
            head = f"{x} and {y} have a {word} {'positive' if r > 0 else 'negative'} relationship"
        sp.update(pts={k: list(zip(g[x].astype(float), g[y].astype(float))) for k, g in grp},
                  ctitle=c["title"] or f"{y} vs {x}", headline=head,
                  bullets=[f"Correlation: {r:.2f} across {len(d):,} records", "Each dot is one record"])
        return sp
    if kind == "scatter":
        kind = sp["kind"] = "column"

    d = df.copy()
    is_dt = pd.api.types.is_datetime64_any_dtype(d[x])
    if is_dt and d[x].nunique() > 24:
        d[x] = d[x].dt.to_period("M").dt.to_timestamp()
    pie = kind in ("pie", "donut")
    keys = [x] + ([col] if col and col != x and not pie else [])
    g = d.groupby(keys)[y].agg(agg).reset_index()
    tot = g.groupby(x)[y].sum()
    if is_dt or kind in ("line", "area"):
        order = sorted(tot.index)[-60:]
    else:
        order = list(tot.sort_values(ascending=False).index[:c["topn"]])
    cats = [v.strftime("%b %Y") if hasattr(v, "strftime") else str(v) for v in order]
    if len(keys) == 2:
        p = g.pivot_table(index=x, columns=col, values=y, aggfunc="sum").reindex(order).fillna(0)
        series = {str(k): [float(v) for v in p[k]] for k in list(p.columns)[:8]}
    else:
        series = {y: [float(tot[k]) for k in order]}

    tv = [sum(v[i] for v in series.values()) for i in range(len(order))]
    hi, lo, total, calc = int(np.argmax(tv)), int(np.argmin(tv)), sum(tv), CALC[agg]
    if kind in ("line", "area") and len(tv) >= 2:
        chg = f" {abs((tv[-1] - tv[0]) / tv[0]):.0%}" if tv[0] else ""
        head = f"{y} {'rose' if tv[-1] >= tv[0] else 'fell'}{chg} from {cats[0]} to {cats[-1]}"
        bl = [f"Peak: {cats[hi]} ({short(tv[hi])})", f"Lowest: {cats[lo]} ({short(tv[lo])})"]
    else:
        share = f" ({tv[hi] / total:.0%} of total)" if agg in ("sum", "count") and total else ""
        head = f"{cats[hi]} leads on {calc} {y} at {short(tv[hi])}{share}"
        bl = [f"Lowest: {cats[lo]} ({short(tv[lo])})", f"{len(cats)} {x} values shown"]
    bl.append(f"Measure: {calc} of {y}" + (f", split by {col}" if len(keys) == 2 else ""))
    sp.update(cats=cats, series=series, headline=head, bullets=bl,
              ctitle=c["title"] or f"{calc.title()} of {y} by {x}")
    return sp


# ---------------------------------------------------------------- shareable HTML page
def build_dashboard_html(title, bi, figs, insights, theme):
    """One self-contained .html page (KPIs + interactive charts) that opens in any browser."""
    t = theme
    root = ":root{color-scheme:" + ("dark" if t["dark"] else "light") + ";" + \
        ";".join(f"--{k}:{v}" for k, v in t.items() if k != "dark") + "}"
    cards = []
    for k in bi.get("kpis", []):
        d = k.get("delta")
        trend = ('<div class="flat">no trend</div>' if d is None else
                 f'<div class="{"up" if d >= 0 else "down"}">{"▲" if d >= 0 else "▼"} {abs(d):.1%} vs first half</div>')
        cards.append(f'<div class="kpi"><div class="lbl">{esc(str(k["label"]))}</div>'
                     f'<div class="val">{esc(str(k["value"]))}</div>{trend}</div>')
    charts = [f'<div class="card">' + f.to_html(full_html=False, include_plotlyjs="cdn" if i == 0 else False,
                                               config={"displaylogo": False, "responsive": True}) + "</div>"
              for i, f in enumerate(figs)]
    finds = "".join(f"<li>{esc(clean(i))}</li>" for i in insights[:6])
    flt = bi.get("filters") or []
    sub = f"{bi.get('rows', 0):,} of {bi.get('total', 0):,} rows" + (" · " + "; ".join(flt) if flt else "")
    css = """
body{margin:0;font-family:system-ui,'Segoe UI',Arial,sans-serif;background:var(--page);color:var(--ink)}
.wrap{max-width:1300px;margin:0 auto;padding:24px 16px 48px}
h1{margin:0 0 4px;font-size:2rem}.sub{color:var(--soft);margin-bottom:22px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:22px}
.kpi{background:linear-gradient(145deg,var(--panel2),var(--panel));border:1px solid var(--line);
border-radius:16px;padding:16px 18px;box-shadow:0 10px 24px var(--shadow-lg)}
.lbl{font-size:.8rem;color:var(--soft)}.val{font-size:1.9rem;font-weight:800;margin:2px 0}
.up{color:#1fbf86;font-weight:600;font-size:.85rem}.down{color:#ff6b81;font-weight:600;font-size:.85rem}
.flat{color:var(--soft);font-size:.85rem}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(480px,1fr));gap:18px}
.card{background:linear-gradient(160deg,var(--panel2),var(--panel));border:1px solid var(--line);
border-radius:16px;padding:8px;overflow:hidden;box-shadow:0 10px 24px var(--shadow-lg)}
.find{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:6px 22px;margin-bottom:22px}
footer{margin-top:28px;color:var(--soft);font-size:.8rem;text-align:center}
@media(max-width:560px){.grid{grid-template-columns:1fr}}"""
    return ("<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{esc(title)} - dashboard</title><style>{root}{css}</style></head><body><div class='wrap'>"
            f"<h1>📊 {esc(title)}</h1><div class='sub'>{esc(sub)} · {datetime.now():%Y-%m-%d %H:%M}</div>"
            f"<div class='kpis'>{''.join(cards)}</div>"
            + (f"<div class='find'><h3>Key findings</h3><ul>{finds}</ul></div>" if finds else "")
            + f"<div class='grid'>{''.join(charts)}</div>"
            "<footer>Created with DataPilot AI · charts are interactive (hover, zoom). "
            "An internet connection is needed to load the chart library.</footer></div></body></html>")


# ---------------------------------------------------------------- PowerPoint
def build_pptx(bi, insights, notes, title, dark=True):
    """Presentation for stakeholders: title, one-page Power BI style dashboard
    (KPI cards + charts), key findings, one slide per chart, data notes."""
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData, XyChartData
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE as CT, XL_LABEL_POSITION, XL_LEGEND_POSITION, XL_MARKER_STYLE
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt

    rgb = RGBColor
    hexrgb = lambda h: RGBColor.from_string(h.lstrip("#").upper())
    NAVY, TEAL, WHITE = rgb(10, 16, 36), rgb(0, 180, 216), rgb(255, 255, 255)
    if dark:   # same look as the website
        BG, PANEL, INK = rgb(10, 16, 36), rgb(22, 34, 80), rgb(232, 236, 255)
        MUTED, GRID, EDGE = rgb(159, 179, 255), rgb(52, 68, 128), rgb(52, 72, 150)
        UP, DOWN = rgb(56, 232, 168), rgb(255, 107, 129)
    else:      # Power BI light canvas: grey page, white tiles
        BG, PANEL, INK = rgb(243, 242, 241), WHITE, rgb(37, 36, 35)
        MUTED, GRID, EDGE = rgb(96, 94, 92), rgb(225, 223, 221), rgb(225, 223, 221)
        UP, DOWN = rgb(27, 158, 107), rgb(192, 57, 43)

    pal = ["#4895ef" if (dark and h == "#1f4e79") else h for h in HEX]  # keep every colour visible on dark
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    count = [0]

    def text(sl, s, l, t, w, h, size=14, bold=False, color=None, align=None):
        tf = sl.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h)).text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text, p.font.size, p.font.bold = s, Pt(size), bold
        p.font.color.rgb = color or INK
        if align:
            p.alignment = align
        return tf

    def bullets(sl, items, l, t, w, h, size=15):
        tf = text(sl, "", l, t, w, h, size)
        for i, s in enumerate(items):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text, p.font.size, p.font.color.rgb = "• " + clean(s), Pt(size), INK
            p.space_after = Pt(10)

    def shape(sl, kind, l, t, w, h, fill, line=None):
        s = sl.shapes.add_shape(kind, Inches(l), Inches(t), Inches(w), Inches(h))
        s.fill.solid()
        s.fill.fore_color.rgb = fill
        if line is None:
            s.line.fill.background()
        else:
            s.line.color.rgb, s.line.width = line, Pt(0.75)
        return s

    def panel(sl, l, t, w, h, accent=None):
        s = shape(sl, MSO_SHAPE.ROUNDED_RECTANGLE, l, t, w, h, PANEL, EDGE)
        s.adjustments[0] = min(0.5, 0.12 / min(w, h))
        if accent is not None:
            shape(sl, MSO_SHAPE.RECTANGLE, l + 0.15, t, w - 0.3, 0.05, accent)

    def new_slide(head, fy=7.05):
        sl = prs.slides.add_slide(prs.slide_layouts[6])
        count[0] += 1
        sl.background.fill.solid()
        sl.background.fill.fore_color.rgb = BG
        shape(sl, MSO_SHAPE.RECTANGLE, 0, 0, 13.333, 0.12, TEAL)
        if head:
            text(sl, head, 0.6, 0.35, 12.1, 1.0, 24, True)
        text(sl, f"DataPilot AI  |  {title}  |  {datetime.now():%d %b %Y}", 0.6, fy, 10, 0.3,
             9, color=MUTED)
        text(sl, str(count[0]), 12.2, fy, 0.6, 0.3, 9, color=MUTED, align=PP_ALIGN.RIGHT)
        return sl

    def add_chart(sl, sp, l, t, w, h, compact=False):
        k, fs = sp["kind"], (9 if compact else 12)
        if k == "scatter":
            cd = XyChartData()
            for name, pts in sp["pts"].items():
                s = cd.add_series(name)
                for a, b in pts:
                    s.add_data_point(a, b)
            ctype = CT.XY_SCATTER
        else:
            cats, ser = list(sp["cats"]), {n: list(v) for n, v in sp["series"].items()}
            if k == "bar":  # horizontal bars draw bottom-up, so flip to keep the top item first
                cats, ser = cats[::-1], {n: v[::-1] for n, v in ser.items()}
            cd = CategoryChartData()
            cd.categories = cats
            for n, v in ser.items():
                cd.add_series(n, v)
            ctype = {"column": CT.COLUMN_CLUSTERED, "column3d": CT.COLUMN_CLUSTERED,
                     "stacked": CT.COLUMN_STACKED, "bar": CT.BAR_CLUSTERED,
                     "line": CT.LINE_MARKERS, "area": CT.AREA, "pie": CT.PIE,
                     "donut": CT.DOUGHNUT}[k]
        ch = sl.shapes.add_chart(ctype, Inches(l), Inches(t), Inches(w), Inches(h), cd).chart
        ch.font.size, ch.font.color.rgb = Pt(fs), INK
        ch.has_title = True
        ch.chart_title.text_frame.text = clean(sp["ctitle"])
        tp = ch.chart_title.text_frame.paragraphs[0]
        tp.font.size, tp.font.bold, tp.font.color.rgb = Pt(11 if compact else 14), True, INK
        n_ser = len(sp["pts"] or sp["series"])
        ch.has_legend = n_ser > 1 or k in ("pie", "donut")
        if ch.has_legend:
            ch.legend.position = XL_LEGEND_POSITION.BOTTOM
            ch.legend.include_in_layout = False
            ch.legend.font.size, ch.legend.font.color.rgb = Pt(fs), INK
        if k in ("pie", "donut"):
            pl = ch.plots[0]
            pl.has_data_labels = True
            dl = pl.data_labels
            dl.show_percentage, dl.show_value = True, False
            dl.number_format, dl.number_format_is_linked = "0%", False
            dl.font.size = Pt(fs)
            if k == "pie":
                dl.position = XL_LABEL_POSITION.OUTSIDE_END
                dl.font.color.rgb = INK
            else:
                dl.font.color.rgb, dl.font.bold = NAVY, True
            for i in range(len(sp["cats"])):
                pt = pl.series[0].points[i].format.fill
                pt.solid()
                pt.fore_color.rgb = hexrgb(pal[i % 8])
            return
        for i, s in enumerate(ch.plots[0].series):
            col = hexrgb(pal[i % 8])
            if k == "line":
                s.format.line.color.rgb, s.format.line.width, s.smooth = col, Pt(2.5), False
                s.marker.format.fill.solid()
                s.marker.format.fill.fore_color.rgb = col
            elif k == "scatter":
                s.format.line.fill.background()
                s.marker.style = XL_MARKER_STYLE.CIRCLE
                s.marker.size = 5 if compact else 7
                s.marker.format.fill.solid()
                s.marker.format.fill.fore_color.rgb = col
            else:
                s.format.fill.solid()
                s.format.fill.fore_color.rgb = col
        if k in ("column", "column3d", "stacked", "bar"):
            ch.plots[0].gap_width = 60
        va, ca = ch.value_axis, ch.category_axis
        va.has_major_gridlines = True
        va.major_gridlines.format.line.color.rgb = GRID
        va.format.line.fill.background()
        ca.format.line.color.rgb = GRID
        for ax in (va, ca):
            ax.tick_labels.font.size, ax.tick_labels.font.color.rgb = Pt(fs), MUTED
        va.tick_labels.number_format, va.tick_labels.number_format_is_linked = "#,##0", False
        if k in ("column", "column3d", "stacked", "bar", "area") and \
                all(v >= 0 for vals in sp["series"].values() for v in vals):
            va.minimum_scale = 0  # bars must start at zero so differences are not exaggerated
        if k == "scatter" and not compact:
            for ax, lab in ((ca, sp["xl"]), (va, sp["yl"])):
                ax.has_title = True
                ax.axis_title.text_frame.text = clean(lab)
                ax.axis_title.text_frame.paragraphs[0].font.color.rgb = MUTED
        elif n_ser == 1 and k in ("column", "column3d", "bar") and not compact:
            pl = ch.plots[0]
            pl.has_data_labels = True
            pl.data_labels.number_format, pl.data_labels.number_format_is_linked = "#,##0", False
            pl.data_labels.font.size, pl.data_labels.font.color.rgb = Pt(10), INK

    # ---- 1. title (always dark)
    sl = prs.slides.add_slide(prs.slide_layouts[6])
    count[0] += 1
    shape(sl, MSO_SHAPE.RECTANGLE, 0, 0, 13.333, 7.5, NAVY)
    shape(sl, MSO_SHAPE.RECTANGLE, 0.8, 3.75, 1.6, 0.08, TEAL)
    text(sl, "Data Analysis Dashboard", 0.8, 1.7, 11.5, 1.2, 44, True, WHITE)
    text(sl, clean(title), 0.8, 2.8, 11.5, 0.7, 24, False, TEAL)
    text(sl, f"{bi['rows']:,} records  |  {datetime.now():%d %B %Y}", 0.8, 4.0, 11.5, 0.5, 16,
         False, rgb(191, 208, 255))

    # ---- 2. one-page Power BI style dashboard: KPI cards + charts
    kp, sps = bi["kpis"][:6], bi["specs"][:4]
    if kp or sps:
        sl = new_slide(None, fy=7.2)
        text(sl, "Executive dashboard", 0.45, 0.2, 7, 0.55, 22, True)
        flt = "; ".join(clean(f) for f in bi["filters"]) or "All data"
        text(sl, f"{bi['rows']:,} records  |  {flt}"[:120], 6.4, 0.3, 6.5, 0.4, 10,
             color=MUTED, align=PP_ALIGN.RIGHT)
        top = 0.9
        if kp:
            n, gap = len(kp), 0.2
            w = (12.43 - gap * (n - 1)) / n
            for i, k in enumerate(kp):
                l = 0.45 + i * (w + gap)
                panel(sl, l, top, w, 1.3, hexrgb(pal[i % 8]))
                text(sl, clean(k["label"]), l + 0.1, top + 0.12, w - 0.2, 0.45,
                     10 if n <= 4 else 9, color=MUTED)
                text(sl, k["value"], l + 0.1, top + 0.5, w - 0.2, 0.55,
                     28 if n <= 4 else 22, True)
                dcol = MUTED if k["delta"] is None else UP if k["delta"] >= 0 else DOWN
                text(sl, delta_text(k["delta"]), l + 0.1, top + 0.98, w - 0.2, 0.28, 9,
                     color=dcol)
            top += 1.45
        if sps:
            avail, n = 7.1 - top, len(sps)
            if n == 1:
                slots = [(0.45, top, 12.43, avail)]
            elif n == 2:
                slots = [(0.45, top, 6.14, avail), (6.74, top, 6.14, avail)]
            else:
                rh = (avail - 0.15) / 2
                slots = [(0.45, top, 6.14, rh), (6.74, top, 6.14, rh)]
                slots += [(0.45, top + rh + 0.15, 12.43, rh)] if n == 3 else \
                    [(0.45, top + rh + 0.15, 6.14, rh), (6.74, top + rh + 0.15, 6.14, rh)]
            for sp, (l, t, w, h) in zip(sps, slots):
                panel(sl, l, t, w, h)
                try:
                    add_chart(sl, sp, l + 0.08, t + 0.08, w - 0.16, h - 0.16, compact=True)
                except Exception as exc:
                    text(sl, f"Chart could not be drawn: {exc}", l + 0.2, t + 0.5, w - 0.4, 1,
                         12, color=DOWN)
        sl.notes_slide.notes_text_frame.text = "Overview: " + " | ".join(
            f"{clean(k['label'])}: {k['value']}" for k in kp)

    # ---- 3. key findings
    pts = [clean(i) for i in insights if clean(i)][:7]
    if pts:
        sl = new_slide("Key findings from the data")
        panel(sl, 0.6, 1.4, 12.1, min(5.4, 0.9 + 0.6 * len(pts)))
        bullets(sl, pts, 0.85, 1.65, 11.6, 5.0, 16)

    # ---- 4. one slide per chart, with a plain-language takeaway
    for sp in bi["specs"]:
        sl = new_slide(clean(sp["headline"]))
        panel(sl, 0.6, 1.5, 8.4, 5.3)
        try:
            add_chart(sl, sp, 0.7, 1.6, 8.2, 5.1)
        except Exception as exc:
            text(sl, f"Chart could not be drawn: {exc}", 0.9, 3, 7.5, 1, 14, color=DOWN)
        panel(sl, 9.3, 1.5, 3.45, 5.3, TEAL)
        text(sl, "What this shows", 9.5, 1.7, 3.1, 0.5, 16, True)
        bullets(sl, sp["bullets"], 9.5, 2.35, 3.1, 4.3, 13)
        sl.notes_slide.notes_text_frame.text = clean(sp["headline"]) + "\n" + "\n".join(
            "- " + clean(b) for b in sp["bullets"])

    # ---- 5. data notes
    sl = new_slide("About this data")
    panel(sl, 0.6, 1.4, 12.1, 5.4)
    flt = "; ".join(clean(f) for f in bi["filters"]) or "none"
    bullets(sl, [f"Records analysed: {bi['rows']:,} of {bi['total']:,}", f"Filters applied: {flt}",
                 f"Missing cells in analysed data: {bi['missing']:,}"] + [clean(n) for n in notes],
            0.85, 1.65, 11.6, 5.0, 16)
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


# ---------------------------------------------------------------- PDF
def build_bi_pdf(bi, insights, notes, title):
    from xml.sax.saxutils import escape

    from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
    from reportlab.graphics.charts.legends import Legend
    from reportlab.graphics.charts.linecharts import HorizontalLineChart
    from reportlab.graphics.charts.piecharts import Pie
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics.widgets.markers import makeMarker
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    cols = [colors.HexColor(h) for h in HEX]
    navy, grey = colors.HexColor("#0a1024"), colors.HexColor("#555f7a")
    base = getSampleStyleSheet()["BodyText"]
    H = ParagraphStyle("H", parent=base, fontName="Helvetica-Bold", fontSize=20, leading=25,
                       textColor=navy, spaceAfter=8)
    B = ParagraphStyle("B", parent=base, fontSize=12, leading=17, spaceAfter=5)
    KL = ParagraphStyle("KL", parent=base, fontSize=11, textColor=grey)
    KV = ParagraphStyle("KV", parent=base, fontName="Helvetica-Bold", fontSize=28, leading=36)
    P = lambda s, st: Paragraph(escape(clean(s)), st)

    def drawing(sp, w=760, h=315):
        d, k = Drawing(w, h), sp["kind"]
        names = list(sp["pts"] or sp["series"])
        legend = len(names) > 1 and k not in ("pie", "donut")
        cw = w - (250 if legend else 100)
        if k == "scatter":
            # light-weight hand-drawn scatter (reportlab's ScatterPlot is very slow and memory hungry)
            from reportlab.graphics.shapes import Circle, Line, Rect, String
            allp = [p for v in sp["pts"].values() for p in v]
            xs, ys = [p[0] for p in allp], [p[1] for p in allp]
            x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
            x1, y1 = (x1 if x1 > x0 else x0 + 1), (y1 if y1 > y0 else y0 + 1)
            X0, Y0, PW, PH = 70, 40, cw - 20, h - 70
            sx = lambda v: X0 + (v - x0) / (x1 - x0) * PW
            sy = lambda v: Y0 + (v - y0) / (y1 - y0) * PH
            for i in range(5):
                gx, gy = x0 + (x1 - x0) * i / 4, y0 + (y1 - y0) * i / 4
                d.add(Line(sx(gx), Y0, sx(gx), Y0 + PH, strokeColor=colors.HexColor("#e1e5ee"), strokeWidth=0.5))
                d.add(Line(X0, sy(gy), X0 + PW, sy(gy), strokeColor=colors.HexColor("#e1e5ee"), strokeWidth=0.5))
                d.add(String(sx(gx), Y0 - 14, short(gx), fontSize=8, textAnchor="middle", fillColor=grey))
                d.add(String(X0 - 6, sy(gy) - 3, short(gy), fontSize=8, textAnchor="end", fillColor=grey))
            d.add(Rect(X0, Y0, PW, PH, fillColor=None, strokeColor=grey, strokeWidth=0.6))
            d.add(String(X0 + PW / 2, 8, clean(sp["xl"]), fontSize=9, textAnchor="middle", fillColor=grey))
            d.add(String(14, Y0 + PH / 2, clean(sp["yl"]), fontSize=9, textAnchor="middle", fillColor=grey))
            for i, pts in enumerate(sp["pts"].values()):
                for a, b in pts[:250]:
                    d.add(Circle(sx(a), sy(b), 2.6, fillColor=cols[i % 8], strokeColor=None))
            ch = None
        elif k in ("pie", "donut"):
            vals = list(sp["series"].values())[0]
            tot = sum(vals) or 1
            ch = Pie()
            ch.data = vals
            ch.labels = [f"{c[:16]} ({v / tot:.0%})" for c, v in zip(sp["cats"], vals)]
            ch.sideLabels, ch.slices.fontSize, ch.slices.strokeColor = 1, 9, colors.white
            for i in range(len(vals)):
                ch.slices[i].fillColor = cols[i % 8]
            if k == "donut":
                ch.innerRadiusFraction = 0.5
            sz = h - 60
            ch.x, ch.y, ch.width, ch.height = (w - sz) / 2, 30, sz, sz
        else:
            line = k in ("line", "area")
            horiz = k == "bar"
            ch = (HorizontalLineChart if line else HorizontalBarChart if horiz else VerticalBarChart)()
            cats, data = list(sp["cats"]), [list(v) for v in sp["series"].values()]
            if horiz:
                cats, data = cats[::-1], [v[::-1] for v in data]
            step = max(1, len(cats) // 14)
            ch.data = data
            ch.categoryAxis.categoryNames = [c[:14] if i % step == 0 else "" for i, c in enumerate(cats)]
            ch.valueAxis.labelTextFormat = short
            if not line:
                ch.valueAxis.valueMin = min(0, min(map(min, data)))
            if k == "stacked":
                ch.categoryAxis.style = "stacked"
            if not horiz:
                ch.categoryAxis.labels.angle, ch.categoryAxis.labels.boxAnchor = 30, "ne"
            for i in range(len(data)):
                if line:
                    ch.lines[i].strokeColor, ch.lines[i].strokeWidth = cols[i % 8], 2.5
                    ch.lines[i].symbol = makeMarker("Circle")
                else:
                    ch.bars[i].fillColor = cols[i % 8]
            ch.x, ch.y, ch.width, ch.height = (140 if horiz else 60), 60, cw - (80 if horiz else 0), h - 80
        if ch is not None:
            d.add(ch)
        if legend:
            lg = Legend()
            lg.x, lg.y, lg.fontSize, lg.alignment = w - 170, h - 30, 9, "right"
            lg.colorNamePairs = [(cols[i % 8], clean(n)[:18]) for i, n in enumerate(names)]
            d.add(lg)
        return d

    story = [Spacer(1, 130),
             Paragraph("Data Analysis Dashboard", ParagraphStyle("T", parent=H, fontSize=40, leading=48)),
             P(title, ParagraphStyle("S", parent=B, fontSize=20, leading=26, textColor=colors.HexColor("#0077b6"))),
             Spacer(1, 14),
             P(f"{bi['rows']:,} records  |  {datetime.now():%d %B %Y}", B), PageBreak()]
    pts = [clean(i) for i in insights if clean(i)][:7]
    if pts:
        story += [P("Key findings from the data", H)] + [P("- " + s, B) for s in pts] + [PageBreak()]
    if bi["kpis"]:
        cells = [[P(k["label"], KL), P(k["value"], KV), P(delta_text(k["delta"]), KL)] for k in bi["kpis"][:6]]
        cells += [""] * (-len(cells) % 3)
        rows = [cells[i:i + 3] for i in range(0, len(cells), 3)]
        tb = Table(rows, colWidths=[252] * 3, rowHeights=[110] * len(rows))
        tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1f5fb")),
                                ("GRID", (0, 0), (-1, -1), 8, colors.white),
                                ("LINEABOVE", (0, 0), (-1, -1), 3, cols[0]),
                                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                ("LEFTPADDING", (0, 0), (-1, -1), 14)]))
        story += [P("Key metrics at a glance", H), Spacer(1, 10), tb, PageBreak()]
    for sp in bi["specs"]:
        story.append(P(sp["headline"], H))
        try:
            story.append(drawing(sp))
        except Exception as exc:
            story.append(P(f"Chart could not be drawn: {exc}", B))
        story += [P("- " + b, B) for b in sp["bullets"]] + [PageBreak()]
    flt = "; ".join(clean(f) for f in bi["filters"]) or "none"
    story += [P("About this data", H), P(f"- Records analysed: {bi['rows']:,} of {bi['total']:,}", B),
              P(f"- Filters applied: {flt}", B),
              P(f"- Missing cells in analysed data: {bi['missing']:,}", B)] + [P("- " + n, B) for n in notes]

    def foot(cv, doc):
        cv.saveState()
        cv.setFont("Helvetica", 8)
        cv.setFillColor(grey)
        cv.drawString(36, 20, f"DataPilot AI | {clean(title)}")
        cv.drawRightString(806, 20, f"Page {doc.page}")
        cv.restoreState()

    out = io.BytesIO()
    SimpleDocTemplate(out, pagesize=landscape(A4), leftMargin=36, rightMargin=36,
                      topMargin=30, bottomMargin=36).build(story, onFirstPage=foot, onLaterPages=foot)
    return out.getvalue()


def dark(fig):
    """Style a chart to match the current page theme (dark or light)."""
    t = current_theme()
    fig.update_layout(template="plotly_dark" if t["dark"] else "plotly_white",
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      colorway=flex.FLEX_PALETTE if theme_cfg()["look"] == "Flex" else PALETTES["Vivid"],
                      font=dict(color=t["ink"]))
    return fig


# ======================================================================
# BI PRO: slicers, maps, extra visuals and DAX automation
# ======================================================================
ROWS = "Number of rows"
MAP_TYPES = ["India states (bubble map)", "USA states (filled map)", "World countries (filled map)",
             "Latitude / longitude points", "My own GeoJSON (filled map)"]
MAP_KIND = dict(zip(MAP_TYPES, ["india", "usa", "world", "points", "geojson"]))
MAP_SCALES = ["Viridis", "Plasma", "Turbo", "Blues", "YlOrRd", "RdYlGn", "Cividis"]

# Approximate centre points of Indian states and union territories (used for the bubble map).
INDIA_STATES = {
    "Andhra Pradesh": (15.91, 79.74), "Arunachal Pradesh": (28.22, 94.73), "Assam": (26.20, 92.94),
    "Bihar": (25.10, 85.31), "Chhattisgarh": (21.28, 81.87), "Goa": (15.30, 74.12),
    "Gujarat": (22.26, 71.19), "Haryana": (29.06, 76.09), "Himachal Pradesh": (31.10, 77.17),
    "Jharkhand": (23.61, 85.28), "Karnataka": (15.32, 75.71), "Kerala": (10.85, 76.27),
    "Madhya Pradesh": (22.97, 78.66), "Maharashtra": (19.75, 75.71), "Manipur": (24.66, 93.91),
    "Meghalaya": (25.47, 91.37), "Mizoram": (23.16, 92.94), "Nagaland": (26.16, 94.56),
    "Odisha": (20.95, 85.10), "Punjab": (31.15, 75.34), "Rajasthan": (27.02, 74.22),
    "Sikkim": (27.53, 88.51), "Tamil Nadu": (11.13, 78.66), "Telangana": (18.11, 79.02),
    "Tripura": (23.94, 91.99), "Uttar Pradesh": (26.85, 80.95), "Uttarakhand": (30.07, 79.02),
    "West Bengal": (22.99, 87.86), "Andaman and Nicobar Islands": (11.74, 92.66),
    "Chandigarh": (30.73, 76.78), "Dadra and Nagar Haveli and Daman and Diu": (20.40, 72.83),
    "Delhi": (28.70, 77.10), "Jammu and Kashmir": (33.78, 76.58), "Ladakh": (34.15, 77.58),
    "Lakshadweep": (10.57, 72.64), "Puducherry": (11.94, 79.81)}
INDIA_ALIASES = {
    "orissa": "Odisha", "uttaranchal": "Uttarakhand", "pondicherry": "Puducherry", "nct of delhi": "Delhi",
    "new delhi": "Delhi", "delhi ncr": "Delhi", "tamilnadu": "Tamil Nadu", "chattisgarh": "Chhattisgarh",
    "telengana": "Telangana", "bengal": "West Bengal", "andaman and nicobar": "Andaman and Nicobar Islands",
    "andaman nicobar islands": "Andaman and Nicobar Islands", "andaman and nicobar island": "Andaman and Nicobar Islands",
    "dadra and nagar haveli": "Dadra and Nagar Haveli and Daman and Diu",
    "daman and diu": "Dadra and Nagar Haveli and Daman and Diu", "j and k": "Jammu and Kashmir",
    "jammu kashmir": "Jammu and Kashmir", "bangalore": "Karnataka"}
INDIA_CODES = {
    "AP": "Andhra Pradesh", "AR": "Arunachal Pradesh", "AS": "Assam", "BR": "Bihar", "CG": "Chhattisgarh",
    "CT": "Chhattisgarh", "GA": "Goa", "GJ": "Gujarat", "HR": "Haryana", "HP": "Himachal Pradesh",
    "JH": "Jharkhand", "KA": "Karnataka", "KL": "Kerala", "MP": "Madhya Pradesh", "MH": "Maharashtra",
    "MN": "Manipur", "ML": "Meghalaya", "MZ": "Mizoram", "NL": "Nagaland", "OD": "Odisha", "OR": "Odisha",
    "PB": "Punjab", "RJ": "Rajasthan", "SK": "Sikkim", "TN": "Tamil Nadu", "TS": "Telangana",
    "TG": "Telangana", "TR": "Tripura", "UP": "Uttar Pradesh", "UK": "Uttarakhand", "WB": "West Bengal",
    "AN": "Andaman and Nicobar Islands", "CH": "Chandigarh", "DD": "Dadra and Nagar Haveli and Daman and Diu",
    "DN": "Dadra and Nagar Haveli and Daman and Diu", "DL": "Delhi", "JK": "Jammu and Kashmir",
    "LA": "Ladakh", "LD": "Lakshadweep", "PY": "Puducherry"}
US_STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO",
    "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA",
    "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
    "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM",
    "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT",
    "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY"}


def norm_key(x):
    s = str(x).lower().replace("&", " and ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s)).strip()


_INDIA_LOOKUP = {norm_key(n): n for n in INDIA_STATES}
_INDIA_LOOKUP.update(INDIA_ALIASES)
_US_LOOKUP = {norm_key(n): c for n, c in US_STATES.items()}
_US_CODES = set(US_STATES.values())
_US_NAME = {c: n for n, c in US_STATES.items()}


def india_state(x):
    """Official state / UT name for a value like 'karnataka', 'KA', 'Orissa'. None if unknown."""
    k = norm_key(x)
    if k in _INDIA_LOOKUP:
        return _INDIA_LOOKUP[k]
    s = str(x).strip()
    return INDIA_CODES.get(s.upper()) if len(s) == 2 else None


def us_state(x):
    """Two-letter US state code for a value like 'Texas' or 'tx'. None if unknown."""
    s = str(x).strip()
    if len(s) == 2 and s.upper() in _US_CODES:
        return s.upper()
    return _US_LOOKUP.get(norm_key(s))


def detect_geo(df, cols):
    """Guess which column holds places, and what kind: ('india' | 'usa' | 'world' | None, column)."""
    best = (None, None, 0.0)
    for c in cols:
        vals = df[c].dropna().astype(str).unique()[:300]
        if len(vals) == 0:
            continue
        for kind, fn in (("india", india_state), ("usa", us_state)):
            r = sum(1 for v in vals if fn(v)) / len(vals)
            if r > best[2]:
                best = (kind, c, r)
    if best[2] >= 0.5:
        return best[0], best[1]
    for c in cols:
        if re.search(r"country|nation", str(c).lower()):
            return "world", c
    return None, None


def find_latlon(df):
    num = df.select_dtypes(include="number").columns
    lat = next((c for c in num if str(c).lower() in ("lat", "latitude") or str(c).lower().startswith("lat")), None)
    lon = next((c for c in num if str(c).lower() in ("lon", "lng", "long", "longitude")
                or str(c).lower().startswith(("lon", "lng"))), None)
    return (lat, lon) if lat and lon else None


def canonical_series(df, col, kind):
    s = df[col].astype(str)
    if kind == "india":
        return s.map(india_state)
    if kind == "usa":
        return s.map(us_state)
    return s.str.strip().where(s.str.strip() != "")


def geo_aggregate(df, col, val, agg, kind):
    """Total the chosen value per place. Returns (table, unmatched names, matched rows, all rows)."""
    canon = canonical_series(df, col, kind)
    ok = canon.notna()
    unmatched = sorted(set(df.loc[~ok, col].astype(str)))[:20]
    d = df.loc[ok].assign(_loc=canon[ok])
    if val == ROWS:
        g = d.groupby("_loc").size().reset_index()
    else:
        g = d.groupby("_loc")[val].agg(agg).reset_index()
    g.columns = ["Location", "Value"]
    return g, unmatched, int(ok.sum()), len(df)


def selected_locations(event, g):
    """Places the user clicked on the map (event comes from st.plotly_chart on_select)."""
    try:
        pts = event["selection"]["points"]
    except Exception:
        return []
    out = []
    for p in pts:
        i = p.get("point_index", p.get("pointIndex"))
        if isinstance(i, int) and 0 <= i < len(g):
            out.append(g.iloc[i]["Location"])
    return list(dict.fromkeys(out))


def _bubble_size(v):
    a = np.abs(np.asarray(v, dtype=float))
    return 0.08 + (a / a.max() if a.max() else a)


def style_geo(fig, t):
    fig.update_geos(bgcolor="rgba(0,0,0,0)", showland=True, landcolor=t["panel2"], showocean=True,
                    oceancolor=_mix(t["bg"], t["accent"], .08), showcountries=True,
                    countrycolor=_mix(t["bg"], t["ink"], .35), showcoastlines=True,
                    coastlinecolor=_mix(t["bg"], t["ink"], .35), showlakes=False, showframe=False)
    fig.update_layout(height=620, margin=dict(l=0, r=0, t=40, b=0))
    return dark(fig)


def build_map(g, kind, scale, labels, t, gj=None, idkey=None, title=""):
    if kind == "india":
        g = g.assign(lat=g["Location"].map(lambda n: INDIA_STATES[n][0]),
                     lon=g["Location"].map(lambda n: INDIA_STATES[n][1]), _size=_bubble_size(g["Value"]))
        fig = px.scatter_geo(g, lat="lat", lon="lon", size="_size", color="Value", hover_name="Location",
                             hover_data={"lat": False, "lon": False, "_size": False, "Value": ":,.2f"},
                             text="Location" if labels else None, color_continuous_scale=scale, size_max=48)
        fig.update_geos(scope="asia", lataxis_range=[5, 37], lonaxis_range=[67, 98])
        if labels:
            fig.update_traces(textposition="top center")
    elif kind == "usa":
        g = g.assign(State=g["Location"].map(_US_NAME))
        fig = px.choropleth(g, locations="Location", locationmode="USA-states", color="Value", scope="usa",
                            hover_name="State", color_continuous_scale=scale)
    elif kind == "geojson":
        fig = px.choropleth(g, geojson=gj, locations="Location", featureidkey="properties." + idkey,
                            color="Value", color_continuous_scale=scale)
        fig.update_geos(fitbounds="locations", visible=False)
    else:
        fig = px.choropleth(g, locations="Location", locationmode="country names", color="Value",
                            color_continuous_scale=scale)
        fig.update_geos(projection_type="natural earth")
    fig.update_layout(title=title)
    return style_geo(fig, t)


def render_map(df, nums, dates, measure, default_agg):
    st.subheader("🗺️ Map (state-wise and more)")
    st.caption("Slicers in the sidebar apply here. Click a state or point on the map to see its rows below.")
    if df.empty:
        st.warning("No rows match the slicers.")
        return
    t = current_theme()
    text_cols = [c for c in df.columns if c not in dates and not pd.api.types.is_numeric_dtype(df[c])]
    kind0, col0 = detect_geo(df, text_cols)
    ll = find_latlon(df)
    c1, c2, c3, c4 = st.columns(4)
    mtype = c1.selectbox("Map type", MAP_TYPES, key="map_type",
                         index={"india": 0, "usa": 1, "world": 2}.get(kind0, 3 if ll else 0))
    kind = MAP_KIND[mtype]
    vals = [ROWS] + nums
    val = c2.selectbox("Value", vals, key="map_val", index=vals.index(measure) if measure in vals else 0)
    agg = c3.selectbox("Calculation", AGG_CHOICES, key="map_agg", index=_idx(AGG_CHOICES, default_agg))
    scale = c4.selectbox("Colors", MAP_SCALES, key="map_scale")
    if val == ROWS:
        agg = "count"

    gj = idkey = None
    if kind == "points":
        if not nums:
            st.info("This map needs two number columns: latitude and longitude.")
            return
        p1, p2 = st.columns(2)
        la = p1.selectbox("Latitude column", nums, key="map_lat", index=nums.index(ll[0]) if ll else 0)
        lo = p2.selectbox("Longitude column", nums, key="map_lon", index=nums.index(ll[1]) if ll else 0)
        d = df.dropna(subset=[la, lo])
        d = d[d[la].between(-90, 90) & d[lo].between(-180, 180)]
        if d.empty:
            st.warning("No valid coordinates found (latitude -90..90, longitude -180..180).")
            return
        if len(d) > 5000:
            st.caption(f"Showing a random 5,000 of {len(d):,} points.")
            d = d.sample(5000, random_state=1)
        extra = {}
        if val != ROWS:
            d = d.assign(_size=_bubble_size(d[val].fillna(0)))
            extra = dict(size="_size", color=val, color_continuous_scale=scale, size_max=22)
        fig = px.scatter_geo(d, lat=la, lon=lo, **extra)
        fig.update_geos(fitbounds="locations")
        fig = style_geo(fig, t)
        st.plotly_chart(fig, key="map_chart", theme=None, **W_PLOT)
        st.download_button("Download map (HTML)", fig.to_html(include_plotlyjs="cdn"), "map.html",
                           "text/html", key="map_dl", **W_DL)
        return

    if not text_cols:
        st.info("This map needs a text column with place names (for example State).")
        return
    loc = st.selectbox("Location column (state / country / region)", text_cols, key="map_loc",
                       index=text_cols.index(col0) if col0 in text_cols else 0)
    if kind == "geojson":
        st.caption("Upload boundaries that follow the official borders of the region you are mapping.")
        up = st.file_uploader("GeoJSON file", type=["geojson", "json"], key="map_gj")
        if up is None:
            st.info("Upload a GeoJSON file to draw a filled map from your own boundaries.")
            return
        try:
            gj = json.loads(up.getvalue().decode("utf-8-sig"))
            keys = list(gj["features"][0]["properties"])
        except Exception:
            st.error("That file is not a valid GeoJSON with features and properties.")
            return
        idkey = st.selectbox("Which property holds the place name?", keys, key="map_idkey")
    g, unmatched, ok_rows, total = geo_aggregate(df, loc, val, agg, kind)
    if g.empty:
        st.warning(f"None of the values in '{loc}' were recognised for this map type. "
                   "Pick another column or map type.")
        return
    if kind in ("india", "usa"):
        st.caption(f"Matched {ok_rows:,} of {total:,} rows to {len(g)} places.")
        if unmatched:
            st.warning("Not recognised (left out of the map): " + ", ".join(unmatched[:12])
                       + (" ..." if len(unmatched) > 12 else ""))
    labels = st.checkbox("Show place names on the map", value=(kind == "india"), key="map_labels")
    calc = "rows" if val == ROWS else f"{agg} of {val}"
    try:
        fig = build_map(g, kind, scale, labels, t, gj, idkey, title=f"{calc.title()} by {loc}")
    except Exception as exc:
        st.error(f"This map could not be drawn: {exc}")
        return
    event = st.plotly_chart(fig, key="map_chart", on_select="rerun", selection_mode="points",
                            theme=None, **W_PLOT)
    sel = selected_locations(event, g)
    if sel:
        canon = canonical_series(df, loc, kind)
        sub = df[canon.isin(sel)]
        st.markdown("**Selected: " + ", ".join(map(str, sel)) + f"**  ({len(sub):,} rows)")
        if val != ROWS and len(sub):
            st.metric(f"{calc.title()} for the selection", short(float(sub[val].agg(agg))))
        st.dataframe(sub.head(500), hide_index=True, **W_DF)
    rank = g.sort_values("Value", ascending=False).reset_index(drop=True)
    rank.insert(0, "Rank", rank.index + 1)
    if agg in ("sum", "count") and (rank["Value"] >= 0).all() and rank["Value"].sum() > 0:
        rank["Share %"] = (rank["Value"] / rank["Value"].sum() * 100).round(1)
    top, low = rank.iloc[0], rank.iloc[-1]
    k1, k2, k3 = st.columns(3)
    k1.metric("Highest", str(top["Location"]), short(float(top["Value"])))
    k2.metric("Lowest", str(low["Location"]), short(float(low["Value"])))
    if "Share %" in rank and len(rank) >= 3:
        k3.metric("Top 3 share of total", f"{rank['Share %'].head(3).sum():.0f}%")
    st.dataframe(rank, hide_index=True, **W_DF)
    d1, d2 = st.columns(2)
    d1.download_button("Download ranking (CSV)", rank.to_csv(index=False).encode("utf-8"), "map_ranking.csv",
                       "text/csv", key="map_csv", **W_DL)
    d2.download_button("Download map (HTML)", fig.to_html(include_plotlyjs="cdn"), "map.html", "text/html",
                       key="map_dl", **W_DL)


# ---------------------------------------------------------------- slicers
def _reset_slicers(sig):
    for k in [k for k in st.session_state if k.startswith(f"sl_{sig}_") or k == f"slicer_cols_{sig}"]:
        del st.session_state[k]


def slicer_panel(df, dataset_name):
    """Sidebar slicers (date range, number range, pick-list, text search). Returns
    (filtered data, readable notes, structured specs used to write DAX filters)."""
    notes, specs, fdf = [], [], df
    sig = abs(hash((dataset_name, tuple(map(str, df.columns)), len(df)))) % 10 ** 8
    with st.sidebar:
        with st.expander("🎛️ Slicers (Power BI, Map, BI Visuals)", expanded=False):
            cols = st.multiselect("Slice by these columns", list(df.columns), key=f"slicer_cols_{sig}")
            for c in cols:
                s, key = df[c], f"sl_{sig}_{c}"
                if pd.api.types.is_datetime64_any_dtype(s):
                    lo, hi = s.min().date(), s.max().date()
                    if lo == hi:
                        st.caption(f"{c}: only one date in the data.")
                        continue
                    r = st.date_input(c, (lo, hi), min_value=lo, max_value=hi, key=key)
                    if isinstance(r, (tuple, list)) and len(r) == 2 and (r[0], r[1]) != (lo, hi):
                        fdf = fdf[(fdf[c].dt.date >= r[0]) & (fdf[c].dt.date <= r[1])]
                        specs.append(dict(col=c, kind="date", lo=r[0], hi=r[1]))
                        notes.append(f"{c}: {r[0]} to {r[1]}")
                elif pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
                    lo, hi = s.min(), s.max()
                    if not lo < hi:
                        st.caption(f"{c}: only one value in the data.")
                        continue
                    if pd.api.types.is_integer_dtype(s):
                        lo, hi = int(lo), int(hi)
                        r = st.slider(c, lo, hi, (lo, hi), key=key)
                    else:
                        lo, hi = float(lo), float(hi)
                        r = st.slider(c, lo, hi, (lo, hi), step=(hi - lo) / 200, key=key)
                    if tuple(r) != (lo, hi):
                        fdf = fdf[(fdf[c] >= r[0]) & (fdf[c] <= r[1])]
                        specs.append(dict(col=c, kind="range", lo=r[0], hi=r[1]))
                        notes.append(f"{c}: {short(r[0])} to {short(r[1])}")
                elif s.nunique() <= 50:
                    opts = sorted(s.dropna().astype(str).unique())
                    sel = st.multiselect(c, opts, key=key)
                    if sel:
                        fdf = fdf[fdf[c].astype(str).isin(sel)]
                        specs.append(dict(col=c, kind="in", values=sel))
                        notes.append(f"{c}: " + ", ".join(sel))
                else:
                    txt = st.text_input(f"{c} contains", key=key)
                    if txt.strip():
                        fdf = fdf[fdf[c].astype(str).str.contains(txt.strip(), case=False, regex=False)]
                        specs.append(dict(col=c, kind="text", text=txt.strip()))
                        notes.append(f"{c} contains '{txt.strip()}'")
            if cols:
                st.caption(f"{len(fdf):,} of {len(df):,} rows match.")
                st.button("Reset slicers", key="sl_reset", on_click=_reset_slicers, args=(sig,), **W_BTN)
            else:
                st.caption("Pick one or more columns to add slicers. They filter the Power BI, Map and "
                           "BI Visuals tabs, and are also written into the DAX queries.")
    return fdf, notes, specs


# ---------------------------------------------------------------- extra BI visuals
def _with_time(df, dates):
    d = df.copy()
    if dates:
        d["Year"] = d[dates[0]].dt.year.astype("Int64").astype(str)
        d["Year-Month"] = d[dates[0]].dt.strftime("%Y-%m")
    return d


def fig_pareto(df, cat, val, agg, topn=20):
    s = df.groupby(cat)[val].agg(agg).clip(lower=0).sort_values(ascending=False)
    total = float(s.sum())
    cum = (s.cumsum() / total * 100) if total else s * 0
    k80 = int((cum < 80).sum() + 1)
    show, cshow = s.head(topn), cum.head(topn)
    fig = go.Figure()
    fig.add_bar(x=[str(i) for i in show.index], y=show.values, name=f"{agg.title()} of {val}")
    fig.add_scatter(x=[str(i) for i in cshow.index], y=cshow.values, name="Cumulative %", yaxis="y2",
                    mode="lines+markers", line=dict(color="#feca57"))
    fig.add_shape(type="line", xref="paper", x0=0, x1=1, yref="y2", y0=80, y1=80,
                  line=dict(dash="dot", color="#ff6b6b"))
    fig.update_layout(yaxis2=dict(overlaying="y", side="right", range=[0, 105], ticksuffix="%"),
                      height=480, margin=dict(l=20, r=20, t=50, b=20), title=f"Pareto of {val} by {cat}")
    return fig, k80, len(s)


def fig_waterfall(df, cat, val, agg, topn=12):
    s = df.groupby(cat)[val].agg(agg)
    s = s.reindex(s.abs().sort_values(ascending=False).index)
    labels = [str(i) for i in s.index[:topn]]
    vals = list(s.values[:topn])
    if len(s) > topn:
        labels.append("Other")
        vals.append(float(s.values[topn:].sum()))
    fig = go.Figure(go.Waterfall(x=labels + ["Total"], y=vals + [0],
                                 measure=["relative"] * len(vals) + ["total"],
                                 increasing=dict(marker=dict(color="#38e8a8")),
                                 decreasing=dict(marker=dict(color="#ff6b6b")),
                                 totals=dict(marker=dict(color="#00b4d8"))))
    fig.update_layout(height=480, margin=dict(l=20, r=20, t=50, b=20), title=f"{val} by {cat} (waterfall)")
    return fig


def fig_gauge(value, target, title):
    top = max(target * 1.5, value * 1.15, 1.0)
    gauge = dict(axis=dict(range=[min(0, value * 1.15), top]), bar=dict(color="#00b4d8"))
    if target > 0:
        gauge["threshold"] = dict(line=dict(color="#ff6b6b", width=4), value=target)
        gauge["steps"] = [dict(range=[0, target * .7], color="rgba(255,107,107,0.25)"),
                          dict(range=[target * .7, target], color="rgba(254,202,87,0.25)"),
                          dict(range=[target, top], color="rgba(56,232,168,0.25)")]
    ind = dict(mode="gauge+number" + ("+delta" if target else ""), value=value, title=dict(text=title),
               gauge=gauge)
    if target:
        ind["delta"] = dict(reference=target, relative=True, valueformat=".1%")
    fig = go.Figure(go.Indicator(**ind))
    fig.update_layout(height=380, margin=dict(l=30, r=30, t=70, b=20))
    return fig


def period_table(df, dax_col, val, agg, gran):
    rule = {"Month": "MS", "Quarter": "QS", "Year": "YS"}[gran]
    s = df.dropna(subset=[dax_col, val]).set_index(dax_col)[val].sort_index().resample(rule).agg(agg)
    s = s.fillna(0) if agg in ("sum", "count") else s.interpolate().ffill().bfill()
    lag = {"Month": 12, "Quarter": 4, "Year": 1}[gran]
    t = pd.DataFrame({"Start": s.index, "Value": s.values})
    t["Period"] = (t["Start"].dt.strftime("%b %Y") if gran == "Month" else
                   t["Start"].dt.year.astype(str) + " Q" + t["Start"].dt.quarter.astype(str) if gran == "Quarter"
                   else t["Start"].dt.year.astype(str))
    t["Previous period"] = t["Value"].shift(1)
    t["Change %"] = (t["Value"] - t["Previous period"]) / t["Previous period"].abs().replace(0, np.nan)
    t["Same period last year"] = t["Value"].shift(lag)
    t["YoY %"] = (t["Value"] - t["Same period last year"]) / t["Same period last year"].abs().replace(0, np.nan)
    if agg in ("sum", "count"):
        t["Year to date"] = t.groupby(t["Start"].dt.year)["Value"].cumsum()
    return t.drop(columns="Start")


def render_visuals(df, nums, dates, measure, default_agg):
    st.subheader("🧩 More Power BI style visuals")
    st.caption("Slicers in the sidebar apply here too.")
    if df.empty:
        st.warning("No rows match the slicers.")
        return
    d = _with_time(df, dates)
    cat_cols = [c for c in d.columns if c not in dates and c not in nums and d[c].nunique() <= 200
                and d[c].nunique() > 1]
    visuals = ["Matrix (pivot heatmap)", "Pareto (80/20)", "Waterfall", "Gauge vs target",
               "Period comparison (MoM / YoY)", "Top / Bottom N"]
    pick = st.selectbox("Visual", visuals, key="viz_pick")
    if not nums:
        st.info("These visuals need at least one number column.")
        return
    mi = nums.index(measure) if measure in nums else 0
    ai = _idx(AGG_CHOICES, default_agg)

    if pick == "Period comparison (MoM / YoY)":
        if not dates:
            st.info("This visual needs a date column.")
            return
        a, b, c, e = st.columns(4)
        dax_col = a.selectbox("Date column", dates, key="viz_pc_d")
        val = b.selectbox("Value", nums, index=mi, key="viz_pc_v")
        agg = c.selectbox("Calculation", AGG_CHOICES, index=ai, key="viz_pc_a")
        gran = e.selectbox("Period", ["Month", "Quarter", "Year"], key="viz_pc_g")
        t = period_table(d, dax_col, val, agg, gran)
        if len(t) < 2:
            st.warning("Not enough periods. Choose a smaller period (for example Month).")
            return
        last = t.iloc[-1]
        k1, k2, k3 = st.columns(3)
        k1.metric(f"{last['Period']}", short(last["Value"]),
                  None if pd.isna(last["Change %"]) else f"{last['Change %']:+.1%} vs previous")
        k2.metric("Same period last year", "n/a" if pd.isna(last["Same period last year"])
                  else short(last["Same period last year"]),
                  None if pd.isna(last["YoY %"]) else f"{last['YoY %']:+.1%} YoY")
        k3.metric("Periods in data", len(t))
        fig = go.Figure()
        fig.add_bar(x=t["Period"], y=t["Value"], name="This period")
        fig.add_scatter(x=t["Period"], y=t["Same period last year"], name="Same period last year",
                        mode="lines+markers", line=dict(color="#feca57"))
        fig.update_layout(height=460, margin=dict(l=20, r=20, t=50, b=20),
                          title=f"{agg.title()} of {val} per {gran.lower()}")
        st.plotly_chart(dark(fig), theme=None, **W_PLOT)
        shown = t.copy()
        for pc in ("Change %", "YoY %"):
            shown[pc] = (shown[pc] * 100).round(1)
        st.dataframe(shown.round(2), hide_index=True, **W_DF)
        return

    if not cat_cols:
        st.info("These visuals need a text column with 2 or more different values.")
        return
    if pick == "Matrix (pivot heatmap)":
        if len(cat_cols) < 2:
            st.info("The matrix needs two text columns that each have 2 or more different values "
                    "(with the current slicers there are fewer).")
            return
        a, b, c, e = st.columns(4)
        r_ = a.selectbox("Rows", cat_cols, key="viz_m_r")
        c_opts = [x for x in cat_cols if x != r_]
        c_ = b.selectbox("Columns", c_opts, key="viz_m_c")
        val = c.selectbox("Value", [ROWS] + nums, index=(1 + mi), key="viz_m_v")
        agg = e.selectbox("Calculation", AGG_CHOICES, index=ai, key="viz_m_a")
        dd, v2, ag2 = (d.assign(_n=1), "_n", "sum") if val == ROWS else (d, val, agg)
        p = dd.pivot_table(index=r_, columns=c_, values=v2, aggfunc=ag2)
        if p.empty:
            st.warning("Nothing to show for this combination.")
            return
        p = p.loc[p.sum(axis=1).sort_values(ascending=False).index[:20],
                  p.sum(axis=0).sort_values(ascending=False).index[:15]]
        p.index, p.columns = p.index.astype(str), p.columns.astype(str)
        fig = px.imshow(p, text_auto=".3s", aspect="auto", color_continuous_scale="Viridis")
        fig.update_layout(height=max(380, 28 * len(p) + 140), margin=dict(l=20, r=20, t=40, b=20),
                          title=f"{'Rows' if val == ROWS else val} by {r_} and {c_}")
        st.plotly_chart(dark(fig), theme=None, **W_PLOT)
        full = dd.pivot_table(index=r_, columns=c_, values=v2, aggfunc=ag2, margins=True,
                              margins_name="Total").round(2)
        st.dataframe(full, **W_DF)
        return

    a, b, c = st.columns(3)
    cat = a.selectbox("Category", cat_cols, key="viz_cat")
    val = b.selectbox("Value", nums, index=mi, key="viz_val")
    agg = c.selectbox("Calculation", AGG_CHOICES, index=ai, key="viz_agg")
    if pick == "Pareto (80/20)":
        fig, k80, n = fig_pareto(d, cat, val, agg)
        st.plotly_chart(dark(fig), theme=None, **W_PLOT)
        st.markdown(f"- **{k80} of {n}** {cat} values ({k80 / n:.0%}) make up about 80% of the total {val}.")
    elif pick == "Waterfall":
        st.plotly_chart(dark(fig_waterfall(d, cat, val, agg)), theme=None, **W_PLOT)
    elif pick == "Gauge vs target":
        v = float(d[val].agg(agg))
        tgt = st.number_input("Target", value=float(round(v * 1.1, 2)), key=f"viz_tgt_{val}_{agg}")
        st.plotly_chart(dark(fig_gauge(v, tgt, f"{agg.title()} of {val}")), theme=None, **W_PLOT)
        if tgt:
            st.markdown(f"- Current value is **{v / tgt:.0%}** of the target ({short(v)} of {short(tgt)}).")
    else:
        e, f = st.columns(2)
        n = e.slider("How many", 3, 30, 10, key="viz_n")
        mode = f.radio("Show", ["Top", "Bottom", "Both"], horizontal=True, key="viz_mode")
        s = d.groupby(cat)[val].agg(agg).sort_values(ascending=False)
        parts = {"Top": s.head(n), "Bottom": s.tail(n)[::-1],
                 "Both": pd.concat([s.head(n), s.tail(n)[::-1]]).loc[lambda x: ~x.index.duplicated()]}[mode]
        t = parts.reset_index()
        t.columns = [cat, "Value"]
        t.insert(0, "Rank", [int(s.index.get_loc(k)) + 1 for k in t[cat]])
        if agg in ("sum", "count") and s.sum():
            t["Share %"] = (t["Value"] / s.sum() * 100).round(1)
        fig = px.bar(t.iloc[::-1], x="Value", y=cat, orientation="h", text_auto=".3s",
                     color="Value", color_continuous_scale="Viridis")
        fig.update_layout(height=max(360, 30 * len(t) + 120), margin=dict(l=20, r=20, t=40, b=20),
                          yaxis_type="category", title=f"{mode} {len(t)} {cat} by {agg} of {val}")
        st.plotly_chart(dark(fig), theme=None, **W_PLOT)
        st.dataframe(t, hide_index=True, **W_DF)


# ---------------------------------------------------------------- DAX automation
DAX_AGG = {"sum": "SUM", "mean": "AVERAGE", "median": "MEDIAN", "count": "COUNTA", "max": "MAX",
           "min": "MIN", "nunique": "DISTINCTCOUNT"}
DAX_LABEL = {"sum": "Total", "mean": "Average", "median": "Median", "count": "Count of", "max": "Max",
             "min": "Min", "nunique": "Distinct"}
CAL_COLS = {"Date", "Year", "Quarter", "Month No", "Month", "Year Month"}


def dq(t):
    return "'" + str(t).replace("'", "''") + "'"


def dax_col(t, c):
    return f"{dq(t)}[{str(c).replace(']', ']]')}]"


def dmeas(n):
    return "[" + str(n).replace("]", "]]") + "]"


def dstr(s):
    return '"' + str(s).replace('"', '""') + '"'


def dagg(t, c, agg):
    return f"{DAX_AGG.get(agg, 'SUM')}({dax_col(t, c)})"


def dlabel(agg, c):
    return f"{DAX_LABEL.get(agg, 'Total')} {c}"


def _indent(text, n=4):
    return "\n".join((" " * n + ln) if ln else ln for ln in text.split("\n"))


def dax_filters(t, specs):
    """Slicer choices -> DAX filter arguments for CALCULATETABLE."""
    out = []
    for sp in specs:
        c = dax_col(t, sp["col"])
        if sp["kind"] == "date":
            hi = sp["hi"] + timedelta(days=1)
            out.append(f"{c} >= DATE({sp['lo'].year}, {sp['lo'].month}, {sp['lo'].day})")
            out.append(f"{c} < DATE({hi.year}, {hi.month}, {hi.day})")
        elif sp["kind"] == "range":
            out.append(f"{c} >= {sp['lo']}")
            out.append(f"{c} <= {sp['hi']}")
        elif sp["kind"] == "in":
            out.append(f"{c} IN {{" + ", ".join(dstr(v) for v in sp["values"]) + "}")
        elif sp["kind"] == "text":
            out.append(f"CONTAINSSTRING({c}, {dstr(sp['text'])})")
    return out


def _wrap(core, filters):
    if not filters:
        return core
    return "CALCULATETABLE(\n" + _indent(core) + ",\n" + _indent(",\n".join(filters)) + "\n)"


def dax_chart_query(t, cfg, filters, use_cal, date_cols):
    """DAX query (for DAX query view / DAX Studio) that returns the same table a dashboard chart plots."""
    typ, x, y, col, agg = cfg["type"], cfg["x"], cfg["y"], cfg.get("color"), cfg["agg"]
    if typ == "Histogram":
        return None
    if typ in ("Scatter", "Bubble", "3D scatter", "3D surface", "3D bar", "Box", "Violin"):
        cols = []
        for c in (x, y, col):
            if c and c not in cols:
                cols.append(c)
        sel = ", ".join(f"{dstr(c)}, {dax_col(t, c)}" for c in cols)
        return "EVALUATE\n" + _wrap(f"TOPN(1000, SELECTCOLUMNS({dq(t)}, {sel}))", filters)
    is_date = x in date_cols
    pie = typ in ("Pie", "Donut", "Treemap", "Sunburst", "Funnel")
    grp = ["'Calendar'[Year Month]" if (is_date and use_cal) else dax_col(t, x)]
    if col and col != x and not pie:
        grp.append(dax_col(t, col))
    vname = dlabel(agg, y)
    core = "SUMMARIZECOLUMNS(\n" + _indent(",\n".join(grp + [f"{dstr(vname)}, {dagg(t, y, agg)}"])) + "\n)"
    if not is_date:
        core = f"TOPN(\n    {int(cfg.get('topn', 12))},\n" + _indent(core) + f",\n    {dmeas(vname)}, DESC\n)"
    order = grp[0] + " ASC" if is_date else dmeas(vname) + " DESC"
    return "EVALUATE\n" + _wrap(core, filters) + "\nORDER BY " + order


def dax_kpi_query(t, kpis, filters):
    parts = []
    for col, agg in kpis:
        if col == "(row count)":
            parts.append(f'"Rows", COUNTROWS({dq(t)})')
        else:
            parts.append(f"{dstr(dlabel(agg, col))}, {dagg(t, col, agg)}")
    if not parts:
        return None
    return "EVALUATE\n" + _wrap("ROW(\n" + _indent(",\n".join(parts)) + "\n)", filters)


def dax_calendar(t, date_col):
    return ("VAR MinDate = MIN(" + dax_col(t, date_col) + ")\nVAR MaxDate = MAX(" + dax_col(t, date_col) + ")\n"
            "RETURN\nADDCOLUMNS(\n"
            "    CALENDAR(DATE(YEAR(MinDate), 1, 1), DATE(YEAR(MaxDate), 12, 31)),\n"
            '    "Year", YEAR([Date]),\n    "Quarter", "Q" & QUARTER([Date]),\n'
            '    "Month No", MONTH([Date]),\n    "Month", FORMAT([Date], "MMM"),\n'
            '    "Year Month", FORMAT([Date], "YYYY-MM")\n)')


def dax_measures(t, df, nums, dates, cats, measure, use_cal, target, custom):
    """Every measure worth having for this data: (section, name, expression)."""
    M = []
    add = lambda sec, name, expr: M.append((sec, name, expr))
    main = measure if measure in nums else (nums[0] if nums else None)
    add("Row counts", "Rows", f"COUNTROWS({dq(t)})")
    for c in cats[:3]:
        add("Row counts", f"Distinct {c}", f"DISTINCTCOUNT({dax_col(t, c)})")
    for c in ([main] if main else []) + [c for c in nums if c != main][:5]:
        add("Basic measures", f"Total {c}", f"SUM({dax_col(t, c)})")
        add("Basic measures", f"Average {c}", f"AVERAGE({dax_col(t, c)})")
        add("Basic measures", f"Min {c}", f"MIN({dax_col(t, c)})")
        add("Basic measures", f"Max {c}", f"MAX({dax_col(t, c)})")
    if main:
        tot = dmeas(f"Total {main}")
        add("Share and ranking", f"{main} % of grand total", f"DIVIDE({tot}, CALCULATE({tot}, ALL({dq(t)})))")
        for c in cats[:2]:
            add("Share and ranking", f"{main} share of selected {c}",
                f"DIVIDE({tot}, CALCULATE({tot}, ALLSELECTED({dax_col(t, c)})))")
            add("Share and ranking", f"{c} rank by {main}", f"RANKX(ALL({dax_col(t, c)}), {tot}, , DESC, DENSE)")
            add("Share and ranking", f"Top 5 {c} total {main}",
                f"CALCULATE({tot}, TOPN(5, ALL({dax_col(t, c)}), {tot}, DESC))")
        if dates and use_cal:
            cal = "'Calendar'[Date]"
            py = dmeas(f"{main} same period last year")
            pm = dmeas(f"{main} previous month")
            add("Time intelligence", f"{main} MTD", f"TOTALMTD({tot}, {cal})")
            add("Time intelligence", f"{main} QTD", f"TOTALQTD({tot}, {cal})")
            add("Time intelligence", f"{main} YTD", f"TOTALYTD({tot}, {cal})")
            add("Time intelligence", f"{main} same period last year", f"CALCULATE({tot}, SAMEPERIODLASTYEAR({cal}))")
            add("Time intelligence", f"{main} YoY %", f"DIVIDE({tot} - {py}, {py})")
            add("Time intelligence", f"{main} previous month", f"CALCULATE({tot}, DATEADD({cal}, -1, MONTH))")
            add("Time intelligence", f"{main} MoM %", f"DIVIDE({tot} - {pm}, {pm})")
            add("Time intelligence", f"{main} running total",
                f"CALCULATE({tot}, FILTER(ALL('Calendar'[Date]), 'Calendar'[Date] <= MAX('Calendar'[Date])))")
            add("Time intelligence", f"{main} 3-month average (per month)",
                f"DIVIDE(CALCULATE({tot}, DATESINPERIOD({cal}, MAX({cal}), -3, MONTH)), 3)")
        if target:
            tg = dmeas(f"Target {main}")
            add("Target and status", f"Target {main}", repr(float(target)))
            add("Target and status", f"{main} vs target", f"{tot} - {tg}")
            add("Target and status", f"{main} vs target %", f"DIVIDE({tot} - {tg}, {tg})")
            add("Target and status", f"{main} status", f'IF({tot} >= {tg}, "On target", "Below target")')
    for c in custom:
        add("Your custom measures", c["name"], c["expr"])
    return M


def dax_measures_text(t, df, dates, measures, use_cal):
    blocks = []
    if dates and use_cal:
        blocks.append("// ===== Calendar table (Modeling > New table) =====\n// Then: Table tools > Mark as date table "
                      f"(column Date), and relate 'Calendar'[Date] to {dax_col(t, dates[0])}.\nCalendar =\n"
                      + dax_calendar(t, dates[0]))
    sec = None
    for s, name, expr in measures:
        if s != sec:
            blocks.append(f"// ===== {s} =====")
            sec = s
        blocks.append(f"{name} =\n{_indent(expr)}" if "\n" in expr else f"{name} = {expr}")
    return "\n\n".join(blocks)


M_TYPES = {"i": "Int64.Type", "u": "Int64.Type", "f": "type number", "b": "type logical"}


def power_query_m(path, df):
    """Power Query (M) script that loads the cleaned CSV with the right column types."""
    steps = []
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_datetime64_any_dtype(s):
            ty = "type date" if (s.dropna() == s.dropna().dt.normalize()).all() else "type datetime"
        elif pd.api.types.is_bool_dtype(s):
            ty = "type logical"
        elif pd.api.types.is_numeric_dtype(s):
            ty = M_TYPES.get(s.dtype.kind, "type number")
        else:
            ty = "type text"
        steps.append("{" + '"' + str(c).replace('"', '""') + '", ' + ty + "}")
    return ("let\n"
            f'    Source = Csv.Document(File.Contents("{path}"), [Delimiter=",", Columns={len(df.columns)}, '
            "Encoding=65001, QuoteStyle=QuoteStyle.Csv]),\n"
            "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),\n"
            "    Typed = Table.TransformColumnTypes(Promoted, {\n        " + ",\n        ".join(steps) + "\n    })\n"
            "in\n    Typed")


def check_dax(text, table, columns, measure_names=()):
    """Quick sanity check of a DAX formula: brackets, quotes and column names. Returns warnings."""
    warns = []
    no_str = re.sub(r'"(?:[^"]|"")*"', '""', text)
    if no_str.count("(") != no_str.count(")"):
        warns.append("The parentheses ( ) are not balanced.")
    if no_str.count("{") != no_str.count("}"):
        warns.append("The braces { } are not balanced.")
    if text.count('"') % 2:
        warns.append('A text "quote" is not closed.')
    known = set(columns)
    for tb, col in re.findall(r"'((?:[^']|'')+)'\[((?:[^\]]|\]\])+)\]", no_str):
        tb = tb.replace("''", "'")
        col = col.replace("]]", "]")
        if tb == table and col not in known:
            warns.append(f"Column [{col}] does not exist in table '{table}'.")
        elif tb == "Calendar" and col not in CAL_COLS:
            warns.append(f"Column [{col}] is not part of the generated Calendar table.")
        elif tb not in (table, "Calendar"):
            warns.append(f"Table '{tb}' is not in this model (expected '{table}').")
    bare = re.sub(r"'(?:[^']|'')+'\[(?:[^\]]|\]\])+\]", "", no_str)
    names = set(measure_names) | known
    for m in re.findall(r"\[((?:[^\]]|\]\])+)\]", bare):
        m = m.replace("]]", "]")
        if m not in names and m not in CAL_COLS:
            warns.append(f"[{m}] is not a known measure or column (ignore this if it is a VAR or a new name).")
    return list(dict.fromkeys(warns))


def build_bi_pack(files):
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for fname, content in files.items():
            z.writestr(fname, content)
    return buf.getvalue()


PACK_HOWTO = """DataPilot AI -> Power BI pack
=============================

Files
  cleaned_data.csv   your cleaned data
  load_data.m        Power Query (M) script that loads the CSV with correct column types
  measures.dax       Calendar table + measures (copy one block at a time)
  queries.dax        DAX queries that return the same tables as your dashboard charts

Steps in Power BI Desktop
  1. Home > Transform data > New source > Blank query > Advanced editor.
     Paste load_data.m and EDIT THE FILE PATH on the Source line. Name the query: {table}.
     Close & Apply.
  2. (Time intelligence) Modeling > New table: paste the "Calendar" block from measures.dax.
     Table tools > Mark as date table > Date. Create a relationship Calendar[Date] -> {date}.
  3. Modeling > New measure: paste each measure from measures.dax (or use Tabular Editor to paste many).
  4. Open DAX query view (or DAX Studio), paste any query from queries.dax and Run.
"""


def render_dax(df, bdf, nums, dates, cats, measure, name, slicer_specs):
    st.subheader("🧮 DAX automation for Power BI")
    st.caption("Writes the measures, queries and data-loading script for you, based on your data, your "
               "dashboard charts and your slicers. Copy them into Power BI Desktop, or download the pack.")
    stem = re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9]+", " ", name.rsplit(".", 1)[0])).strip().title() or "Data"
    c1, c2, c3 = st.columns([2, 2, 2])
    t = c1.text_input("Table name in Power BI", value=stem, key="dax_table").strip() or "Data"
    use_cal = c2.checkbox("Use a Calendar table for time intelligence", value=bool(dates), key="dax_cal",
                          disabled=not dates)
    use_sl = c3.checkbox("Apply my slicers to the queries", value=True, key="dax_sl")
    main = measure if measure in nums else (nums[0] if nums else None)
    target = 0.0
    if main:
        target = st.number_input(f"Target for {main} (optional, 0 = none)", value=0.0, key="dax_target")

    custom = st.session_state.setdefault("dax_custom", [])
    with st.expander("➕ Build your own measure"):
        kinds = ["Ratio of two columns", "Difference of two columns", "Total where a category equals a value",
                 "Share of total for one category value"]
        k = st.selectbox("Type", kinds, key="dax_ck")
        nm = st.text_input("Measure name", key="dax_cn")
        expr = None
        if k.startswith(("Ratio", "Difference")) and len(nums) >= 2:
            a, b = st.columns(2)
            c_a = a.selectbox("First column", nums, key="dax_ca")
            c_b = b.selectbox("Second column", nums, index=1, key="dax_cb")
            expr = (f"DIVIDE(SUM({dax_col(t, c_a)}), SUM({dax_col(t, c_b)}))" if k.startswith("Ratio")
                    else f"SUM({dax_col(t, c_a)}) - SUM({dax_col(t, c_b)})")
        elif k.startswith(("Total where", "Share")) and cats and main:
            a, b = st.columns(2)
            c_c = a.selectbox("Category column", cats, key="dax_cc")
            c_v = b.selectbox("Value", sorted(df[c_c].dropna().astype(str).unique())[:200], key="dax_cv")
            cond = f"CALCULATE(SUM({dax_col(t, main)}), {dax_col(t, c_c)} = {dstr(c_v)})"
            expr = cond if k.startswith("Total") else f"DIVIDE({cond}, SUM({dax_col(t, main)}))"
        else:
            st.caption("This measure type needs more number or category columns than your data has.")
        b1, b2 = st.columns(2)
        if b1.button("Add measure", key="dax_cadd", disabled=not (nm.strip() and expr), **W_BTN):
            custom.append(dict(name=nm.strip(), expr=expr))
        if custom and b2.button("Clear my measures", key="dax_cclear", **W_BTN):
            custom.clear()

    measures = dax_measures(t, df, nums, dates, cats, measure, use_cal and bool(dates), target, custom)
    m_text = dax_measures_text(t, df, dates, measures, use_cal and bool(dates))
    filters = dax_filters(t, slicer_specs) if use_sl else []
    cfgs = st.session_state.get("bi_cfgs", [])
    queries = []
    kp = [(st.session_state.get(f"kpi_c{i}"), st.session_state.get(f"kpi_a{i}"))
          for i in range(int(st.session_state.get("kpi_n", 0)))]
    kq = dax_kpi_query(t, [(c, a) for c, a in kp if c and a], filters)
    if kq:
        queries.append(("KPI cards", kq))
    for i, cfg in enumerate(cfgs):
        try:
            q = dax_chart_query(t, cfg, filters, use_cal and bool(dates), dates)
        except Exception:
            q = None
        if q:
            queries.append((f"Chart {i + 1}: {cfg.get('title') or cfg['type'] + ' - ' + str(cfg['x'])}", q))
    queries.append(("Preview the table", "EVALUATE\nTOPN(100, " + dq(t) + ")"))
    q_text = "\n\n".join(f"// ===== {ttl} =====\n{q}" for ttl, q in queries)
    m_code = power_query_m(r"C:\Users\YourName\Downloads\cleaned_data.csv", df)

    k1, k2, k3 = st.columns(3)
    k1.metric("Measures written", len(measures))
    k2.metric("Queries written", len(queries))
    k3.metric("Filter conditions in queries", len(filters))
    tabs = st.tabs(["Measures", "Queries", "Power Query (M)", "AI DAX helper", "Download pack"])
    with tabs[0]:
        st.code(m_text, language="sql")
    with tabs[1]:
        if not cfgs:
            st.info("Open the 📊 Power BI tab first: a query is written for each chart you build there.")
        if use_cal and dates and any(c["x"] in dates for c in cfgs):
            st.caption("Charts over time group by 'Calendar'[Year Month], so the Calendar table and its "
                       "relationship are needed.")
        st.code(q_text, language="sql")
    with tabs[2]:
        st.caption("Edit the file path on the Source line. The cleaned CSV is in the Download tab and in the pack.")
        st.code(m_code, language="text")
    with tabs[3]:
        eng = st.session_state.get("ai_engine", AI_ENGINES[0])
        st.caption(f"Describe the calculation in plain words. Uses the AI engine chosen in the 🤖 Ask AI tab "
                   f"({eng}); the answer is checked against your real column names.")
        ask = st.text_area("What should the measure calculate?", key="dax_ask",
                           value=f"Year-over-year growth of {main}" if main else "")
        if st.button("Write DAX", key="dax_ai_btn", **W_BTN):
            schema = "; ".join(f"{c} ({str(df[c].dtype)})" for c in df.columns)
            system = ("You are an expert Power BI / DAX developer. Table: " + dq(t) + " with columns: " + schema +
                      ". Existing measures: " + ", ".join(m[1] for m in measures[:40]) + ". "
                      + ("A 'Calendar' table exists with columns Date, Year, Quarter, Month No, Month, Year Month, "
                         "related to the main date column. " if (dates and use_cal) else "")
                      + "Reply with ONE measure in a ```dax code block written as `Measure name = expression`, "
                        "then at most two short sentences of explanation. Use only the columns listed.")
            with st.spinner("Writing DAX..."):
                try:
                    st.session_state["dax_ai"] = llm_chat(
                        system, ask, eng, st.session_state.get("ai_key", ""),
                        st.session_state.get("ai_model", CLAUDE_MODEL))
                except requests.exceptions.ConnectionError:
                    st.error("Could not reach the AI engine. Start Ollama or check your internet connection.")
                except Exception as exc:
                    st.error(str(exc))
        ans = st.session_state.get("dax_ai")
        if ans:
            m = re.search(r"```(?:dax|sql)?\s*\n(.*?)```", ans, re.S)
            code = m.group(1).strip() if m else ans.strip()
            st.code(code, language="sql")
            body = code.split("=", 1)[1] if "=" in code else code
            warns = check_dax(body, t, list(df.columns), [mm[1] for mm in measures])
            for w in warns:
                st.warning(w)
            if not warns:
                st.success("Checked: brackets, quotes and column names look right.")
            rest = (ans[:m.start()] + ans[m.end():]).strip() if m else ""
            if rest:
                st.markdown(rest)
    with tabs[4]:
        st.caption("One ZIP with your cleaned data, the Power Query script, all measures, all queries and "
                   "step-by-step instructions.")
        files = {"cleaned_data.csv": df.to_csv(index=False), "load_data.m": m_code, "measures.dax": m_text,
                 "queries.dax": q_text,
                 "HOW_TO_USE.txt": PACK_HOWTO.format(table=t, date=dax_col(t, dates[0]) if dates else "your date column")}
        sig = hashlib.md5((m_text + q_text + m_code + str(df.shape)).encode()).hexdigest()
        lazy_file("Power BI pack (.zip)", "zip", sig, lambda: build_bi_pack(files), "powerbi_pack.zip",
                  "application/zip")



# ======================================================================
# Forecast (simple trend line, optionally with a repeating seasonal pattern)
# ======================================================================
def make_forecast(values, periods, season=0):
    """Straight-line trend (+ optional seasonal pattern) with an approximate 95% range."""
    y = np.asarray(values, dtype=float)
    n = len(y)
    x = np.arange(n)
    slope, icpt = np.polyfit(x, y, 1)
    fitted = icpt + slope * x
    pat = None
    if season and n >= 2 * season:
        resid = y - fitted
        pat = np.array([resid[i::season].mean() for i in range(season)])
        pat = pat - pat.mean()
        fitted = fitted + pat[x % season]
    sd = float(np.std(y - fitted, ddof=2 if n > 2 else 0))
    xf = np.arange(n, n + periods)
    pred = icpt + slope * xf + (pat[xf % season] if pat is not None else 0)
    band = 1.96 * sd * np.sqrt(1 + (xf - n + 1) / n)          # range widens further ahead
    return dict(slope=float(slope), fitted=fitted, pred=pred, lower=pred - band, upper=pred + band,
                seasonal=pat is not None)


# ======================================================================
# DATABASE, ACCOUNTS AND FILE STORAGE  (all of it lives in datapilot_db.py)
# ----------------------------------------------------------------------
#   users             Accounts: hashed passwords, lock-out counter, admin flag
#   projects          Saved analysis projects and dataset metadata
#   chat_messages     AI conversation history
#   reports           Report details and file-storage references
#   uploads           Original files the user uploaded (CSV / Excel / JSON / SQLite)
#   user_settings     User preferences and dashboard settings
#   analysis_history  Cleaning summaries, KPIs, and analysis results
#   file_store        File bytes when DATAPILOT_STORAGE=db
# Every helper takes the signed-in user's id and only ever touches that user's rows and files.
# ======================================================================
AGG_CHOICES = ["sum", "mean", "median", "count", "max", "min"]
PPT_STYLES = ["Dark (Power BI)", "Light"]
REPORT_LABEL = {"xlsx": "Excel", "pptx": "PowerPoint", "pdf": "PDF", "html": "HTML page",
                "zip": "Power BI pack"}
MIME = {".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pdf": "application/pdf", ".csv": "text/csv", ".html": "text/html",
        ".zip": "application/zip"}

from datapilot_db import (                                                   # noqa: E402
    DEFAULT_SETTINGS, SETTING_COLS, THEME_KEYS, AuthError, add_analysis, add_chat, authenticate,
    backend_label, change_password, clear_chat, db_counts, delete_account, delete_report, delete_upload,
    get_chat, get_settings, get_user, init_db, legacy_account_exists, list_analysis, list_projects,
    list_reports, list_uploads, load_project, read_report, read_upload, register_user, save_project,
    save_settings, save_upload)


def save_report(uid, pid, key, filename, data):
    """Keep a generated report in the user's history (a failure only shows a warning)."""
    try:
        dpdb.save_report(uid, pid, REPORT_LABEL.get(key, key), filename, data)
    except Exception as exc:
        st.warning(f"Report built, but it could not be saved to your history: {exc}")


def delete_project(uid, pid):
    dpdb.delete_project(uid, pid)
    sp = st.session_state.get("saved_pid")
    if sp and sp[1] == pid:
        st.session_state.pop("saved_pid", None)


def clear_all_data(uid):
    dpdb.clear_all_data(uid)
    st.session_state.pop("saved_pid", None)


def S():
    """Current user's settings (falls back to defaults)."""
    return {**DEFAULT_SETTINGS, **(st.session_state.get("settings") or {})}


def _idx(options, value):
    return options.index(value) if value in options else 0


def current_pid(source_name):
    """The saved project that matches the data currently on screen (or None)."""
    sp = st.session_state.get("saved_pid")
    return sp[1] if sp and sp[0] == source_name else None


def flex_top(landing, username=None):
    """Flex look: nav bar, dark-mode switch (the pull-cord clicks it) and the hero + doors, or a slim header."""
    now = pd.Timestamp.now()
    c1, c2 = st.columns([9, 1.5], vertical_alignment="center")
    with c1:
        st.markdown(flex.nav_html(now.strftime("%I:%M%p").lstrip("0").lower(), f"{now.day} {now:%B}, {now.year}"),
                    unsafe_allow_html=True)
    with c2:
        st.toggle("Dark mode", value=bool(S().get("flex_dark", True)), key="flex_dark")
    if landing:
        st.markdown(flex.hero_html(), unsafe_allow_html=True)
        st.markdown(flex.doors_html(), unsafe_allow_html=True)
        if username is not None:
            st.markdown(flex.steps_html(), unsafe_allow_html=True)
    else:
        st.markdown(flex.compact_html(username or ""), unsafe_allow_html=True)


def logout():
    """Forget the signed-in user and everything cached for them in this browser session."""
    st.session_state.clear()
    st.rerun()


# ======================================================================
# ANALYST TOOLKIT: quality, cleaning recipe, pivot, statistical tests, regression, segments, outliers, SQL
# (the maths lives in datapilot_tools.py)
# ======================================================================
quality_cached = st.cache_data(show_spinner=False, max_entries=8)(tools.quality_report)

TX_OPS = ["Remove duplicate rows", "Drop columns", "Rename a column", "Remove rows with empty values",
          "Fill empty cells", "Change column type", "Clean text", "Filter rows", "Remove outliers",
          "New calculated column", "Group numbers into bins", "Split a date (year, month...)"]


def _csv_btn(label, frame, fname, key, index=False):
    st.download_button(label, frame.to_csv(index=index).encode("utf-8-sig"), fname, "text/csv", key=key, **W_DL)


def data_chips(name, df, dates):
    q = quality_cached(df)
    dot = "🟢" if q["score"] >= 75 else "🟠" if q["score"] >= 55 else "🔴"
    chips = [f"📄 {esc(str(name))}", f"🧱 {len(df):,} rows × {len(df.columns)} columns",
             f"{dot} Data quality {q['score']}/100 · {q['grade']}"]
    if dates:
        d = df[dates[0]].dropna()
        if len(d):
            chips.append(f"📅 {d.min():%d %b %Y} → {d.max():%d %b %Y}")
    st.markdown('<div class="chips">' + "".join(f'<span class="chip">{c}</span>' for c in chips) + "</div>",
                unsafe_allow_html=True)


def tk_quality(df):
    q = quality_cached(df)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Quality score", f"{q['score']}/100", q["grade"], delta_color="off")
    c2.metric("Duplicate rows", f"{q['duplicates']:,}")
    c3.metric("Empty cells", f"{int(df.isna().sum().sum()):,}")
    c4.metric("Outliers", f"{int(q['outliers']['Outliers'].sum()) if len(q['outliers']) else 0:,}")
    st.progress(q["score"] / 100)
    st.markdown("**What I found**")
    for line in q["issues"]:
        st.markdown("- " + line)
    st.caption("Fix problems in the 🧼 Clean & transform tab. The score drops for empty cells, duplicates, "
               "outliers, constant columns and numbers stored as text.")
    miss = q["columns"][q["columns"]["Missing"] > 0]
    if len(miss):
        st.plotly_chart(dark(px.bar(miss.sort_values("Missing %"), x="Missing %", y="Column", orientation="h",
                                    title="Empty cells by column (%)")), theme=None, **W_PLOT)
    st.markdown("**Every column at a glance**")
    st.dataframe(q["columns"], hide_index=True, **W_DF)
    if len(q["outliers"]):
        st.markdown("**Outliers per numeric column** (IQR rule)")
        st.dataframe(q["outliers"], hide_index=True, **W_DF)


def tk_clean(df, nums, dates, cats):
    steps = st.session_state.setdefault("tx_steps", [])
    st.caption("Build a cleaning recipe one step at a time. Every tab in the app updates straight away. "
               "Your uploaded file is never changed. Saved steps reset when you load different data.")
    cols = list(df.columns)
    op = st.selectbox("What do you want to do?", TX_OPS, key="tx_op")
    step = None
    if op == "Remove duplicate rows":
        step = {"op": "drop_duplicates"}
    elif op == "Drop columns":
        c = st.multiselect("Columns to drop", cols, key="tx_dc")
        step = {"op": "drop_columns", "cols": c} if c else None
    elif op == "Rename a column":
        a, b = st.columns(2)
        old = a.selectbox("Column", cols, key="tx_rn_old")
        new = b.text_input("New name", key="tx_rn_new")
        step = {"op": "rename", "old": old, "new": new} if new.strip() else None
    elif op == "Remove rows with empty values":
        c = st.multiselect("Only look at these columns (leave empty = any column)", cols, key="tx_dn")
        step = {"op": "dropna", "cols": c}
    elif op == "Fill empty cells":
        a, b, c3 = st.columns(3)
        col = a.selectbox("Column", cols, key="tx_fl_col")
        how = b.selectbox("Fill with", ["mean", "median", "mode", "zero", "ffill", "bfill", "value"],
                          format_func=lambda x: {"mean": "average", "median": "median", "mode": "most common",
                                                 "zero": "0", "ffill": "value above", "bfill": "value below",
                                                 "value": "a value I type"}[x], key="tx_fl_how")
        val = c3.text_input("Value", key="tx_fl_val") if how == "value" else ""
        step = {"op": "fillna", "col": col, "how": how, "value": val}
    elif op == "Change column type":
        a, b = st.columns(2)
        col = a.selectbox("Column", cols, key="tx_ty_col")
        to = b.selectbox("Make it", ["number", "date", "text"], key="tx_ty_to")
        step = {"op": "astype", "col": col, "to": to}
    elif op == "Clean text":
        a, b = st.columns(2)
        col = a.selectbox("Column", cols, key="tx_tx_col")
        how = b.selectbox("Action", ["trim", "lower", "upper", "title"],
                          format_func=lambda x: {"trim": "remove extra spaces", "lower": "lowercase",
                                                 "upper": "UPPERCASE", "title": "Title Case"}[x], key="tx_tx_how")
        step = {"op": "text", "col": col, "how": how}
    elif op == "Filter rows":
        a, b, c3 = st.columns(3)
        col = a.selectbox("Column", cols, key="tx_fi_col")
        cmp_ = b.selectbox("Keep rows where it", tools.CMP_OPS, key="tx_fi_cmp")
        val = c3.text_input("Value (a list for 'is one of', comma separated)", key="tx_fi_val") \
            if cmp_ not in ("is empty", "is not empty") else ""
        step = {"op": "filter", "col": col, "cmp": cmp_, "value": val}
    elif op == "Remove outliers":
        a, b, c3 = st.columns(3)
        col = a.selectbox("Column", nums or cols, key="tx_ou_col")
        meth = b.selectbox("Method", ["iqr", "z"], format_func=lambda x: "IQR rule" if x == "iqr" else "Z-score",
                           key="tx_ou_m")
        k = c3.number_input("Strictness (IQR 1.5 / Z 3)", 0.5, 10.0, 1.5 if meth == "iqr" else 3.0, 0.5,
                            key="tx_ou_k")
        step = {"op": "outliers", "col": col, "method": meth, "k": k}
    elif op == "New calculated column":
        a, b = st.columns([1, 2])
        name_ = a.text_input("New column name", key="tx_ca_name")
        expr = b.text_input("Formula", key="tx_ca_expr", placeholder="[Unit Price] * Quantity * 1.18",
                            help="Use column names, or [Column Name] when it has spaces. "
                                 "Allowed: + - * / % ** and abs, log, sqrt, exp, round.")
        step = {"op": "calc", "name": name_, "expr": expr} if name_.strip() and expr.strip() else None
    elif op == "Group numbers into bins":
        a, b, c3 = st.columns(3)
        col = a.selectbox("Numeric column", nums or cols, key="tx_bi_col")
        nb = b.slider("Groups", 2, 10, 4, key="tx_bi_n")
        how = c3.selectbox("Split", ["equal-width", "quantile"], key="tx_bi_how",
                           format_func=lambda x: "equal ranges" if x == "equal-width" else "equal-sized groups")
        step = {"op": "bin", "col": col, "bins": nb, "how": how}
    else:
        a, b = st.columns(2)
        col = a.selectbox("Date column", dates or cols, key="tx_dp_col")
        part = b.selectbox("Part", ["year", "quarter", "month", "month name", "week", "weekday", "day", "hour"],
                           key="tx_dp_part")
        step = {"op": "datepart", "col": col, "part": part}
    if st.button("➕ Add this step", key="tx_add", disabled=step is None, **W_BTN):
        steps.append(step)
        st.rerun()

    st.markdown(f"**Your recipe** ({len(steps)} step{'s' if len(steps) != 1 else ''})")
    for _, msg in st.session_state.get("tx_errors", []):
        st.warning(msg)
    if not steps:
        st.caption("No steps yet. The data is shown as loaded (plus the automatic tidy-up).")
    for i, s in enumerate(steps):
        a, b = st.columns([9, 1])
        a.markdown(f"**{i + 1}.** {esc(tools.describe_step(s))}")
        if b.button("✕", key=f"tx_rm_{i}", help="Remove this step"):
            steps.pop(i)
            st.rerun()
    if steps:
        a, b, _ = st.columns([1, 1, 3])
        if a.button("↩️ Undo last", key="tx_undo", **W_BTN):
            steps.pop()
            st.rerun()
        if b.button("🗑️ Clear all", key="tx_clear", **W_BTN):
            steps.clear()
            st.rerun()
    st.divider()
    st.caption(f"Result: {len(df):,} rows × {len(df.columns)} columns")
    _csv_btn("⬇️ Download the cleaned data (CSV)", df, "cleaned_data.csv", "tx_dl")


def tk_pivot(df, nums, cats):
    a, b, c3, d4 = st.columns(4)
    rows = a.multiselect("Rows", list(df.columns), default=cats[:1], key="pv_rows")
    colsel = b.multiselect("Columns (optional)", [c for c in df.columns if c not in rows], key="pv_cols")
    agg = c3.selectbox("Calculate", ["sum", "mean", "median", "count", "max", "min"], key="pv_agg")
    val = d4.selectbox("Values", (nums or list(df.columns)) if agg != "count" else list(df.columns), key="pv_val")
    totals = st.checkbox("Show totals", True, key="pv_tot")
    if not rows:
        st.info("Pick at least one field for the rows.")
        return
    try:
        pv = tools.pivot(df, rows, colsel, val, agg, totals)
    except Exception as exc:
        st.error(f"Could not build the pivot table: {exc}")
        return
    shown = pv.round(2)
    st.dataframe(shown, **W_DF)
    body = pv.drop(index="Total", errors="ignore").drop(columns="Total", errors="ignore")
    if colsel and body.shape[0] > 1 and body.shape[1] > 1 and body.shape[0] * body.shape[1] <= 2500:
        hm = body.copy()
        hm.index, hm.columns = hm.index.astype(str), [str(c) for c in hm.columns]
        st.plotly_chart(dark(px.imshow(hm, aspect="auto", color_continuous_scale="Viridis", text_auto=".3s",
                                       title=f"{agg.title()} of {val}")), theme=None, **W_PLOT)
    elif not colsel and body.shape[0] > 1 and len(rows) == 1:
        g = body.reset_index()
        g.columns = [str(c) for c in g.columns]
        st.plotly_chart(dark(px.bar(g, x=g.columns[0], y=g.columns[-1], title=f"{agg.title()} of {val}")),
                        theme=None, **W_PLOT)
    _csv_btn("⬇️ Download pivot table (CSV)", pv.reset_index() if pv.index.nlevels else pv, "pivot.csv", "pv_dl")


def _stat_card(r, rows, neutral=False):
    cols = st.columns(len(rows))
    for c, (k, v) in zip(cols, rows):
        c.metric(k, v)
    if not neutral and r["p"] < st.session_state.get("st_alpha", 0.05):
        st.success(r["text"])
    else:
        st.info(r["text"])


def tk_tests(df, nums, cats):
    alpha = st.select_slider("Significance level (alpha)", [0.01, 0.025, 0.05, 0.1], value=0.05, key="st_alpha")
    kinds = ["Compare 2 groups (t-test)", "Compare 3+ groups (ANOVA)", "Two categories linked? (Chi-square)",
             "Do two numbers move together? (Correlation)", "Is a column normal?", "A/B test (conversion rates)"]
    kind = st.selectbox("Which question do you want to answer?", kinds, key="st_kind")
    try:
        if kind == kinds[0]:
            if not nums or not cats:
                st.info("Needs a numeric column and a column with groups.")
                return
            a, b = st.columns(2)
            val = a.selectbox("Numbers to compare", nums, key="t2_val")
            gc = b.selectbox("Group column", cats, key="t2_grp")
            lv = sorted(df[gc].dropna().astype(str).unique())
            if len(lv) < 2:
                st.info("The group column needs at least 2 different values.")
                return
            c1, c2, c3 = st.columns(3)
            ga = c1.selectbox("Group A", lv, index=0, key="t2_a")
            gb = c2.selectbox("Group B", lv, index=1, key="t2_b")
            meth = c3.radio("Test", ["Welch t-test", "Paired t-test", "Mann-Whitney (not normal data)"], key="t2_m")
            xa = df.loc[df[gc].astype(str) == ga, val]
            xb = df.loc[df[gc].astype(str) == gb, val]
            r = tools.mann_whitney(xa, xb, alpha) if meth.startswith("Mann") else \
                tools.ttest(xa, xb, meth.startswith("Paired"), alpha)
            if "mean_a" in r:
                _stat_card(r, [(f"Average {ga}", f"{r['mean_a']:,.2f}"), (f"Average {gb}", f"{r['mean_b']:,.2f}"),
                               ("Difference (A − B)", f"{r['diff']:,.2f}"), ("p-value", f"{r['p']:.4g}")])
                st.caption(f"{r['test']} · {int(100 * (1 - alpha))}% confidence interval of the difference: "
                           f"{r['ci'][0]:,.2f} to {r['ci'][1]:,.2f} · {r['effect_name']} = {r['effect']:.2f}")
            else:
                _stat_card(r, [(f"Median {ga}", f"{r['median_a']:,.2f}"), (f"Median {gb}", f"{r['median_b']:,.2f}"),
                               ("p-value", f"{r['p']:.4g}"), (r["effect_name"], f"{r['effect']:.2f}")])
            sub = df[df[gc].astype(str).isin([ga, gb])]
            st.plotly_chart(dark(px.box(sub, x=gc, y=val, color=gc, points="all",
                                        title=f"{val} by {gc}")), theme=None, **W_PLOT)
        elif kind == kinds[1]:
            if not nums or not cats:
                st.info("Needs a numeric column and a column with groups.")
                return
            a, b = st.columns(2)
            val = a.selectbox("Numbers to compare", nums, key="an_val")
            gc = b.selectbox("Group column", cats, key="an_grp")
            if df[gc].nunique() > 20:
                st.info("That column has more than 20 groups. Pick one with fewer.")
                return
            r = tools.anova({k: v[val] for k, v in df.groupby(gc)}, alpha)
            _stat_card(r, [("F statistic", f"{r['statistic']:.2f}"), ("p-value", f"{r['p']:.4g}"),
                           (r["effect_name"], f"{r['effect']:.3f}"), ("Kruskal-Wallis p", f"{r['kruskal_p']:.4g}")])
            st.dataframe(r["table"].round(3), hide_index=True, **W_DF)
            st.plotly_chart(dark(px.box(df, x=gc, y=val, color=gc, title=f"{val} by {gc}")), theme=None, **W_PLOT)
        elif kind == kinds[2]:
            if len(cats) < 2:
                st.info("Needs two columns with categories.")
                return
            a, b = st.columns(2)
            ca = a.selectbox("First column", cats, key="ch_a")
            cb = b.selectbox("Second column", [c for c in cats if c != ca], key="ch_b")
            r = tools.chi_square(df, ca, cb, alpha)
            _stat_card(r, [("Chi-square", f"{r['statistic']:.2f}"), ("p-value", f"{r['p']:.4g}"),
                           ("Degrees of freedom", r["dof"]), (r["effect_name"], f"{r['effect']:.3f}")])
            if r["warning"]:
                st.warning(r["warning"])
            st.dataframe(r["table"], **W_DF)
            st.plotly_chart(dark(px.imshow(r["table"], text_auto=True, aspect="auto",
                                           color_continuous_scale="Viridis", title="Counts")), theme=None, **W_PLOT)
        elif kind == kinds[3]:
            if len(nums) < 2:
                st.info("Needs two numeric columns.")
                return
            a, b, c3 = st.columns(3)
            x = a.selectbox("X", nums, key="co_x")
            y = b.selectbox("Y", [c for c in nums if c != x], key="co_y")
            m = c3.selectbox("Method", ["pearson", "spearman", "kendall"], key="co_m")
            r = tools.correlation_test(df[x], df[y], m, alpha)
            ci = f"{r['ci'][0]:.2f} to {r['ci'][1]:.2f}" if r["ci"] else "n/a"
            _stat_card(r, [("Correlation r", f"{r['statistic']:.3f}"), ("p-value", f"{r['p']:.4g}"),
                           ("Pairs used", f"{r['n']:,}"), ("95% range of r", ci)])
            d = df[[x, y]].dropna()
            fig = px.scatter(d, x=x, y=y, opacity=.6, title=f"{y} vs {x}")
            if len(d) > 2:
                k, i0 = np.polyfit(d[x].astype(float), d[y].astype(float), 1)
                xs = np.array([d[x].min(), d[x].max()], dtype=float)
                fig.add_trace(go.Scatter(x=xs, y=k * xs + i0, mode="lines", name="trend",
                                         line=dict(color="#feca57", width=3)))
            st.plotly_chart(dark(fig), theme=None, **W_PLOT)
        elif kind == kinds[4]:
            if not nums:
                st.info("Needs a numeric column.")
                return
            col = st.selectbox("Column", nums, key="no_col")
            r = tools.normality(df[col], alpha)
            _stat_card(r, [("W statistic", f"{r['statistic']:.4f}"), ("p-value", f"{r['p']:.4g}"),
                           ("Skew", f"{r['skew']:.2f}"), ("Kurtosis", f"{r['kurtosis']:.2f}")], neutral=True)
            st.plotly_chart(dark(px.histogram(df, x=col, marginal="box", title=f"Distribution of {col}")),
                            theme=None, **W_PLOT)
        else:
            st.markdown("**A/B test result**")
            c1, c2 = st.columns(2)
            na = c1.number_input("A: visitors", 1, 100_000_000, 1000, key="ab_na")
            ca_ = c1.number_input("A: conversions", 0, 100_000_000, 100, key="ab_ca")
            nb = c2.number_input("B: visitors", 1, 100_000_000, 1000, key="ab_nb")
            cb_ = c2.number_input("B: conversions", 0, 100_000_000, 130, key="ab_cb")
            r = tools.ab_test(int(ca_), int(na), int(cb_), int(nb), alpha)
            _stat_card(r, [("Rate A", f"{r['rate_a']:.2%}"), ("Rate B", f"{r['rate_b']:.2%}"),
                           ("Lift of B", f"{r['lift']:+.1%}"), ("p-value", f"{r['p']:.4g}")])
            st.caption(f"Difference B − A: {r['diff']:+.2%} (confidence interval {r['ci'][0]:+.2%} to {r['ci'][1]:+.2%})")
            st.markdown("**Plan a test: how many visitors do I need?**")
            p1, p2 = st.columns(2)
            base = p1.number_input("Current conversion rate (%)", 0.1, 99.0, 10.0, 0.1, key="ab_base")
            lift = p2.number_input("Smallest lift worth detecting (%)", 1.0, 500.0, 20.0, 1.0, key="ab_lift")
            n = tools.ab_sample_size(base / 100, lift / 100, alpha)
            st.info(f"About **{n:,} visitors per variant** ({2 * n:,} in total) at {int(100 * (1 - alpha))}% "
                    "confidence and 80% power.")
    except ValueError as exc:
        st.warning(str(exc))
    except Exception as exc:
        st.error(f"This test could not run: {exc}")


def tk_regression(df, nums, cats):
    if len(nums) < 2:
        st.info("Regression needs at least 2 numeric columns.")
        return
    y = st.selectbox("What do you want to predict / explain? (numeric)", nums,
                     key="rg_y")
    pool = [c for c in nums if c != y] + [c for c in cats if df[c].nunique() <= 12]
    xs = st.multiselect("Inputs that may influence it", pool, default=pool[:3], key="rg_x")
    if not xs:
        st.info("Pick at least one input.")
        return
    try:
        m = tools.linear_regression(df, y, xs)
    except ValueError as exc:
        st.warning(str(exc))
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("R² (fit)", f"{m['r2']:.3f}")
    c2.metric("Adjusted R²", f"{m['adj_r2']:.3f}")
    c3.metric("Typical error (RMSE)", f"{m['rmse']:,.2f}")
    c4.metric("Rows used", f"{m['n']:,}")
    st.caption(f"The model explains about {m['r2']:.0%} of the ups and downs in {y}. "
               "Coefficients show the change in the result for +1 in that input, other inputs held equal.")
    co = m["coefs"].copy()
    co["Significant"] = np.where(co["p-value"] < .001, "★★★", np.where(co["p-value"] < .01, "★★",
                                  np.where(co["p-value"] < .05, "★", "")))
    st.dataframe(co.round(4), hide_index=True, **W_DF)
    a, b = st.columns(2)
    fig = px.scatter(x=m["fitted"], y=m["actual"], labels={"x": "Predicted", "y": "Actual"},
                     title="Actual vs predicted", opacity=.6)
    lo, hi = float(min(m["fitted"].min(), m["actual"].min())), float(max(m["fitted"].max(), m["actual"].max()))
    fig.add_trace(go.Scatter(x=[lo, hi], y=[lo, hi], mode="lines", name="perfect", line=dict(color="#feca57")))
    a.plotly_chart(dark(fig), theme=None, **W_PLOT)
    b.plotly_chart(dark(px.histogram(x=m["resid"], labels={"x": "Error"}, title="Errors (should look like a bell)")),
                   theme=None, **W_PLOT)
    st.markdown("**Try it: predict a new case**")
    cols = st.columns(min(4, len(xs)))
    row = {}
    for i, c in enumerate(xs):
        with cols[i % len(cols)]:
            if c in m["num_cols"]:
                row[c] = st.number_input(c, value=float(df[c].mean()), key=f"rg_p_{c}")
            else:
                row[c] = st.selectbox(c, m["levels"][c], key=f"rg_p_{c}")
    st.success(f"Predicted {y}: **{tools.predict(m, row):,.2f}**")
    _csv_btn("⬇️ Download coefficients (CSV)", co, "regression_coefficients.csv", "rg_dl")


def tk_segments(df, nums):
    if len(nums) < 2:
        st.info("Segmentation needs at least 2 numeric columns.")
        return
    cols = st.multiselect("Columns that describe each row", nums, default=nums[:3], key="sg_cols")
    d = df[cols].dropna() if cols else df[nums[:0]]
    if len(cols) < 2 or len(d) < 10:
        st.info("Pick at least 2 columns (and 10+ complete rows).")
        return
    if len(d) > 5000:
        st.caption("Large data: 5,000 random rows are used to keep this fast.")
        d = d.sample(5000, random_state=0)
    Xs = tools.standardize(d.values)
    c1, c2 = st.columns([3, 1])
    k = c1.slider("Number of segments", 2, 8, 3, key="sg_k")
    if c2.button("Find the best number", key="sg_best", **W_BTN):
        res = []
        for kk in range(2, min(8, len(d) - 1) + 1):
            r = tools.kmeans(Xs, kk, n_init=3)
            res.append((kk, r["inertia"], tools.silhouette(Xs, r["labels"])))
        st.session_state["sg_scan"] = pd.DataFrame(res, columns=["Segments", "Inertia", "Silhouette"])
    scan = st.session_state.get("sg_scan")
    if scan is not None:
        best = int(scan.loc[scan["Silhouette"].idxmax(), "Segments"])
        st.info(f"Best separation: **{best} segments** (silhouette closer to 1 is better).")
        st.dataframe(scan.round(3), hide_index=True, **W_DF)
    r = tools.kmeans(Xs, k)
    d = d.assign(Segment=[f"Segment {i + 1}" for i in r["labels"]])
    U, S_, Vt = np.linalg.svd(Xs - Xs.mean(0), full_matrices=False)
    pc = Xs @ Vt[:2].T
    fig = px.scatter(x=pc[:, 0], y=pc[:, 1], color=d["Segment"], labels={"x": "Main pattern 1", "y": "Main pattern 2"},
                     title=f"{k} segments (silhouette {tools.silhouette(Xs, r['labels']):.2f})", opacity=.75)
    st.plotly_chart(dark(fig), theme=None, **W_PLOT)
    prof = d.groupby("Segment")[cols].mean().round(2)
    prof.insert(0, "Rows", d["Segment"].value_counts().sort_index())
    prof.insert(1, "Share", (prof["Rows"] / len(d)).map("{:.0%}".format))
    st.markdown("**Who is in each segment** (average of each column)")
    st.dataframe(prof, **W_DF)
    _csv_btn("⬇️ Download data with segment labels (CSV)", d, "segments.csv", "sg_dl")


def tk_outliers(df, nums):
    if not nums:
        st.info("Needs a numeric column.")
        return
    a, b, c3 = st.columns(3)
    col = a.selectbox("Column", nums, key="ol_col")
    meth = b.radio("Method", ["iqr", "z"], format_func=lambda x: "IQR rule" if x == "iqr" else "Z-score",
                   horizontal=True, key="ol_m")
    k = c3.slider("Strictness", 1.0, 4.0, 1.5, 0.5, key="ol_k") if meth == "iqr" else \
        c3.slider("Strictness", 2.0, 5.0, 3.0, 0.5, key="ol_kz")
    mask = tools.outlier_mask(df[col], meth, k)
    s = pd.to_numeric(df[col], errors="coerce")
    if meth == "iqr":
        q1, q3 = s.quantile(.25), s.quantile(.75)
        lo, hi = q1 - k * (q3 - q1), q3 + k * (q3 - q1)
    else:
        lo, hi = s.mean() - k * s.std(), s.mean() + k * s.std()
    m1, m2, m3 = st.columns(3)
    m1.metric("Outliers", f"{int(mask.sum()):,}")
    m2.metric("Share of rows", f"{mask.mean():.1%}")
    m3.metric("Normal range", f"{lo:,.2f} to {hi:,.2f}")
    view = df.assign(Status=np.where(mask, "Outlier", "Normal"))
    st.plotly_chart(dark(px.histogram(view, x=col, color="Status", nbins=50, title=f"{col}: normal vs outliers",
                                      color_discrete_map={"Normal": "#00b4d8", "Outlier": "#ff6b6b"})),
                    theme=None, **W_PLOT)
    if mask.any():
        st.markdown("**The outlier rows**")
        st.dataframe(df[mask].head(300), **W_DF)
        a, b = st.columns(2)
        with a:
            _csv_btn("⬇️ Download outlier rows (CSV)", df[mask], "outliers.csv", "ol_dl")
        if b.button(f"🧼 Remove these {int(mask.sum()):,} rows (adds a cleaning step)", key="ol_rm", **W_BTN):
            st.session_state.setdefault("tx_steps", []).append(
                {"op": "outliers", "col": col, "method": meth, "k": float(k)})
            st.rerun()
    else:
        st.success("No outliers with these settings.")


def tk_sql(df, nums, cats):
    st.caption("Ask your data questions in SQL. The table is called **data**. Only SELECT queries run, "
               "on a private copy, so nothing can be changed.")
    c0 = cats[0] if cats else df.columns[0]
    n0 = nums[0] if nums else df.columns[0]
    examples = {"Preview": "SELECT * FROM data LIMIT 20",
                "Row count": "SELECT COUNT(*) AS rows FROM data",
                f"Total of {n0} by {c0}": f'SELECT "{c0}", SUM("{n0}") AS total, COUNT(*) AS rows\n'
                                          f'FROM data\nGROUP BY "{c0}"\nORDER BY total DESC',
                f"Top 10 by {n0}": f'SELECT * FROM data\nORDER BY "{n0}" DESC\nLIMIT 10',
                f"Average {n0}": f'SELECT AVG("{n0}") AS average, MIN("{n0}") AS lowest, MAX("{n0}") AS highest '
                                 "FROM data"}
    st.session_state.setdefault("sql_text", examples["Preview"])
    a, b = st.columns([3, 1])
    ex = a.selectbox("Start from an example", list(examples), key="sql_ex")
    b.button("Use example", key="sql_use", on_click=lambda: st.session_state.update(sql_text=examples[ex]),
             **W_BTN)
    q = st.text_area("SQL query", key="sql_text", height=140)
    with st.expander("Column names (use double quotes if there are spaces)"):
        st.code(", ".join(f'"{c}"' for c in df.columns))
    if st.button("▶ Run query", key="sql_run", **W_BTN):
        try:
            st.session_state["sql_res"] = tools.run_sql(df, q)
            st.session_state["sql_err"] = None
        except Exception as exc:
            st.session_state["sql_err"] = str(exc)
    if st.session_state.get("sql_err"):
        st.error(st.session_state["sql_err"])
    res = st.session_state.get("sql_res")
    if res is not None and not st.session_state.get("sql_err"):
        st.caption(f"{len(res):,} rows × {len(res.columns)} columns")
        st.dataframe(res, **W_DF)
        _csv_btn("⬇️ Download result (CSV)", res, "query_result.csv", "sql_dl")
        rn = [c for c in res.columns if pd.api.types.is_numeric_dtype(res[c])]
        rc = [c for c in res.columns if c not in rn]
        if rn and len(res) > 1 and len(res) <= 500:
            x = rc[0] if rc else res.columns[0]
            y = [c for c in rn if c != x] or rn
            st.plotly_chart(dark(px.bar(res.head(60), x=x, y=y[0], title=f"{y[0]} by {x}")), theme=None, **W_PLOT)


def render_toolkit(df, nums, dates, cats):
    t = st.tabs(["🩺 Data quality", "🧼 Clean & transform", "📐 Pivot table", "🧪 Statistical tests",
                 "📉 Regression", "🧬 Segments", "🚨 Outliers", "🧾 SQL"])
    with t[0]:
        tk_quality(df)
    with t[1]:
        tk_clean(df, nums, dates, cats)
    with t[2]:
        tk_pivot(df, nums, cats)
    with t[3]:
        tk_tests(df, nums, cats)
    with t[4]:
        tk_regression(df, nums, cats)
    with t[5]:
        tk_segments(df, nums)
    with t[6]:
        tk_outliers(df, nums)
    with t[7]:
        tk_sql(df, nums, cats)


def render_sidebar(user):
    uid = user["id"]
    with st.sidebar:
        st.markdown("### 📊 DataPilot AI")
        st.caption(f"👤 Signed in as **{user['username']}**" + (" · admin" if user.get("is_admin") else ""))
        if st.button("🚪 Log out", key="logout_btn", **W_BTN):
            logout()
        with st.expander("👤 My account"):
            if user.get("is_admin"):
                st.caption(f"Database: {backend_label()}")
            with st.form("pw_form", clear_on_submit=True):
                p_old = st.text_input("Current password", type="password")
                p_new = st.text_input("New password", type="password",
                                      help="At least 8 characters with a letter and a number.")
                p_ok = st.form_submit_button("Change password")
            if p_ok:
                try:
                    change_password(uid, p_old, p_new)
                    st.success("Password changed ✅")
                except AuthError as exc:
                    st.error(str(exc))
                except Exception as exc:
                    st.error(f"Could not change the password: {exc}")
            st.divider()
            st.caption("Delete my account and ALL my saved projects, reports and files. This cannot be undone.")
            del_pw = st.text_input("Password to confirm", type="password", key="del_acct_pw")
            del_ok = st.checkbox("Yes, delete my account", key="del_acct_ok")
            if st.button("Delete my account", key="del_acct", disabled=not del_ok, **W_BTN):
                try:
                    delete_account(uid, del_pw)
                    st.session_state.clear()
                    st.rerun()
                except AuthError as exc:
                    st.error(str(exc))
        cnt = db_counts(uid)
        st.caption(f"🗄️ {cnt['projects']} projects · {cnt['reports']} reports · {cnt['uploads']} files · "
                   f"{cnt['analysis_history']} analyses · {cnt['chat_messages']} chat messages")
        with st.expander("🎨 Theme & background", expanded=False):
            s = S()
            looks = ["Flex", "Modern", "3D classic"]
            st.radio("Look", looks, index=_idx(looks, s.get("look", "Flex")), horizontal=True, key="th_look",
                     help="Flex = charcoal / cream portfolio style with doors. Modern = glass cards. 3D classic = your original.")
            if st.session_state.get("th_look", s.get("look", "Flex")) == "Flex":
                st.caption("Flex has its own charcoal and cream colours. Switch light / dark with the pull-cord "
                           "at the top of the page or the Dark mode switch. Pick another Look to use colour presets.")
            else:
                names = [n for n in THEMES if not n.startswith("Flex")]
                st.selectbox("Theme", names, index=_idx(names, s["theme_name"]), key="th_name")
                if st.session_state.get("th_name") == "Custom":
                    c1, c2 = st.columns(2)
                    c1.color_picker("Background", s["theme_bg"], key="th_bg")
                    c2.color_picker("Accent", s["theme_accent"], key="th_accent")
                    st.caption("Dark or light text is chosen automatically from your background colour.")
            st.selectbox("3D background", fx.BACKGROUNDS, index=_idx(fx.BACKGROUNDS, s.get("bg3d", fx.DEFAULT_BG)),
                         key="th_bg3d", help="Animated 3D scene behind the app. Choose Off for the calmest page.")
            st.checkbox("Interactive effects (tilt, glow, count-up)", value=bool(s.get("fx", True)), key="th_fx")
            st.checkbox("Solid background (no glow)", value=bool(s["theme_solid"]), key="th_solid")
            if st.button("Save as my default theme", key="save_theme", **W_BTN):
                new = {**S(), **theme_cfg()}
                save_settings(uid, new)
                st.session_state["settings"] = new
                st.toast("Theme saved ✅")
        with st.expander("⚙️ Settings & dashboard defaults"):
            s = S()
            n_agg = st.selectbox("Default calculation", AGG_CHOICES,
                                 index=_idx(AGG_CHOICES, s["default_agg"]), key="set_agg")
            n_ppt = st.radio("PowerPoint style", PPT_STYLES,
                             index=_idx(PPT_STYLES, s["ppt_style"]), key="set_ppt")
            n_kpi = st.slider("KPI cards", 1, 6, int(s["kpi_cards"]), key="set_kpi")
            n_ch = st.slider("Dashboard charts", 1, 8, int(s["dash_charts"]), key="set_ch")
            n_pal = st.selectbox("Chart colors", list(PALETTES),
                                 index=_idx(list(PALETTES), s["palette"]), key="set_pal")
            n_tpl = st.selectbox("Chart style", TEMPLATES,
                                 index=_idx(TEMPLATES, s["template"]), key="set_tpl")
            if st.button("Save settings", key="save_settings", **W_BTN):
                new = {**S(), "default_agg": n_agg, "ppt_style": n_ppt, "kpi_cards": n_kpi,
                       "dash_charts": n_ch, "palette": n_pal, "template": n_tpl}
                save_settings(uid, new)
                st.session_state["settings"] = new
                for k in ("agg_main", "kpi_n", "dash_n", "ppt_style"):   # let new defaults apply
                    st.session_state.pop(k, None)
                st.toast("Settings saved ✅")
                st.rerun()
        with st.expander("🧹 Clear saved data"):
            st.caption("Deletes all saved projects, reports, chats and analysis history.")
            sure = st.checkbox("Yes, delete everything saved", key="clear_ok")
            if st.button("Delete saved data", key="clear_all", disabled=not sure, **W_BTN):
                clear_all_data(uid)
                st.toast("Saved data deleted ✅")
                st.rerun()


# ======================================================================
# Page
# ======================================================================
def auth_gate():
    """Return the signed-in user, or show the log in / create account screen and stop the page."""
    sid = st.session_state.get("auth_uid")
    if sid:
        u = get_user(sid)
        if u:
            return u
        st.session_state.clear()
    apply_theme()
    if theme_cfg()["look"] == "Flex":
        flex_top(landing=True)
        st.markdown('<div class="anchor-add-data"></div><div class="fx-h2s">Log in or create your account.</div>',
                    unsafe_allow_html=True)
    else:
        st.markdown(hero_html("Log in to open your saved projects, or create a free account."), unsafe_allow_html=True)
        st.markdown('<div class="feat-grid">'
                    '<div class="feat"><span class="ic">📈</span><b>Instant insights</b><span class="t">Drop in a file and get KPIs, '
                    'charts and a plain-English summary.</span></div>'
                    '<div class="feat"><span class="ic">🧰</span><b>Analyst toolkit</b><span class="t">Clean data, pivot, run '
                    'statistical tests, regression, clustering and SQL.</span></div>'
                    '<div class="feat"><span class="ic">🤖</span><b>Ask AI</b><span class="t">Ask questions about your data '
                    'and get answers with the numbers.</span></div>'
                    '<div class="feat"><span class="ic">🔒</span><b>Private projects</b><span class="t">Every account has its own '
                    'saved projects, reports and files.</span></div></div>', unsafe_allow_html=True)
    submit = _stretch(st.form_submit_button)
    t_in, t_up = st.tabs(["🔐 Log in", "📝 Create account"])
    signed = None
    with t_in:
        with st.form("login_form"):
            lu = st.text_input("Username", key="li_user")
            lp = st.text_input("Password", type="password", key="li_pw")
            go = st.form_submit_button("Log in", **submit)
        if go:
            try:
                signed = authenticate(lu, lp)
            except AuthError as exc:
                st.error(str(exc))
            except Exception as exc:
                st.error(f"Could not log in: {exc}")
        st.caption("Forgot your password? Ask the person who runs this app to reset it "
                   "(see DEPLOY.md, manage_users.py).")
    with t_up:
        if legacy_account_exists():
            st.info("Saved work from the earlier version (no login) was found. "
                    "The account you create now will own it.")
        with st.form("register_form"):
            ru = st.text_input("Username", key="rg_user", help="3-32 letters, numbers, . - or _")
            re_ = st.text_input("Email (optional)", key="rg_email")
            rp = st.text_input("Password", type="password", key="rg_pw",
                               help="At least 8 characters with a letter and a number.")
            rp2 = st.text_input("Repeat password", type="password", key="rg_pw2")
            gor = st.form_submit_button("Create account", **submit)
        if gor:
            if rp != rp2:
                st.error("The two passwords do not match.")
            else:
                try:
                    signed = register_user(ru, re_, rp)
                except AuthError as exc:
                    st.error(str(exc))
                except Exception as exc:
                    st.error(f"Could not create the account: {exc}")
    if signed:
        st.session_state["auth_uid"] = signed["id"]
        st.session_state.pop("settings", None)
        st.rerun()
    st.stop()


try:
    init_db()
except Exception as exc:
    st.error(f"Could not open the database ({backend_label()}): {exc}")
    st.info("Check the MYSQL_* settings (host, user, password, database) in DEPLOY.md, "
            "or remove DATAPILOT_DB to use the built-in SQLite file.")
    st.stop()
user = auth_gate()          # nothing below runs until someone is signed in
uid = user["id"]
if "settings" not in st.session_state:
    st.session_state["settings"] = get_settings(uid)
apply_theme()
flex_on = theme_cfg()["look"] == "Flex"
if flex_on:
    flex_top(landing=not st.session_state.get("has_data", False), username=user["username"])
else:
    st.markdown(hero_html("Put your data in. Insights, charts and a Power BI style dashboard appear "
                          "automatically."), unsafe_allow_html=True)

render_sidebar(user)

with st.expander("👋 New here? How to use DataPilot AI", expanded=not st.session_state.get("guide_seen")):
    st.markdown(
        "1. **Add data**: upload a CSV / Excel / JSON / SQLite file, paste a Google Sheet link, paste from "
        "Excel, or type it in.\n"
        "2. **Read the results**: Insights, Charts and Statistics appear automatically. "
        "If cells are empty, choose how to handle them.\n"
        "3. **Build a dashboard** in the 📊 Power BI tab, or predict the future in 🔮 Forecast.\n"
        "4. **Download** Excel, PowerPoint, PDF or a shareable HTML page.\n"
        "5. **Save** your work in 🗄️ Projects and open it again later. Change colours in the sidebar (🎨).")
st.session_state["guide_seen"] = True

if flex_on and not st.session_state.get("has_data", False):
    st.markdown(flex.cta_html(), unsafe_allow_html=True)
st.subheader("1. Insert your data")
source = st.radio("How do you want to add data?",
                  ["Upload file", "Google Sheet link", "Paste from Excel", "Type data",
                   "Try sample data", "Open saved project"],
                  horizontal=True)

raw, name = None, "my_data"

if source == "Upload file":
    up = st.file_uploader("CSV, Excel, JSON or SQLite file",
                          type=["csv", "xlsx", "xlsm", "json", "db", "sqlite", "sqlite3"])
    if up is not None:
        name = up.name
        if up.size > MAX_MB * 1024 * 1024:
            st.error(f"This file is {up.size / 1048576:,.0f} MB, and the limit is {MAX_MB} MB. "
                     "Please use a smaller file (remove columns or rows you do not need).")
        else:
            _ru = st.session_state.get("raw_upload")
            if not _ru or _ru[0] != up.name or len(_ru[1]) != up.size:
                st.session_state["raw_upload"] = (up.name, up.getvalue())     # kept for 'Save project'
            try:
                ext = up.name.lower().rsplit(".", 1)[-1]
                if ext == "csv":
                    raw = pd.read_csv(up, sep=None, engine="python")
                elif ext == "json":
                    raw = read_json_upload(up)
                elif ext in ("db", "sqlite", "sqlite3"):
                    raw = read_sqlite_upload(up)
                else:
                    xl = pd.ExcelFile(up)
                    sheet = st.selectbox("Sheet", xl.sheet_names) if len(xl.sheet_names) > 1 \
                        else xl.sheet_names[0]
                    raw = xl.parse(sheet)
            except Exception as exc:
                st.error(f"Could not read the file: {exc}")

elif source == "Google Sheet link":
    st.caption("Share the sheet as 'Anyone with the link can view', then paste its link here.")
    gs_url = st.text_input("Google Sheet link", key="gs_url")
    if st.button("Load sheet", key="gs_load", **W_BTN):
        try:
            with st.spinner("Loading the sheet..."):
                st.session_state["gs_data"] = (gs_url, read_google_sheet(gs_url))
        except Exception as exc:
            st.error(str(exc))
    gs = st.session_state.get("gs_data")
    if gs and gs[0] == gs_url:
        raw, name = gs[1], "google_sheet"

elif source == "Paste from Excel":
    st.caption("Copy cells in Excel (include the header row) and paste them here.")
    text = st.text_area("Paste data", height=200)
    if text.strip():
        try:
            raw = pd.read_csv(io.StringIO(text), sep=None, engine="python")
        except Exception as exc:
            st.error(f"Could not read the pasted data: {exc}")

elif source == "Type data":
    cols_txt = st.text_input("Column names (comma separated)",
                             value="Date, Product, Category, Quantity, Price")
    cols = [c.strip() for c in cols_txt.split(",") if c.strip()]
    if cols and len(set(cols)) == len(cols):
        if st.session_state.get("typed_cols") != cols:
            st.session_state.typed_cols = cols
            st.session_state.typed_df = pd.DataFrame({c: [""] * 5 for c in cols})
        st.caption("Click a cell to type. Use the bottom empty row to add records.")
        raw = st.data_editor(st.session_state.typed_df, num_rows="dynamic",
                             key="typed_editor", **W_ED)
    else:
        st.warning("Enter at least one unique column name.")

elif source == "Open saved project":
    projs = list_projects(uid)
    if not projs:
        st.info("You have no saved projects yet. Analyse some data, then press "
                "'Save project' in the 🗄️ Projects tab.")
    else:
        labels = {p["id"]: f"{p['name']}  ({p['n_rows']:,} rows, saved {p['updated_at']})"
                  for p in projs}
        pick = st.selectbox("Saved project", list(labels), format_func=labels.get)
        try:
            prj, raw = load_project(uid, pick)
            name = prj["source_name"] or prj["name"]
            st.session_state["saved_pid"] = (name, pick)
        except Exception as exc:
            st.error(f"Could not open this project: {exc}")

else:
    rng = np.random.default_rng(1)
    n = 200
    prod = rng.choice(["Laptop", "Phone", "Tablet", "Headphones"], n)
    base = {"Laptop": 60000, "Phone": 30000, "Tablet": 25000, "Headphones": 3000}
    raw = pd.DataFrame({
        "Date": pd.date_range("2025-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
        "Product": prod,
        "Region": rng.choice(["North", "South", "East", "West"], n),
        "Quantity": rng.integers(1, 10, n),
        "Price": [base[p] * rng.uniform(0.9, 1.1) for p in prod],
    })
    raw["Revenue"] = (raw["Quantity"] * raw["Price"]).round(0)
    raw["Price"] = raw["Price"].round(0)
    name = "sample_data"

if raw is None or raw.dropna(how="all").empty:
    if st.session_state.get("has_data"):               # data was removed: show the home page again
        st.session_state["has_data"] = False
        st.rerun()
    st.info("👆 Add some data above and the analysis will appear here.")
    st.stop()
if not st.session_state.get("has_data"):               # first data: switch to the compact header once
    st.session_state["has_data"] = True
    if flex_on:
        st.rerun()

if len(raw) > MAX_ROWS:
    st.warning(f"This data has {len(raw):,} rows. To keep the app fast, only the first {MAX_ROWS:,} are used.")
    raw = raw.head(MAX_ROWS)

df, notes = prepare_cached(raw)
if df.empty:
    st.warning("The data is empty after cleaning.")
    st.stop()

_miss = int(df.isna().sum().sum())
if _miss:
    _mode = st.selectbox(f"🩹 {_miss:,} empty cells found. What should I do with them?",
                         MISSING_MODES, key="miss_mode")
    df, _n2 = handle_missing(df, _mode)
    notes = notes + _n2
    if df.empty:
        st.warning("No rows are left after removing rows with missing values. Pick another option.")
        st.stop()

# Cleaning recipe built in the Analyst Toolkit (resets when different data is loaded)
if st.session_state.get("tx_src") != name:
    st.session_state["tx_src"] = name
    st.session_state["tx_steps"] = []
df, _tx_notes, _tx_err = tools.apply_steps(df, st.session_state.setdefault("tx_steps", []))
st.session_state["tx_errors"] = _tx_err
notes = notes + _tx_notes
if df.empty:
    st.warning("Your cleaning steps removed every row.")
    if st.button("↩️ Undo the last cleaning step", key="tx_undo_empty", **W_BTN):
        st.session_state["tx_steps"].pop()
        st.rerun()
    st.stop()

nums, dates, cats = split_columns(df)
bdf, slicer_notes, slicer_specs = slicer_panel(df, name)   # sidebar slicers

# ---------------------------------------------------------------- results
st.divider()
st.subheader("2. Analysis")
data_chips(name, df, dates)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Rows", f"{len(df):,}")
m2.metric("Columns", len(df.columns))
m3.metric("Numeric columns", len(nums))
m4.metric("Missing cells", f"{int(df.isna().sum().sum()):,}")
for n_ in notes:
    st.caption("🧹 " + n_)

measure, agg = None, "sum"
if nums:
    c1, c2 = st.columns(2)
    default = next((i for i, c in enumerate(nums)
                    if any(k in c.lower() for k in ("revenue", "sales", "amount", "total",
                                                    "profit", "price"))), 0)
    measure = c1.selectbox("Main value to analyse", nums, index=default)
    agg = c2.selectbox("Combine values by", AGG_CHOICES,
                       index=_idx(AGG_CHOICES, S()["default_agg"]), key="agg_main")

insights = insights_cached(df, measure, agg)

(tab_ins, tab_charts, tab_stats, tab_tools, tab_data, tab_bi, tab_map, tab_viz, tab_fc, tab_dl, tab_ai, tab_dax,
 tab_proj) = st.tabs(
    ["💡 Insights", "📈 Charts", "📋 Statistics", "🧰 Analyst Toolkit", "🗂️ Data", "📊 Power BI", "🗺️ Map", "🧩 BI Visuals",
     "🔮 Forecast", "⬇️ Download", "🤖 Ask AI", "🧮 DAX", "🗄️ Projects"])

with tab_ins:
    for line in insights:
        st.markdown("- " + line)

with tab_charts:
    if dates and measure:
        d = dates[0]
        t = df.dropna(subset=[d, measure])
        span = (t[d].max() - t[d].min()).days if len(t) else 0
        freq = "MS" if span > 90 else "D"
        trend = t.set_index(d)[measure].resample(freq).agg(agg).reset_index()
        st.plotly_chart(dark(px.line(trend, x=d, y=measure, markers=True,
                                title=f"{agg.title()} of {measure} over time")), theme=None, **W_PLOT)

    if cats and measure:
        cols = st.columns(2)
        for i, c in enumerate(cats[:4]):
            g = df.groupby(c)[measure].agg(agg).reset_index().sort_values(measure, ascending=False)
            fig = px.bar(g, x=c, y=measure, title=f"{agg.title()} of {measure} by {c}")
            cols[i % 2].plotly_chart(dark(fig), theme=None, **W_PLOT)

    if nums:
        cols = st.columns(2)
        for i, c in enumerate(nums[:4]):
            cols[i % 2].plotly_chart(dark(px.histogram(df, x=c, title=f"Distribution of {c}")),
                                     theme=None, **W_PLOT)

    if len(nums) > 1:
        st.plotly_chart(dark(px.imshow(df[nums].corr().round(2), text_auto=True, aspect="auto",
                                  color_continuous_scale="RdBu_r", zmin=-1, zmax=1,
                                  title="Correlation between numeric columns")), theme=None, **W_PLOT)

    st.markdown("**Make your own chart**")
    a, b, c_, d_ = st.columns(4)
    kind = a.selectbox("Type", ["Bar", "Line", "Scatter", "Box", "Pie"])
    x = b.selectbox("X", df.columns)
    y = c_.selectbox("Y", nums or list(df.columns))
    color = d_.selectbox("Color", ["(none)"] + list(df.columns))
    color = None if color == "(none)" else color
    try:
        if kind == "Bar":
            fig = px.bar(df, x=x, y=y, color=color)
        elif kind == "Line":
            fig = px.line(df.sort_values(x), x=x, y=y, color=color)
        elif kind == "Scatter":
            fig = px.scatter(df, x=x, y=y, color=color)
        elif kind == "Box":
            fig = px.box(df, x=x, y=y, color=color)
        else:
            fig = px.pie(df, names=x, values=y)
        st.plotly_chart(dark(fig), theme=None, **W_PLOT)
    except Exception as exc:
        st.error(f"Could not draw this chart: {exc}")

with tab_stats:
    if nums:
        st.markdown("**Numeric columns**")
        st.dataframe(df[nums].describe().T.round(3), **W_DF)
    others = [c for c in df.columns if c not in nums]
    if others:
        st.markdown("**Other columns**")
        st.dataframe(pd.DataFrame({"Type": df[others].dtypes.astype(str),
                                   "Unique values": df[others].nunique(),
                                   "Most common": [str(df[c].mode().iloc[0]) if df[c].notna().any()
                                                   else "" for c in others],
                                   "Missing": df[others].isna().sum()}), **W_DF)

with tab_tools:
    render_toolkit(df, nums, dates, cats)

with tab_data:
    st.dataframe(df, **W_DF)

with tab_bi:
    render(bdf, nums, dates, cats, pre_filters=slicer_notes, total_rows=len(df))

with tab_map:
    render_map(bdf, nums, dates, measure, agg)

with tab_viz:
    render_visuals(bdf, nums, dates, measure, agg)

with tab_fc:
    st.subheader("Forecast")
    st.caption("A simple statistical estimate from your past trend. It is a guide, not a guarantee.")
    if not dates or not nums:
        st.info("Forecasting needs a date column and a number column in your data.")
    else:
        f1, f2, f3, f4 = st.columns(4)
        dcol = f1.selectbox("Date column", dates, key="fc_date")
        vcol = f2.selectbox("Value to forecast", nums, key="fc_val",
                            index=nums.index(measure) if measure in nums else 0)
        span_days = max(1, (df[dcol].max() - df[dcol].min()).days)
        freq = f3.selectbox("Group by", ["Day", "Week", "Month"], key="fc_freq",
                            index=0 if span_days < 120 else 2 if span_days > 700 else 1)
        ahead = f4.slider("Periods ahead", 1, 36, 6, key="fc_n")
        rule = {"Day": "D", "Week": "W", "Month": "MS"}[freq]
        ser = df.dropna(subset=[dcol, vcol]).set_index(dcol)[vcol].sort_index().resample(rule).agg(agg)
        ser = ser.fillna(0) if agg in ("sum", "count") else ser.interpolate().ffill().bfill()
        if len(ser) < 6:
            st.warning(f"Only {len(ser)} {freq.lower()}(s) of data. At least 6 are needed. "
                       "Try grouping by a smaller period (for example Day).")
        else:
            m = {"Day": 7, "Month": 12}.get(freq, 0)
            use_season = False
            if m and len(ser) >= 2 * m:
                use_season = st.checkbox(f"Include a repeating pattern (every {m} {freq.lower()}s)",
                                         key="fc_season")
            fc = make_forecast(ser.values, ahead, m if use_season else 0)
            fut = pd.date_range(ser.index[-1], periods=ahead + 1, freq=rule)[1:]
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=ser.index, y=ser.values, name="Actual", mode="lines+markers"))
            fig.add_trace(go.Scatter(x=fut, y=fc["upper"], mode="lines", line=dict(width=0),
                                     showlegend=False, hoverinfo="skip"))
            fig.add_trace(go.Scatter(x=fut, y=fc["lower"], mode="lines", line=dict(width=0),
                                     fill="tonexty", fillcolor="rgba(0,180,216,0.2)", name="Likely range"))
            fig.add_trace(go.Scatter(x=fut, y=fc["pred"], name="Forecast", mode="lines+markers",
                                     line=dict(dash="dash", color="#feca57")))
            fig.update_layout(title=f"{agg.title()} of {vcol} per {freq.lower()}, next {ahead}",
                              height=460, margin=dict(l=20, r=20, t=60, b=20))
            st.plotly_chart(dark(fig), theme=None, **W_PLOT)
            avg = float(np.mean(ser.values))
            k1, k2, k3 = st.columns(3)
            k1.metric(f"Trend per {freq.lower()}", ("+" if fc["slope"] >= 0 else "-") + short(abs(fc["slope"])),
                      f"{fc['slope'] / abs(avg):+.1%} of average" if avg else None)
            k2.metric(f"Next {freq.lower()}", short(fc["pred"][0]))
            k3.metric(f"Total of next {ahead}", short(float(np.sum(fc["pred"]))))
            word = "upward" if fc["slope"] > 0 else "downward" if fc["slope"] < 0 else "flat"
            st.markdown(f"- The overall trend of **{vcol}** is **{word}**, based on {len(ser)} {freq.lower()}s of history.")
            if fc["seasonal"]:
                st.markdown(f"- The forecast also repeats the usual {m}-{freq.lower()} pattern in your data.")
            st.markdown("- The shaded band is a rough 95% range; it gets wider the further ahead you look.")
            out = pd.DataFrame({freq: fut, "Forecast": fc["pred"].round(2), "Low": fc["lower"].round(2),
                                "High": fc["upper"].round(2)})
            st.dataframe(out, hide_index=True, **W_DF)
            st.download_button("Download forecast (CSV)", out.to_csv(index=False).encode("utf-8"),
                               "forecast.csv", "text/csv", **W_DL)


def lazy_file(label, key, sig, builder, filename, mime):
    """Build a file only when asked (keeps the app fast), then offer the download."""
    store = st.session_state.setdefault("_files", {})
    ready = store.get(key)
    if ready and ready[0] == sig:
        st.download_button(f"⬇️ Download {label}", ready[1], filename, mime, key=f"dl_{key}", **W_DL)
        return
    if st.button(f"Build {label}", key=f"build_{key}", **W_BTN):
        with st.spinner(f"Building {label}..."):
            try:
                store[key] = (sig, builder())
                save_report(uid, current_pid(name), key, filename, store[key][1])
            except ModuleNotFoundError as exc:
                st.warning(f"One more package is needed. Run: python -m pip install "
                           f"{'python-pptx' if 'pptx' in str(exc) else 'reportlab'}")
                return
            except Exception as exc:
                st.warning(f"{label} unavailable: {exc}")
                return
        st.rerun()


with tab_dl:
    try:
        data_sig = (name, df.shape, int(pd.util.hash_pandas_object(df, index=False).sum()))
    except Exception:
        data_sig = (name, df.shape)
    st.download_button("Cleaned data (CSV)", df.to_csv(index=False).encode("utf-8"),
                       "cleaned_data.csv", "text/csv", **W_DL)
    lazy_file("Excel report (insights + data + statistics)", "xlsx", data_sig,
              lambda: build_excel(df, insights), "analysis_report.xlsx",
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.divider()
    st.markdown("**Presentation for stakeholders**")
    bi = st.session_state.get("bi_export")
    deck = name.rsplit(".", 1)[0]
    if bi:
        style = st.radio("PowerPoint style", PPT_STYLES, index=_idx(PPT_STYLES, S()["ppt_style"]),
                         horizontal=True, key="ppt_style")
        bsig = hashlib.md5(repr(bi).encode()).hexdigest()
        lazy_file("PowerPoint dashboard (.pptx)", "pptx", (bsig, style),
                  lambda: build_pptx(bi, insights, notes, deck, dark=style.startswith("Dark")),
                  "powerbi_dashboard.pptx",
                  "application/vnd.openxmlformats-officedocument.presentationml.presentation")
        lazy_file("PDF dashboard report", "pdf", bsig,
                  lambda: build_bi_pdf(bi, insights, notes, deck),
                  "powerbi_dashboard.pdf", "application/pdf")
        _figs = st.session_state.get("bi_figs", [])
        lazy_file("Shareable dashboard page (.html)", "html", (bsig, len(_figs), theme_cfg()["theme_name"]),
                  lambda: build_dashboard_html(deck, bi, _figs, insights, current_theme()).encode("utf-8"),
                  "dashboard.html", "text/html")
        st.caption("The PowerPoint opens with a one-page dashboard (KPI cards + charts), then "
                   "findings and one slide per chart with a plain-language takeaway. Charts are "
                   "native PowerPoint charts, so you can click and edit them. "
                   "If you change the dashboard, press Build again.")
    else:
        st.info("Open the Power BI tab and build your dashboard to enable the PowerPoint and PDF.")

with tab_ai:
    engine = st.radio("AI engine", AI_ENGINES, horizontal=True, key="ai_engine")
    api_key, model = "", CLAUDE_MODEL
    if engine.startswith("Claude"):
        k1, k2 = st.columns(2)
        api_key = k1.text_input("Claude API key", type="password", key="ai_key",
                                help="Used only in this browser session and never saved. "
                                     "You can also set the ANTHROPIC_API_KEY environment variable.")
        model = k2.text_input("Model", value=CLAUDE_MODEL, key="ai_model")
        st.warning("Online mode sends your column names, summary statistics and a few sample rows "
                   "to Anthropic's servers.")
    else:
        st.caption("Needs Ollama installed and running with a model (`ollama pull llama3.2:3b`). "
                   "Everything stays on your computer.")
    st.caption("Your conversation is saved in the local database.")

    def _ai_error(exc):
        if isinstance(exc, requests.exceptions.ConnectionError):
            st.error("Ollama is not running. Start it and try again." if not engine.startswith("Claude")
                     else "Could not reach the Claude API. Check your internet connection.")
        else:
            st.error(str(exc))

    pid_now = current_pid(name)
    history = get_chat(uid, pid_now)
    for m_ in history:
        with st.chat_message(m_["role"]):
            st.markdown(m_["content"])
    q = st.text_input("Your question", value="Explain this data and give me 3 recommendations.")
    b1, b2 = st.columns(2)
    if b1.button("Ask", **W_BTN):
        answer = None
        with st.spinner("Thinking..."):
            try:
                answer = ai_explain(df, insights, q, engine, api_key, model)
            except Exception as exc:
                _ai_error(exc)
        if answer:
            add_chat(uid, pid_now, "user", q)
            add_chat(uid, pid_now, "assistant", answer)
            st.rerun()
    if history and b2.button("Clear chat history", **W_BTN):
        clear_chat(uid, pid_now)
        st.rerun()

    st.divider()
    st.markdown("**📈 Draw a chart from a question**")
    cq = st.text_input("Describe the chart you want", key="ai_chart_q",
                       value=f"Show {measure or 'the number of rows'} by {cats[0] if cats else df.columns[0]}")
    if st.button("Draw chart", key="ai_chart_btn", **W_BTN):
        with st.spinner("Choosing the best chart..."):
            try:
                st.session_state["ai_chart"] = (name, ai_chart_cfg(df, cq, engine, api_key, model))
            except json.JSONDecodeError:
                st.error("The AI reply could not be read as a chart setting. Please try again.")
            except Exception as exc:
                _ai_error(exc)
    saved_chart = st.session_state.get("ai_chart")
    if saved_chart and saved_chart[0] == name:
        cfg_ = saved_chart[1]
        try:
            d2 = df.assign(**{"Number of records": 1}) if cfg_["y"] == "Number of records" else df
            st.plotly_chart(make_fig(d2, cfg_), theme=None, **W_PLOT)
            st.caption(f"{cfg_['type']} · X: {cfg_['x']} · Y: {cfg_['y']} ({cfg_['agg']})"
                       + (f" · colour: {cfg_['color']}" if cfg_["color"] else ""))
        except Exception as exc:
            st.error(f"This chart could not be drawn: {exc}")

with tab_dax:
    render_dax(df, bdf, nums, dates, cats, measure, name, slicer_specs)

with tab_proj:
    st.subheader("Save this analysis")
    st.caption("Saves the cleaned dataset, cleaning notes, KPIs and insights in the local database. "
               "Re-open it any time from 'Open saved project' at the top.")
    pname = st.text_input("Project name", value=name.rsplit(".", 1)[0][:80])
    _ru = st.session_state.get("raw_upload")
    keep_orig = False
    if source == "Upload file" and _ru and _ru[0] == name:
        keep_orig = st.checkbox("Also keep the original uploaded file", value=True, key="keep_orig")
    if st.button("💾 Save project & analysis", key="save_project", **W_BTN):
        if not pname.strip():
            st.warning("Please type a project name.")
        else:
            try:
                pid = save_project(uid, pname, name, df)
                bi_ = st.session_state.get("bi_export") or {}
                add_analysis(uid, pid, notes, bi_.get("kpis", []), insights,
                             dict(measure=measure, aggregation=agg, rows=len(df),
                                  columns=len(df.columns), filters=bi_.get("filters", []),
                                  charts=len(bi_.get("specs", []))))
                st.session_state["saved_pid"] = (name, pid)
                st.success(f"Saved '{pname.strip()}' (project #{pid}).")
                if keep_orig:
                    try:
                        save_upload(uid, pid, _ru[0], _ru[1])
                    except Exception as exc:
                        st.warning(f"The project was saved, but the original file was not: {exc}")
            except Exception as exc:
                st.error(f"Could not save the project: {exc}")

    st.divider()
    st.subheader("Saved projects")
    projs = list_projects(uid)
    if projs:
        st.dataframe(pd.DataFrame(projs)[["id", "name", "source_name", "n_rows", "n_cols", "updated_at"]]
                     .rename(columns={"source_name": "source", "n_rows": "rows", "n_cols": "columns",
                                      "updated_at": "last saved"}), hide_index=True, **W_DF)
        dsel = st.selectbox("Delete a project", [p["id"] for p in projs], key="del_proj_sel",
                            format_func=lambda i: next(p["name"] for p in projs if p["id"] == i))
        if st.button("🗑️ Delete selected project", key="del_proj", **W_BTN):
            delete_project(uid, dsel)
            st.rerun()
    else:
        st.caption("No saved projects yet.")

    st.divider()
    st.subheader("Original uploaded files")
    ups = list_uploads(uid, limit=20)
    if ups:
        usel = st.selectbox("Choose a file", [u_["id"] for u_ in ups], key="up_sel",
                            format_func=lambda i: next(
                                f"{u_['file_name']} · {u_['project_name'] or 'unsaved data'} · "
                                f"{(u_['size_bytes'] or 0) / 1024:,.0f} KB · {u_['created_at']}"
                                for u_ in ups if u_["id"] == i))
        d1, d2 = st.columns(2)
        try:
            urow, udata = read_upload(uid, usel)
            d1.download_button("⬇️ Download original file", udata, urow["file_name"],
                               "application/octet-stream", key=f"udl_{usel}", **W_DL)
        except Exception as exc:
            d1.warning(f"This file cannot be read: {exc}")
        if d2.button("🗑️ Delete this file", key="udel_btn", **W_BTN):
            delete_upload(uid, usel)
            st.rerun()
    else:
        st.caption("Tick 'Also keep the original uploaded file' when you save a project to keep it here.")

    st.divider()
    st.subheader("Analysis history")
    hist = list_analysis(uid)
    if hist:
        st.dataframe(pd.DataFrame([dict(id=h["id"], project=h["project"], saved=h["created_at"],
                                        rows=h["result"].get("rows"), measure=h["result"].get("measure"),
                                        calculation=h["result"].get("aggregation"),
                                        insights=len(h["insights"])) for h in hist]),
                     hide_index=True, **W_DF)
        hid = st.selectbox("View details", [h["id"] for h in hist], key="hist_sel",
                           format_func=lambda i: next(f"#{h['id']} - {h['project']} - {h['created_at']}"
                                                      for h in hist if h["id"] == i))
        h = next(x for x in hist if x["id"] == hid)
        with st.expander("🧹 Cleaning summary", expanded=True):
            for n_ in h["cleaning"] or ["No cleaning changes were needed."]:
                st.markdown("- " + str(n_))
        if h["kpis"]:
            with st.expander("📊 KPIs", expanded=False):
                st.dataframe(pd.DataFrame(h["kpis"]), hide_index=True, **W_DF)
        with st.expander("💡 Insights", expanded=False):
            for line in h["insights"]:
                st.markdown("- " + str(line))
    else:
        st.caption("No analyses saved yet.")

    st.divider()
    st.subheader("Saved reports")
    reps = list_reports(uid)
    if reps:
        for r in reps:
            c1, c2, c3, c4 = st.columns([5, 2, 1, 1])
            c1.markdown(f"**{r['file_name']}**  \n{r['report_type']} · {r['project_name'] or 'unsaved data'}"
                        f" · {r['created_at']} · {(r['size_bytes'] or 0) / 1024:,.0f} KB")
            data_ = read_report(uid, r)
            if data_ is None:
                c2.caption("file missing")
            else:
                c2.download_button("⬇️ Download", data_, r["file_name"],
                                   MIME.get(Path(r["file_name"]).suffix, "application/octet-stream"),
                                   key=f"rdl_{r['id']}", **W_DL)
            if c3.button("🗑️", key=f"rdel_{r['id']}", **W_BTN):
                delete_report(uid, r["id"])
                st.rerun()
    else:
        st.caption("Reports you build in the Download tab are kept here.")

