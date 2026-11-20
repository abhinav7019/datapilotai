"""
datapilot_flex.py - the "Flex" look (inspired by a designer-portfolio site)
===========================================================================
No Streamlit import. Everything is plain strings:

  FLEX_CSS            charcoal / cream design, big bold type, pill buttons, text-style tabs
  nav_html()          top bar: links, live clock + date chips, and the pull-cord (light/dark)
  hero_html()         "Hi, I'm DataPilot. I am a [Data Analyst]" on a spiral notepad + 3D card stack
  doors_html()        four 3D arched doors that swing open on hover; a click walks you in (opens the tab)
  steps_html()        big-number "from raw file to answer" timeline
  cta_html()          "Got a data project? Let's analyze it together."
  compact_html()      slim header once data is loaded

Clicks are handled by datapilot_fx.py (it looks at the CSS class names: go-insights, go-toolkit...).
HTML is written as single lines without blank lines so Markdown never turns it into a code block.
"""

from html import escape

FONT_IMPORT = ("@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800"
               "&family=JetBrains+Mono:wght@500;700&display=swap');")

# page colours for the two Flex themes (see build_theme in app.py)
FLEX_DARK = {"bg": "#1b2025", "accent": "#ff8a3d"}
FLEX_LIGHT = {"bg": "#ebe7de", "accent": "#e8590c"}
FLEX_VARS = {
    True: {"ink": "#f2efe8", "soft": "#a3a8a6", "panel": "#242a30", "panel2": "#2d343b", "inp": "#20262c",
           "line": "#ffffff1f", "edge": "#12161a", "edge2": "#0d1013", "btn1": "#f2efe8", "btn2": "#dcd8cd",
           "btn-ink": "#1b2025", "shadow": "#0006", "shadow-lg": "#000a", "glass": "rgba(36,42,48,.72)",
           "tbl-filter": "invert(.92) hue-rotate(180deg) contrast(.95)"},
    False: {"ink": "#1d1c1a", "soft": "#6c6961", "panel": "#f7f4ed", "panel2": "#e2ded4", "inp": "#fbfaf6",
            "line": "#1d1c1a24", "edge": "#cfcabe", "edge2": "#bdb8ab", "btn1": "#1d1c1a", "btn2": "#35332f",
            "btn-ink": "#f7f4ed", "shadow": "#1d1c1a22", "shadow-lg": "#1d1c1a33", "glass": "rgba(247,244,237,.78)",
            "tbl-filter": "none"},
}
FLEX_PALETTE = ["#ff8a3d", "#4f8cff", "#6fbf8e", "#b9bec6", "#f2c14e", "#c084fc", "#ef6b73", "#4dd0e1"]

