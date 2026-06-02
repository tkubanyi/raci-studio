"""Tests for Presentation Studio parsing and build."""

from pathlib import Path

from presentation_studio.content_parser import load_plain_text, paragraphs_to_document
from presentation_studio.deck_builder import DeckBuildOptions, build_deck

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / "data" / "presentation-templates" / "Project_Vienna_Discovery_Phase.pptx"
BRAND_JSON = REPO / "data" / "presentation-templates" / "graphic_elements_correct.brand.summary.json"


def test_plain_text_parse():
    doc = load_plain_text("Alpha Project\nPhase 1\n\nBody paragraph one.\n\nBody two.")
    assert doc["title"] == "Alpha Project"
    assert doc["subtitle"] == "Phase 1"


def test_build_minimal_deck(tmp_path):
    if not TEMPLATE.exists() or not BRAND_JSON.exists():
        return
    doc = paragraphs_to_document(["T", "S", "Only content paragraph for what section."])
    out = tmp_path / "test_out.pptx"
    build_deck(
        doc,
        DeckBuildOptions(
            output_path=out,
            brand_pptx=TEMPLATE,
            brand_json=BRAND_JSON,
        ),
    )
    assert out.exists()
    assert out.stat().st_size > 10_000
