"""Tests for multi-format ingestion."""

from pathlib import Path

import pytest

from app.services.ingestion import ingest_file
from app.services.diagram import render_mermaid_swimlane
from app.services.extraction import heuristic_extract, _build_diagram_from_activities


def test_ingest_markdown(tmp_path):
    f = tmp_path / "sop.md"
    f.write_text("1. Receive order\n2. Approve credit\n3. Post invoice", encoding="utf-8")
    result = ingest_file(f, "sop.md")
    assert "Receive order" in result.text
    assert result.source_type == "text"


def test_heuristic_builds_diagram():
    result = heuristic_extract("1. Step one\n2. Step two", filename="test.txt")
    assert result.diagram
    assert result.diagram.get("lanes")
    mermaid = render_mermaid_swimlane(result.diagram)
    assert "flowchart" in mermaid


def test_vsdx_zip_extract(tmp_path):
    import zipfile

    vsdx = tmp_path / "mini.vsdx"
    with zipfile.ZipFile(vsdx, "w") as zf:
        zf.writestr(
            "visio/pages/page1.xml",
            '<?xml version="1.0"?><Page><Text>Start Process</Text><Text>End Process</Text></Page>',
        )
    result = ingest_file(vsdx, "mini.vsdx")
    assert "Start Process" in result.text
    assert result.source_type == "visio"
