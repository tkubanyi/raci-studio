"""Finalize presentation template map with design tokens and slide catalog."""

from __future__ import annotations

import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


def extract_theme_from_pptx(pptx_path: Path) -> dict[str, str]:
    colors: dict[str, str] = {}
    with zipfile.ZipFile(pptx_path) as z:
        theme_files = sorted(n for n in z.namelist() if n.startswith("ppt/theme/theme") and n.endswith(".xml"))
        if not theme_files:
            return colors
        root = ET.fromstring(z.read(theme_files[0]))
        ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
        clr_scheme = root.find(".//a:clrScheme", ns)
        if clr_scheme is None:
            return colors
        for child in clr_scheme:
            tag = child.tag.split("}")[-1]
            srgb = child.find("a:srgbClr", ns)
            sys_clr = child.find("a:sysClr", ns)
            if srgb is not None and srgb.get("val"):
                colors[tag] = f"#{srgb.get('val')}"
            elif sys_clr is not None and sys_clr.get("lastClr"):
                colors[tag] = f"#{sys_clr.get('lastClr')}"
    return colors


def first_text_from_shape(shape: dict) -> str | None:
    text = shape.get("text")
    if text:
        for para in text.get("paragraphs", []):
            t = para.get("text", "").strip()
            if t:
                return t
    for child in shape.get("children", []):
        t = first_text_from_shape(child)
        if t:
            return t
    return None


def slide_title(slide: dict) -> str | None:
    for shape in slide.get("shapes", []):
        name = (shape.get("name") or "").lower()
        ph = shape.get("placeholder_format") or {}
        ph_type = str(ph.get("type", ""))
        if "title" in name or "CENTER_TITLE" in ph_type or "TITLE" in ph_type:
            t = first_text_from_shape(shape)
            if t:
                return t
    for shape in slide.get("shapes", []):
        t = first_text_from_shape(shape)
        if t and len(t) < 120:
            return t
    return None


def collect_text_blocks(slide: dict, max_blocks: int = 6) -> list[str]:
    blocks: list[str] = []

    def walk(shapes):
        for shape in shapes:
            text = shape.get("text")
            if text:
                for para in text.get("paragraphs", []):
                    t = para.get("text", "").strip()
                    if t and t not in blocks:
                        blocks.append(t)
            walk(shape.get("children", []))

    walk(slide.get("shapes", []))
    return blocks[:max_blocks]


def collect_fonts(template: dict) -> dict:
    names: set[str] = set()
    sizes: set[float] = set()

    def walk(shapes):
        for shape in shapes:
            text = shape.get("text", {})
            for para in text.get("paragraphs", []):
                for source in [para, *para.get("runs", [])]:
                    font = source.get("font", {})
                    if font.get("name"):
                        names.add(font["name"])
                    if font.get("size_pt"):
                        sizes.add(font["size_pt"])
            walk(shape.get("children", []))

    for slide in template.get("slides", []):
        walk(slide.get("shapes", []))

    return {
        "families": sorted(names),
        "sizes_pt": sorted(sizes),
    }


def build_design_tokens(theme: dict[str, str], palette: dict) -> dict:
    return {
        "brand_palette": {
            "primary_orange": theme.get("accent1", "#FD5108"),
            "orange_mid": theme.get("accent2", "#FE7C39"),
            "orange_light": theme.get("accent3", "#FFAA72"),
            "neutral_dark": theme.get("dk1", "#000000"),
            "neutral_white": theme.get("lt1", "#FFFFFF"),
            "neutral_gray_light": theme.get("lt2", "#EBEBEB"),
            "accent_gray_1": theme.get("accent4", "#A1A8B3"),
            "accent_gray_2": theme.get("accent5", "#B5BCC4"),
            "accent_gray_3": theme.get("accent6", "#CBD1D6"),
        },
        "surface_colors": {
            "page_background": "#FFFFFF",
            "panel_light": "#F5F7F8",
            "panel_warm_1": "#FFF5ED",
            "panel_warm_2": "#FFE8D4",
            "panel_warm_3": "#FFE5D7",
            "panel_warm_4": "#FFCDA8",
            "divider": "#DFE3E6",
            "body_text": "#434343",
        },
        "gradient_orange_scale": [
            "#FD5108",
            "#FE7C39",
            "#FFAA72",
            "#FFCDA8",
            "#FFE8D4",
        ],
        "all_fill_colors": palette.get("fill_colors", []),
        "all_font_colors": palette.get("font_colors", []),
    }


