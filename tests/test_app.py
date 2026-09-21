"""app.py — display-only checks (source label).

`app.py` is the Streamlit frontend; per this task's constraint, only its
source display changed (source_label()), everything else is untouched. This
module imports app.py directly (safe outside a real Streamlit run — its
module-level st.* calls only warn about a missing ScriptRunContext, they
don't raise) to unit-test that one pure function without needing a full
AppTest run.
"""

from __future__ import annotations

from pathlib import Path

import app
from src.schemas.common import ResearchMode
from src.schemas.tender import Tender, TenderSource

_APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def _tender(research_mode: ResearchMode) -> Tender:
    source = TenderSource.SIMAP if research_mode == ResearchMode.SIMAP_MCP else TenderSource.LOCAL_SAMPLE
    return Tender(id="t-1", title="X", source=source, research_mode=research_mode)


def test_source_label_shows_simap_only_for_real_simap_results():
    """Requirement 3 — correct source_type display: never show "SIMAP"
    unless research_mode says a live SimapAdapter call actually produced it."""
    assert app.source_label(_tender(ResearchMode.SIMAP_MCP)) == "SIMAP"


def test_source_label_shows_local_sample_for_the_fallback():
    assert app.source_label(_tender(ResearchMode.LOCAL_FALLBACK)) == "Local Sample"


def test_search_click_end_to_end_shows_local_sample_not_simap():
    """Full AppTest run: in this environment (SIMAP MCP unconfigured), a
    Search must render "Local Sample" and must never render "SIMAP" — the
    app must not claim to use SIMAP when it technically isn't."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(_APP_PATH), default_timeout=60)
    at.run()
    at.text_input[0].set_value(
        "Find Swiss tenders related to cloud infrastructure, managed services and cybersecurity"
    )
    next(b for b in at.button if b.label == "Search").click().run()

    assert not at.exception
    rendered = "\n".join(m.value for m in at.markdown)
    assert "Local Sample" in rendered
    assert "SIMAP" not in rendered