FLEX_CSS = r"""
/* ============================ FLEX LOOK ============================ */
.stApp, .stApp .stMarkdown, .stApp p, .stApp label, .stApp button, .stApp input, .stApp textarea,
.stApp [data-baseweb], .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp li {
  font-family: 'Plus Jakarta Sans', 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif; }
.stApp { background: var(--bg) !important; color: var(--ink); }
.stApp::after { content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 5; opacity: .07; mix-blend-mode: overlay;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='180' height='180'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='2' stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>"); }
.block-container { max-width: 1240px; padding-top: 1.1rem; }
[data-testid="stHeader"] { background: transparent !important; }
h1, h2, h3, h4 { font-weight: 800 !important; letter-spacing: -.025em !important; color: var(--ink); text-shadow: none !important; }
[data-testid="stCaptionContainer"], .stCaption, small { color: var(--soft) !important; }
hr { border-color: var(--line) !important; }
a { color: var(--accent); }

/* ---- text-style tabs (the site's nav look). Works with old (baseweb) and new (react-aria) Streamlit ---- */
[data-baseweb="tab-list"], [role="tablist"] { gap: 2px !important; padding: 0 !important; margin-bottom: 14px; background: transparent !important;
  border: 0 !important; border-bottom: 1px solid var(--line) !important; border-radius: 0 !important; backdrop-filter: none !important; box-shadow: none !important; }
button[data-baseweb="tab"], [data-baseweb="tab"], [role="tab"] { background: transparent !important; border: 0 !important; box-shadow: none !important;
  color: var(--soft) !important; font-weight: 600 !important; font-size: .9rem !important; padding: 10px 14px !important;
  border-radius: 12px 12px 0 0 !important; transition: color .2s, background .2s; transform: none !important; }
[role="tab"] *, [data-baseweb="tab"] * { color: inherit !important; font-weight: inherit !important; }
button[data-baseweb="tab"]:hover, [data-baseweb="tab"]:hover, [role="tab"]:hover { color: var(--ink) !important; background: var(--panel) !important; transform: none !important; }
button[data-baseweb="tab"][aria-selected="true"], [data-baseweb="tab"][aria-selected="true"], [role="tab"][aria-selected="true"] {
  color: var(--ink) !important; background: var(--panel) !important; box-shadow: inset 0 -2px 0 var(--accent) !important; transform: none !important; }
[data-baseweb="tab-highlight"], [data-testid="stTabHighlight"], [role="tablist"] > [aria-hidden="true"] { background-color: var(--accent) !important; height: 2px !important; }
[data-baseweb="tab-border"] { background-color: var(--line) !important; }
:root { --primary-color: var(--accent); }

/* ---- pill buttons ---- */
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button, [data-testid="stBaseButton-secondary"],
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-secondaryFormSubmit"], [data-testid="stBaseButton-primaryFormSubmit"] {
  border-radius: 999px !important; font-weight: 700 !important; padding: .5rem 1.25rem !important; border: 1px solid transparent !important;
  background: var(--btn1) !important; color: var(--btn-ink) !important; box-shadow: none !important; transition: transform .2s, filter .2s; }
.stButton > button:hover, .stDownloadButton > button:hover, [data-testid="stFormSubmitButton"] > button:hover {
  transform: translateY(-2px); filter: brightness(1.06); box-shadow: 0 10px 24px var(--shadow) !important; }
.stButton > button p, .stDownloadButton > button p, [data-testid="stFormSubmitButton"] > button p { color: var(--btn-ink) !important; }

/* ---- inputs ---- */
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="textarea"], [data-baseweb="select"] > div,
[data-testid="stTextInputRootElement"], [data-testid="stNumberInputContainer"] {
  background: var(--inp) !important; border-color: var(--line) !important; border-radius: 14px !important; box-shadow: none !important; }
[data-baseweb="input"] input, [data-baseweb="base-input"] input, textarea, [data-baseweb="select"] * { color: var(--ink) !important; }
[data-baseweb="input"] input::placeholder, textarea::placeholder { color: var(--soft) !important; opacity: .8; }
[data-baseweb="popover"] [role="listbox"], [data-baseweb="menu"] { background: var(--panel) !important; }
/* newer Streamlit (react-aria) form controls */
[data-testid="stSelectbox"] [role="group"], [data-testid="stMultiSelect"] [role="group"], [data-testid="stNumberInput"] [role="group"],
[data-testid="stDateInput"] [role="group"], [data-testid="stTimeInput"] [role="group"], [data-testid="stTextInput"] [role="group"],
[data-testid="stTextArea"] [role="group"], [data-testid="stSelectbox"] [data-testid="stSelectboxInput"] {
  background: var(--inp) !important; border: 1px solid var(--line) !important; border-radius: 14px !important; box-shadow: none !important; }
[data-testid="stSelectbox"] [role="group"] *, [data-testid="stMultiSelect"] [role="group"] *, [data-testid="stNumberInput"] [role="group"] *,
[data-testid="stDateInput"] [role="group"] *, [data-testid="stTextInput"] [role="group"] * { color: var(--ink) !important; }
[role="listbox"], [role="menu"], [data-testid="stSelectboxVirtualDropdown"], [data-testid="stPopover"] { background: var(--panel) !important; color: var(--ink) !important;
  border: 1px solid var(--line) !important; border-radius: 14px !important; }
[role="option"] { color: var(--ink) !important; } [role="option"]:hover, [role="option"][data-focused="true"] { background: var(--panel2) !important; }
[data-testid="stRadio"] label, [data-testid="stCheckbox"] label, [data-testid="stSlider"] label { color: var(--ink) !important; }
[data-testid="stSlider"] [role="slider"] { background: var(--accent) !important; }
[data-testid="stCheckbox"] label[data-selected="true"] > div:first-of-type { background-color: var(--accent) !important; }

[data-testid="stFileUploaderDropzone"] { background: var(--panel) !important; border: 1.5px dashed var(--line) !important; border-radius: 18px !important; }
[data-testid="stFileUploaderDropzone"] * { color: var(--ink) !important; }
[data-testid="stFileUploaderDropzone"] button, [data-testid="stFileUploaderDropzone"] button * { color: var(--btn-ink) !important; }
[data-testid="stForm"] { background: var(--panel) !important; border: 1px solid var(--line) !important; border-radius: 20px !important; }

/* ---- cards ---- */
.kpi, [data-testid="stMetric"], [data-testid="stExpander"], [data-testid="stDataFrame"], [data-testid="stDataEditor"],
[data-testid="stPlotlyChart"], [data-testid="stAlert"] { background: var(--panel) !important; border: 1px solid var(--line) !important;
  border-radius: 20px !important; box-shadow: none !important; backdrop-filter: none !important; }
[data-testid="stPlotlyChart"] { padding: 10px; }
.kpi, [data-testid="stMetric"] { padding: 16px 18px; transform: none; }
.kpi .val, [data-testid="stMetricValue"] { font-weight: 800 !important; letter-spacing: -.03em; color: var(--ink) !important; text-shadow: none !important; transform: none !important; }
.kpi:hover, [data-testid="stMetric"]:hover { transform: translateY(-3px); box-shadow: 0 18px 40px var(--shadow) !important; }
[data-testid="stExpander"] summary { font-weight: 700; }
[data-testid="stSidebar"] { background: var(--panel) !important; border-right: 1px solid var(--line); }
[data-testid="stSidebar"] > div:first-child { background: transparent !important; backdrop-filter: none !important; }
[data-testid="stAlert"] { border-left: 3px solid var(--accent) !important; }
[data-testid="stProgressBarTrack"] { background: var(--panel2) !important; border-radius: 999px !important; }
[data-testid="stProgressBarTrack"] > div { background: var(--accent) !important; border-radius: 999px !important; }
/* tables are drawn on a canvas by Streamlit: recolour them for the dark palette */
[data-testid="stDataFrame"] canvas, [data-testid="stDataEditor"] canvas { filter: var(--tbl-filter, none); }

/* ---- chips and labels ---- */
.fx-label { display: inline-flex; align-items: center; gap: 9px; font-size: .72rem; font-weight: 700; letter-spacing: .15em;
  text-transform: uppercase; color: var(--soft); }
.fx-label i, .avail i { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 12px var(--accent);
  animation: pulseDot 2s ease-in-out infinite; }
.avail { display: inline-flex; align-items: center; gap: 9px; font-size: .7rem; font-weight: 700; letter-spacing: .15em; color: var(--soft); }
@keyframes pulseDot { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: .45; transform: scale(.7); } }

/* ---- nav bar ---- */
.fx-nav { display: flex; align-items: center; justify-content: space-between; gap: 18px; flex-wrap: wrap; padding: 4px 0 14px; }
.fx-nav .links { display: flex; flex-wrap: wrap; gap: 2px; }
.fx-nav .nl { font-size: .8rem; font-weight: 600; color: var(--soft); padding: 7px 12px; border-radius: 999px; cursor: pointer;
  transition: background .2s, color .2s; user-select: none; }
.fx-nav .nl:hover { background: var(--panel); color: var(--ink); }
.fx-nav .chips { margin: 0; gap: 8px; }
.fx-nav .chip b { font-weight: 800; }

/* ---- the pull cord (switches light / dark) ---- */
.cord { position: fixed; top: 0; right: 178px; width: 30px; height: 120px; z-index: 1000002; cursor: pointer; transform-origin: top center; }
.cord .cl { position: absolute; left: 14px; top: 0; width: 2px; height: 64px; background: linear-gradient(var(--soft), var(--ink)); transition: height .25s cubic-bezier(.3, 1.6, .5, 1); }
.cord .cb { position: absolute; left: 6px; top: 60px; width: 18px; height: 24px; border-radius: 50% 50% 50% 50% / 38% 38% 62% 62%;
  background: radial-gradient(circle at 35% 28%, #fff0b8, #e0ad45 58%, #8a5f12); box-shadow: 0 4px 8px #0006; transition: top .25s cubic-bezier(.3, 1.6, .5, 1); }
.cord:hover .cl { height: 76px; } .cord:hover .cb { top: 72px; }
.cord.pulled .cl { height: 100px; } .cord.pulled .cb { top: 96px; }
.cord.swing { animation: cordSwing 1s ease; }
@keyframes cordSwing { 0% { transform: rotate(0); } 20% { transform: rotate(7deg); } 45% { transform: rotate(-5deg); } 70% { transform: rotate(2.5deg); } 100% { transform: rotate(0); } }
@media (max-width: 900px) { .cord { display: none; } }

/* ---- big type ---- */
.fx-h1 { font-size: clamp(2.5rem, 5.4vw, 4.8rem); line-height: 1.04; font-weight: 800; letter-spacing: -.04em; margin: 14px 0 18px; color: var(--ink); }
.fx-h2 { font-size: clamp(1.9rem, 3.8vw, 3.1rem); line-height: 1.08; font-weight: 800; letter-spacing: -.035em; margin: 0 0 10px; color: var(--ink); }
.fx-h2s { font-size: clamp(1.5rem, 2.6vw, 2.1rem); line-height: 1.1; font-weight: 800; letter-spacing: -.03em; margin: 6px 0 0; color: var(--ink); }
.fx-big { font-size: clamp(2.5rem, 6.6vw, 5.6rem); line-height: 1.0; font-weight: 800; letter-spacing: -.045em; margin: 16px 0 14px; color: var(--ink); }
.fx-sub { font-size: 1.02rem; line-height: 1.6; color: var(--soft); max-width: 560px; margin: 0 0 22px; }
.mut { color: var(--soft); opacity: .8; }

/* ---- pills (calls to action) ---- */
.pill { display: inline-flex; align-items: center; gap: 14px; padding: 13px 24px; border-radius: 999px; font-weight: 700; font-size: .95rem;
  cursor: pointer; border: 1px solid var(--line); user-select: none; transition: transform .2s, box-shadow .2s, background .2s; margin: 0 10px 10px 0; }
.pill:hover { transform: translateY(-2px); }
.pill-dark { background: var(--btn1); color: var(--btn-ink); border-color: transparent; }
.stApp .pill-dark, .stApp .pill-dark * { color: var(--btn-ink) !important; }
.stApp .pill-ghost { color: var(--ink) !important; }
.stApp .notepad, .stApp .notepad * { color: #1d1c1a !important; }
.stApp .room, .stApp .room * { color: #fff !important; }
.stApp .door .plate { color: #4a3406 !important; }
.stApp .fx-nav .nl { color: var(--soft) !important; } .stApp .fx-nav .nl:hover { color: var(--ink) !important; }
.stApp .fx-h1, .stApp .fx-h2, .stApp .fx-h2s, .stApp .fx-big, .stApp .fx-i { color: var(--ink) !important; }
.stApp .fx-sub, .stApp .mut, .stApp .fx-label, .stApp .avail, .stApp .scroll { color: var(--soft) !important; }
.stApp .sc b { color: var(--ink) !important; } .stApp .sc small { color: var(--soft) !important; } .stApp .sc em { color: #6fbf8e !important; }
.stApp .step b { color: var(--ink) !important; } .stApp .step .t { color: var(--soft) !important; } .stApp .step .n { color: var(--accent) !important; }
.pill-dark:hover { box-shadow: 0 14px 30px var(--shadow); }
.pill-ghost { background: transparent; color: var(--ink); }
.pill-ghost:hover { background: var(--panel); }
.knob { width: 36px; height: 21px; border-radius: 999px; border: 2px solid currentColor; opacity: .75; position: relative; display: inline-block; }
.knob::after { content: ""; position: absolute; top: 2px; left: 2px; width: 13px; height: 13px; border-radius: 50%; background: currentColor; transition: transform .25s; }
.pill:hover .knob::after { transform: translateX(15px); }

/* ---- hero ---- */
.fx-hero { position: relative; display: grid; grid-template-columns: 1.12fr .88fr; gap: 30px; align-items: center; min-height: 500px; padding: 24px 0 64px; }
.fx-hero-foot { position: absolute; left: 0; right: 0; bottom: 8px; display: flex; justify-content: space-between; align-items: center; }
.fx-hero-foot .scroll { font-size: .7rem; font-weight: 700; letter-spacing: .15em; color: var(--soft); }
@media (max-width: 920px) { .fx-hero { grid-template-columns: 1fr; min-height: 0; } .fx-stack { display: none; } }
.fx-i { font-weight: 600; color: var(--ink); }
.notepad { position: relative; display: inline-block; margin-left: .12em; padding: .06em .42em .1em; background: #fbfaf6; color: #1d1c1a; border-radius: 12px;
  box-shadow: 0 16px 30px #0006, inset 0 -3px 0 #0000000d; transform: rotate(-1.8deg); vertical-align: middle; font-size: .76em; }
.notepad .rings { position: absolute; top: -12px; left: 9%; right: 9%; display: flex; justify-content: space-between; }
.notepad .rings i { width: 7px; height: 19px; border-radius: 6px; background: linear-gradient(90deg, #8d949b, #eef0f2 50%, #737a81); border: 1px solid #596066; box-shadow: 0 2px 3px #0005; }
.words { position: relative; display: inline-block; width: 7.7em; height: 1.18em; overflow: hidden; vertical-align: top; perspective: 500px; }
.words b { position: absolute; left: 0; top: 0; white-space: nowrap; font-weight: 700; opacity: 0; animation: wordCycle 12s infinite; transform-origin: 50% 100%; }
.words b:nth-child(2) { animation-delay: 3s; } .words b:nth-child(3) { animation-delay: 6s; } .words b:nth-child(4) { animation-delay: 9s; }
@keyframes wordCycle { 0% { opacity: 0; transform: translateY(75%) rotateX(-85deg); } 4%, 23% { opacity: 1; transform: none; }
  27%, 100% { opacity: 0; transform: translateY(-75%) rotateX(85deg); } }

/* 3D card stack (right side of the hero) */
.fx-stack { position: relative; height: 430px; perspective: 1200px; transform-style: preserve-3d; }
.sc { position: absolute; border-radius: 22px; background: var(--panel); border: 1px solid var(--line); padding: 18px 20px; box-shadow: 0 34px 60px var(--shadow);
  backdrop-filter: blur(8px); }
.sc small { display: block; font-size: .68rem; letter-spacing: .14em; text-transform: uppercase; color: var(--soft); font-weight: 700; margin-bottom: 4px; }
.sc b { display: block; font-size: 2.1rem; font-weight: 800; letter-spacing: -.035em; color: var(--ink); }
.sc em { font-style: normal; font-size: .78rem; font-weight: 700; color: #6fbf8e; }
.sc1 { left: 0; top: 2%; width: 56%; transform: rotateY(-18deg) rotateX(8deg) translateZ(40px); animation: floatA 7s ease-in-out infinite; }
.sc2 { right: 0; top: 38%; width: 52%; transform: rotateY(-18deg) rotateX(8deg) translateZ(95px); animation: floatB 8s ease-in-out infinite; }
.sc3 { left: 10%; bottom: 0; width: 52%; transform: rotateY(-18deg) rotateX(8deg) translateZ(20px); animation: floatC 9s ease-in-out infinite; display: flex; align-items: center; gap: 16px; }
@keyframes floatA { 0%, 100% { transform: rotateY(-18deg) rotateX(8deg) translateZ(40px) translateY(0); } 50% { transform: rotateY(-18deg) rotateX(8deg) translateZ(40px) translateY(-14px); } }
@keyframes floatB { 0%, 100% { transform: rotateY(-18deg) rotateX(8deg) translateZ(95px) translateY(0); } 50% { transform: rotateY(-18deg) rotateX(8deg) translateZ(95px) translateY(12px); } }
@keyframes floatC { 0%, 100% { transform: rotateY(-18deg) rotateX(8deg) translateZ(20px) translateY(0); } 50% { transform: rotateY(-18deg) rotateX(8deg) translateZ(20px) translateY(-10px); } }
.spark { height: 50px; margin-top: 8px; background: linear-gradient(var(--accent), transparent);
  clip-path: polygon(0 78%, 14% 58%, 28% 68%, 43% 38%, 58% 50%, 73% 18%, 88% 30%, 100% 8%, 100% 100%, 0 100%); opacity: .9; }
.bars { display: flex; align-items: flex-end; gap: 8px; height: 92px; margin-top: 10px; }
.bars i { flex: 1; border-radius: 6px 6px 2px 2px; background: linear-gradient(var(--accent), #ffffff22); animation: barGrow 1.4s cubic-bezier(.2, .8, .2, 1) backwards; }
.bars i:nth-child(1) { height: 38%; } .bars i:nth-child(2) { height: 62%; animation-delay: .08s; } .bars i:nth-child(3) { height: 48%; animation-delay: .16s; }
.bars i:nth-child(4) { height: 82%; animation-delay: .24s; } .bars i:nth-child(5) { height: 66%; animation-delay: .32s; } .bars i:nth-child(6) { height: 96%; animation-delay: .4s; }
@keyframes barGrow { from { height: 4%; opacity: .2; } }
.donut { position: relative; flex: none; width: 84px; height: 84px; border-radius: 50%;
  background: conic-gradient(var(--accent) 0 38%, #4f8cff 0 64%, #6fbf8e 0 82%, #b9bec6 0); }
.donut::after { content: ""; position: absolute; inset: 19px; border-radius: 50%; background: var(--panel); }

/* ---- the doors ---- */
.fx-doors { padding: 36px 0 22px; text-align: center; }
.fx-doors .fx-sub { margin: 0 auto; }
.door-row { display: flex; flex-wrap: wrap; justify-content: center; gap: 38px; margin-top: 40px; }
.door-wrap { position: relative; width: 176px; height: 264px; perspective: 1000px; cursor: pointer; border-radius: 92px 92px 6px 6px; background: #0b0d10;
  box-shadow: 0 0 0 8px var(--panel2), 0 30px 50px var(--shadow-lg); transition: transform .4s; }
.door-wrap:hover { transform: translateY(-4px); }
.door-wrap .room { position: absolute; inset: 0; border-radius: inherit; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px;
  padding: 22px 14px 22px 52px; text-align: center; background: radial-gradient(circle at 60% 80%, var(--glow), #0b0d10 74%); color: #fff; }
.room-ic { font-size: 2.5rem; filter: drop-shadow(0 4px 10px #0008); }
.room-tx { font-size: .78rem; font-weight: 600; line-height: 1.4; opacity: .95; }
.room-go { font-size: .66rem; font-weight: 800; letter-spacing: .16em; opacity: .75; }
.door { position: absolute; inset: 0; border-radius: inherit; transform-origin: left center; transition: transform 1s cubic-bezier(.2, .8, .2, 1);
  background: var(--door); box-shadow: inset 0 0 0 3px #ffffff1c, inset -16px 0 28px #0000003a; transform-style: preserve-3d; }
.door-wrap:hover .door, .door-wrap.open .door { transform: rotateY(-78deg); }
.door .pn { position: absolute; left: 17%; right: 17%; box-shadow: inset 0 4px 12px #0006, 0 1px 0 #ffffff26; background: #0000001c; }
.door .pn1 { top: 9%; height: 36%; border-radius: 60px 60px 6px 6px; } .door .pn2 { top: 53%; height: 33%; border-radius: 8px; }
.door .plate { position: absolute; left: 50%; top: 49%; transform: translate(-50%, -50%); padding: 4px 10px; font: 700 .56rem/1 'JetBrains Mono', monospace; letter-spacing: .15em;
  background: linear-gradient(#f8e08f, #b98a2b); color: #4a3406; border-radius: 3px; box-shadow: 0 2px 5px #0007; white-space: nowrap; }
.door .hd { position: absolute; right: 11%; top: 57%; width: 15px; height: 15px; border-radius: 50%;
  background: radial-gradient(circle at 35% 30%, #fff3b8, #c9992f 60%, #7a5712); box-shadow: 0 2px 6px #0008; }
.d-blue { --door: linear-gradient(165deg, #3f80ee, #19408b); --glow: #3f80ee; }
.d-grey { --door: linear-gradient(165deg, #5b616b, #2b3036); --glow: #8a93a3; }
.d-green { --door: linear-gradient(165deg, #86b897, #4a7a5c); --glow: #6fbf8e; }
.d-orange { --door: linear-gradient(165deg, #ee8238, #a5441a); --glow: #ff8a3d; }

/* ---- steps ---- */
.fx-steps { display: grid; grid-template-columns: .9fr 1.1fr; gap: 44px; padding: 70px 0 28px; margin-top: 44px; border-top: 1px solid var(--line); }
.bignum { font-size: clamp(5rem, 13vw, 10rem); font-weight: 800; letter-spacing: -.06em; line-height: .86; color: transparent;
  background: linear-gradient(var(--ink), var(--soft)); -webkit-background-clip: text; background-clip: text; }
.step { display: grid; grid-template-columns: 64px 1fr; gap: 14px; padding: 18px 0; border-bottom: 1px solid var(--line); }
.step .n { font: 700 .8rem 'JetBrains Mono', monospace; color: var(--accent); letter-spacing: .1em; padding-top: 4px; }
.step b { display: block; font-size: 1.15rem; font-weight: 800; letter-spacing: -.02em; color: var(--ink); margin-bottom: 2px; }
.step span.t { color: var(--soft); font-size: .93rem; line-height: 1.55; }
@media (max-width: 900px) { .fx-steps { grid-template-columns: 1fr; } }

/* ---- call to action + compact header ---- */
.fx-cta { padding: 64px 0 26px; }
.fx-compact { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; padding: 6px 0 14px; }

/* ---- reveal on load ---- */
.kpi, [data-testid="stPlotlyChart"], [data-testid="stMetric"], [data-testid="stDataFrame"], [data-testid="stExpander"], .feat { animation: dpUp .6s cubic-bezier(.2, .7, .2, 1) backwards; }
.door-wrap { animation: dpUp .8s cubic-bezier(.2, .7, .2, 1) backwards; }
.door-wrap:nth-child(2) { animation-delay: .08s; } .door-wrap:nth-child(3) { animation-delay: .16s; } .door-wrap:nth-child(4) { animation-delay: .24s; }
@media (prefers-reduced-motion: reduce) { .sc, .words b, .bars i, .fx-label i, .avail i, .door, .cord { animation: none !important; transition: none !important; } .words b:first-child { opacity: 1; } }
"""