def build_slide_catalog(slides: list[dict]) -> list[dict]:
    catalog = []
    for slide in slides:
        catalog.append(
            {
                "index": slide["index"],
                "layout_name": slide["layout_name"],
                "role": slide["role"],
                "title": slide_title(slide),
                "text_blocks": collect_text_blocks(slide),
                "shape_count": slide["shape_count"],
                "color_summary": slide.get("color_summary", {}),
            }
        )
    return catalog


def build_shape_patterns(slides: list[dict]) -> dict:
    layout_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    for slide in slides:
        layout_counts[slide["layout_name"]] = layout_counts.get(slide["layout_name"], 0) + 1
        role_counts[slide["role"]] = role_counts.get(slide["role"], 0) + 1
    return {
        "layouts_by_frequency": dict(sorted(layout_counts.items(), key=lambda x: -x[1])),
        "roles_by_frequency": dict(sorted(role_counts.items(), key=lambda x: -x[1])),
        "common_layouts": {
            "title_cover": "Title Slide",
            "section_divider": "Section Header",
            "standard_content": "Title Only",
            "photo_content": "Content Photo 4",
            "stats_row": "Four Stat Boxes",
            "closing": "Conclusion 1",
        },
    }


def finalize_template(
    template_path: Path,
    pptx_path: Path,
    target_name: str,
    target_path: str,
    extraction_note: str | None = None,
) -> tuple[dict, dict]:
    template = json.loads(template_path.read_text(encoding="utf-8"))
    theme = extract_theme_from_pptx(pptx_path)

    template["template_id"] = "proposal_global_payments_v3"
    template["target_file"] = target_name
    template["target_path"] = target_path
    template["extraction"] = {
        "structure_source": pptx_path.name,
        "structure_source_path": str(pptx_path),
        "note": extraction_note
        or "Structure extracted from the closest available PPTX revision.",
    }
    template["theme"] = {"colors": theme}
    template["design_tokens"] = build_design_tokens(theme, template.get("palette", {}))
    template["typography"] = collect_fonts(template)
    template["slide_catalog"] = build_slide_catalog(template["slides"])
    template["shape_patterns"] = build_shape_patterns(template["slides"])

    summary = {
        "template_id": template["template_id"],
        "target_file": template["target_file"],
        "target_path": template["target_path"],
        "extraction": template["extraction"],
        "canvas": template["canvas"],
        "theme": template["theme"],
        "design_tokens": template["design_tokens"],
        "typography": template["typography"],
        "shape_patterns": template["shape_patterns"],
        "slide_count": template["slide_count"],
        "slide_catalog": template["slide_catalog"],
        "layouts_used": template["layouts_used"],
        "replication_notes": template["replication_notes"],
        "full_map_path": template_path.name,
    }

    return template, summary


def main() -> int:
    base = Path(__file__).resolve().parent.parent / "data" / "presentation-templates"
    template_path = base / "proposal_global_payments_v3.template.json"
    pptx_path = base / "Proposal_Global_Payments_V2.pptx"

    template, summary = finalize_template(
        template_path=template_path,
        pptx_path=pptx_path,
        target_name="Proposal_Global_Payments_V3.pptx",
        target_path=r"C:\Users\tkubanyi001\OneDrive - PwC\Cust Proposals\Proposal_Global_Payments_V3.pptx",
        extraction_note=(
            "Proposal_Global_Payments_V3.pptx was locked by another process during extraction. "
            "Visual structure, shapes, colors, and layouts were mapped from Proposal_Global_Payments_V2.pptx "
            "(same deck family). Re-run extract_pptx_template.py against V3 when the file is closed to refresh."
        ),
    )

    template_path.write_text(json.dumps(template, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path = base / "proposal_global_payments_v3.summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Updated: {template_path}")
    print(f"Summary: {summary_path}")
    print(f"Slides: {template['slide_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
