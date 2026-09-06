"""Tests for Graph Engine and Media Analysis."""

import pytest
from graph_engine import GraphEngine
from media_analyzer import MediaAnalyzer


def test_graph_creation_mermaid_and_ascii():
    """Test generating Mermaid flowchart and ASCII diagram."""
    nodes = [
        {"id": "A", "label": "Start"},
        {"id": "B", "label": "Process"},
        {"id": "C", "label": "End"},
    ]
    edges = [
        {"from": "A", "to": "B", "label": "Begin"},
        {"from": "B", "to": "C", "label": "Done"},
    ]
    res = GraphEngine.create_graph(nodes, edges, graph_type="flowchart")
    assert res["node_count"] == 3
    assert res["edge_count"] == 2
    assert "flowchart TD" in res["mermaid"]
    assert 'A["Start"]' in res["mermaid"]
    assert 'A -->|"Begin"| B' in res["mermaid"]
    assert "[Start]" in res["ascii"]


def test_graph_reading_mermaid_and_nl():
    """Test reading graph nodes and edges from mermaid text and NL."""
    text = """
    A["NodeA"] -->|"Link"| B["NodeB"]
    SystemA connects to SystemB
    """
    res = GraphEngine.read_graph(text)
    assert res["node_count"] >= 2
    assert res["edge_count"] >= 1


def test_media_analyzer_picture(tmp_path):
    """Test reading picture metadata and encoding."""
    # Write a dummy PNG header with 100x50 dimensions
    # PNG signature + IHDR chunk
    png_data = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x64"  # width 100
        b"\x00\x00\x00\x32"  # height 50
        b"\x08\x02\x00\x00\x00"
    )
    img_file = tmp_path / "test.png"
    img_file.write_bytes(png_data)

    res = MediaAnalyzer.analyze_picture(img_file)
    assert res["success"] is True
    assert res["format"] == "PNG"
    assert res["width"] == 100
    assert res["height"] == 50
    assert res["aspect_ratio"] == "2.0:1"

    b64 = MediaAnalyzer.encode_image_base64(img_file)
    assert b64 is not None
    assert len(b64) > 0


def test_media_analyzer_video(tmp_path):
    """Test video analysis strategy generation."""
    vid_file = tmp_path / "test.mp4"
    vid_file.write_bytes(b"\x00" * 1000)

    res = MediaAnalyzer.analyze_video(vid_file)
    assert res["success"] is True
    assert res["format"] == "MP4"
    assert "analysis_strategy" in res
    assert res["analysis_strategy"]["sampling_rate_fps"] == 1
