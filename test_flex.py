"""Tests for the Flex look (datapilot_flex.py) and the 3D effects script (datapilot_fx.py)."""
import re
import shutil
import subprocess
import tempfile

import pytest

import datapilot_flex as fl
import datapilot_fx as fx


@pytest.mark.parametrize("html", [fl.nav_html(), fl.hero_html(), fl.doors_html(), fl.steps_html(), fl.cta_html(),
                                  fl.compact_html("ann")])
def test_html_is_one_block_markdown_will_not_break(html):
    assert "\n" not in html and "  " not in html.replace("&nbsp;", "")     # no blank lines / indented code blocks
    assert html.count("<div") == html.count("</div>")


def test_doors_cover_the_four_areas_and_are_clickable():
    h = fl.doors_html()
    for cls in ("go-insights", "go-toolkit", "go-dash", "go-ai"):
        assert f"door-wrap" in h and cls in h
    assert h.count('class="door-wrap') == 4 and "Magic happens behind the doors" in h
    assert "rotateY" in fl.FLEX_CSS and ".door-wrap:hover .door" in fl.FLEX_CSS


def test_hero_has_rotating_words_notepad_and_buttons():
    h = fl.hero_html()
    assert h.count("<b>") >= 4 and "notepad" in h and "go-start" in h and "go-doors" in h
    assert "wordCycle" in fl.FLEX_CSS


def test_user_text_is_escaped():
    assert "<script>" not in fl.compact_html("<script>alert(1)</script>")
    assert "&lt;script&gt;" in fl.compact_html("<script>alert(1)</script>")


def test_nav_has_cord_clock_and_links():
    h = fl.nav_html("1:05pm", "5 November, 2026")
    assert "cord" in h and "dp-clock" in h and "1:05pm" in h
    for cls in ("go-home", "go-insights", "go-toolkit", "go-dash", "go-ai", "go-projects"):
        assert cls in h


def test_css_braces_balance_and_support_new_and_old_streamlit():
    css = fl.FLEX_CSS
    assert css.count("{") == css.count("}")
    assert '[role="tab"]' in css and '[data-baseweb="tab"]' in css          # both tab markups
    assert "stSelectbox" in css and "SelectionIndicator" not in css      # selectbox restyled; indicator lives in app CSS


def test_both_palettes_define_every_variable_the_css_uses():
    used = set(re.findall(r"var\(--([a-z0-9-]+)", fl.FLEX_CSS))
    provided = set(fl.FLEX_VARS[True]) | {"bg", "accent"}
    missing = {u for u in used if u not in provided and u not in ("mx", "my", "door", "glow", "tbl-filter")}
    assert not missing, missing
    assert set(fl.FLEX_VARS[True]) == set(fl.FLEX_VARS[False])


def test_fx_html_installs_once_and_is_safe():
    h = fx.fx_html("Galaxy", "#ff8a3d", True, True, 0.5)
    assert h.startswith("<script>") and h.endswith("</script>") and h.count("</script>") == 1
    assert '"bg": "Galaxy"' in h and '"opacity": 0.5' in h
    assert fx.fx_html("nonsense")                                               # unknown background falls back
    assert "Neural network" in fx.fx_html("nonsense")


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_injected_javascript_has_valid_syntax():
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(fx.fx_script())
    r = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_script_uses_new_and_old_tab_markup_and_clicks_the_real_checkbox():
    js = fx.fx_script()
    assert '[role="tab"]' in js and "input[type=\"checkbox\"]" in js and "__dpfx" in js
    assert "eval(" not in js and "fetch(" not in js and "XMLHttpRequest" not in js      # no network, no eval
