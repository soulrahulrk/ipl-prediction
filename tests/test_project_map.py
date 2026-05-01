from __future__ import annotations

from pathlib import Path

from ipl_predictor.project_map import build_project_map, render_html


def test_project_map_contains_core_nodes():
    repo_root = Path(__file__).resolve().parents[1]
    payload = build_project_map(repo_root=repo_root)

    node_ids = {node["id"] for node in payload["nodes"]}
    edge_pairs = {(edge["source"], edge["target"], edge["relation"]) for edge in payload["edges"]}

    assert "web_app.py" in node_ids
    assert "ipl_predictor/common.py" in node_ids
    assert ("web_app.py", "templates/index.html", "renders") in edge_pairs


def test_render_html_includes_map_data():
    repo_root = Path(__file__).resolve().parents[1]
    payload = build_project_map(repo_root=repo_root)
    html = render_html(payload)

    assert "IPL Prediction Project Map" in html
    assert "const DATA =" in html
    assert "project_map.html" not in html