def _l(*parts):
    """Join into one line: no blank lines or indentation, so Markdown keeps it as HTML."""
    return "".join(parts)


def nav_html(clock="10:09pm", date="3 November, 2026"):
    links = [("go-home", "Home"), ("go-insights", "Insights"), ("go-toolkit", "Toolkit"), ("go-dash", "Dashboard"),
             ("go-ai", "Ask AI"), ("go-projects", "Projects")]
    return _l('<div class="fx-nav"><div class="links">',
              "".join(f'<span class="nl {c}">{t}</span>' for c, t in links),
              '</div><div class="chips"><span class="chip">Local time <b class="dp-clock">', escape(clock), '</b></span>',
              '<span class="chip dp-date">', escape(date), '</span></div></div>',
              '<div class="cord" title="Pull to switch light / dark"><i class="cl"></i><i class="cb"></i></div>')


def hero_html(sub="Drop in any spreadsheet and get clean data, charts, statistical tests and plain-English answers in minutes.",
              cta="Start a project", cta2="See what I can do"):
    rings = "<i></i>" * 9
    words = "".join(f"<b>{w}</b>" for w in ("Data Analyst", "Chart Maker", "Stats Wizard", "SQL Explorer"))
    stack = _l('<div class="fx-stack tilt">',
               '<div class="sc sc1"><small>Revenue</small><b>$248,320</b><em>▲ 18.4%</em><div class="spark"></div></div>',
               '<div class="sc sc2"><small>Orders by month</small><div class="bars"><i></i><i></i><i></i><i></i><i></i><i></i></div></div>',
               '<div class="sc sc3"><div class="donut"></div><div><small>Traffic mix</small><b>38%</b></div></div></div>')
    return _l('<div class="fx-hero"><div class="fx-hero-l">',
              '<span class="fx-label"><i></i> Your AI data analyst</span>',
              '<div class="fx-h1">Hi, I\'m DataPilot.<br><span class="fx-i">I am a</span> ',
              f'<span class="notepad"><span class="rings">{rings}</span><span class="words">{words}</span></span></div>',
              f'<p class="fx-sub">{sub}</p>',
              f'<span class="pill pill-dark go-start">{escape(cta)} <span class="knob"></span></span>',
              f'<span class="pill pill-ghost go-doors">{escape(cta2)}</span></div>',
              stack,
              '<div class="fx-hero-foot"><span class="avail"><i></i> AVAILABLE FOR NEW DATA</span>',
              '<span class="scroll">SCROLL ↓</span></div></div>')


