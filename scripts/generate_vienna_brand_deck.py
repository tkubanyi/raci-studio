"""CLI wrapper — generate Vienna brand deck from the canonical Word document."""

from __future__ import annotations

from pathlib import Path

from presentation_studio.content_parser import load_docx
from presentation_studio.deck_builder import DeckBuildOptions, build_deck
from pptx import Presentation

REPO = Path(__file__).resolve().parent.parent
DOCX_PATH = Path(
    r"C:\Users\tkubanyi001\OneDrive - PwC\Documents\Customers\Global Payments\Project Vienna_discovery phase.docx"
)
OUTPUT_PPTX = Path(
    r"C:\Users\tkubanyi001\OneDrive - PwC\Documents\Customers\Global Payments\Project_Vienna_Discovery_Phase_Brand.pptx"
)
BRAND_PPTX = Path(
    r"C:\Users\tkubanyi001\OneDrive - PwC\Documents\Brand package\Graphic elements_correct.pptx"
)
BRAND_JSON = REPO / "data" / "presentation-templates" / "graphic_elements_correct.brand.summary.json"


def generate() -> Path:
    doc = load_docx(DOCX_PATH)
    options = DeckBuildOptions(
        output_path=OUTPUT_PPTX,
        brand_pptx=BRAND_PPTX if BRAND_PPTX.exists() else REPO / "data/presentation-templates/Project_Vienna_Discovery_Phase.pptx",
        brand_json=BRAND_JSON,
        footer="Project Vienna | Global Payments Europe",
        client_line="Global Payments Europe | PwC",
    )
    return build_deck(doc, options)


if __name__ == "__main__":
    out = generate()
    print(f"Created: {out} ({len(Presentation(str(out)).slides)} slides)")
