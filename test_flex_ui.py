"""UI tests for the Flex look: landing page, doors, compact header after data, light/dark switch."""
import sys
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
PW = "Passw0rd!x"


def _btn(at, label):
    return next(b for b in at.button if b.label == label)


def _css(at):
    return " ".join(m.value for m in at.markdown)


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAPILOT_HOME", str(tmp_path))
    monkeypatch.delenv("DATAPILOT_DB", raising=False)
    monkeypatch.delenv("DATAPILOT_STORAGE", raising=False)
    monkeypatch.syspath_prepend(str(ROOT))
    for m in ("datapilot_db", "datapilot_tools", "datapilot_fx", "datapilot_flex"):
        sys.modules.pop(m, None)
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()


def _signup(at, name="designer"):
    at.text_input(key="rg_user").input(name)
    at.text_input(key="rg_pw").input(PW)
    at.text_input(key="rg_pw2").input(PW)
    _btn(at, "Create account").click()
    return at.run()


def test_login_page_shows_the_flex_landing(fresh):
    assert not fresh.exception, [e.value for e in fresh.exception]
    css = _css(fresh)
    assert "Hi, I'm DataPilot" in css and css.count('class="door-wrap') == 4 and "fx-nav" in css
    assert any(t.label == "Dark mode" for t in fresh.toggle)


def test_landing_then_compact_header_after_data(fresh):
    at = _signup(fresh)
    assert not at.exception
    css = _css(at)
    assert "Magic happens behind the doors" in css and "steps from raw file" in css and "Got a data project?" in css
    at.radio[0].set_value("Try sample data")
    at = at.run()
    assert not at.exception, [e.value for e in at.exception]
    css = _css(at)
    assert "fx-compact" in css and "Hi, DataPilot" not in css and "Magic happens" not in css
    assert any("Analyst Toolkit" in t.label for t in at.tabs)


def test_dark_light_switch_changes_the_palette_and_is_remembered(fresh):
    at = _signup(fresh)
    assert "--bg:#1b2025" in _css(at)
    at.toggle(key="flex_dark").set_value(False)
    at = at.run()
    assert not at.exception and "--bg:#ebe7de" in _css(at) and "--bg:#1b2025" not in _css(at)
    at.toggle(key="flex_dark").set_value(True)
    assert "--bg:#1b2025" in _css(at.run())


def test_removing_data_brings_the_landing_back(fresh):
    at = _signup(fresh)
    at.radio[0].set_value("Try sample data")
    at = at.run()
    assert "fx-compact" in _css(at)
    at.radio[0].set_value("Type data")
    at = at.run()
    assert not at.exception