DOORS = [("d-blue", "go-insights", "INSIGHTS", "📈", "KPIs, charts and a plain-English summary of your data."),
         ("d-grey", "go-toolkit", "TOOLKIT", "🧰", "Clean, pivot, test, regress, cluster and query with SQL."),
         ("d-green", "go-dash", "DASHBOARD", "📊", "A Power BI style dashboard, maps and DAX, built for you."),
         ("d-orange", "go-ai", "ASK AI", "🤖", "Ask questions about your data and get answers with numbers.")]


def doors_html():
    doors = "".join(
        _l(f'<div class="door-wrap tilt {c} {g}"><div class="room"><span class="room-ic">{ic}</span>',
           f'<span class="room-tx">{escape(tx)}</span><span class="room-go">CLICK TO ENTER →</span></div>',
           f'<div class="door"><i class="pn pn1"></i><i class="pn pn2"></i><span class="plate">{nm}</span><i class="hd"></i></div></div>')
        for c, g, nm, ic, tx in DOORS)
    return _l('<div class="fx-doors"><div class="fx-h2">Magic happens behind the doors</div>',
              '<p class="fx-sub">Pick a door. Hover to peek inside, click to walk in.</p>',
              f'<div class="door-row">{doors}</div></div>')


STEPS = [("01", "Upload", "CSV, Excel, JSON, a SQLite file or a Google Sheet link. No setup."),
         ("02", "Clean", "Automatic tidy-up plus a no-code recipe with undo. Your file is never changed."),
         ("03", "Analyze", "Insights, statistics, tests, regression, segments and SQL, all in one place."),
         ("04", "Share", "Excel, PowerPoint, PDF and Power BI packs, plus saved projects you can reopen.")]


def steps_html():
    items = "".join(f'<div class="step"><span class="n">{n}</span><div><b>{t}</b><span class="t">{escape(d)}</span></div></div>'
                    for n, t, d in STEPS)
    return _l('<div class="fx-steps"><div><span class="fx-label"><i></i> How it works</span>',
              '<div class="bignum">04</div><div class="fx-h2s">steps from raw file<br>to real answer.</div></div>',
              f'<div>{items}</div></div>')


def cta_html(line1="Got a data project?", line2="Let's analyze it together.",
             sub="Add your data below and the insights appear automatically.", cta="Start a project"):
    return _l('<div class="fx-cta"><span class="avail"><i></i> AVAILABLE FOR NEW DATA</span>',
              f'<div class="fx-big">{escape(line1)}<br><span class="mut">{escape(line2)}</span></div>',
              f'<p class="fx-sub">{escape(sub)}</p><span class="pill pill-dark go-start">{escape(cta)} <span class="knob"></span></span></div>',
              '<div class="anchor-add-data"></div>')


def compact_html(username):
    return _l('<div class="fx-compact"><div><span class="fx-label"><i></i> Your workspace</span>',
              f'<div class="fx-h2s">Hi, {escape(str(username))}.</div></div>',
              '<span class="avail"><i></i> ANALYSIS READY</span></div><div class="anchor-add-data"></div>')
