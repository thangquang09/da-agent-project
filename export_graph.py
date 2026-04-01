"""Export LangGraph graph(s) as Mermaid (.mmd) and image (.png).

Usage:
    .venv/bin/python export_graph.py              # exports all graphs to docs/thangquang09/
    .venv/bin/python export_graph.py --version v1 # export only v1
    .venv/bin/python export_graph.py --version v2 # export only v2
    .venv/bin/python export_graph.py --output ./  # custom output dir
"""

from __future__ import annotations

import argparse
import http.server
import socketserver
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.graph.graph import build_sql_v1_graph, build_sql_v2_graph

_MERMAID_HTML = """\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <script>
    mermaid.initialize({{ startOnLoad: true, theme: 'default', securityLevel: 'loose' }});
  </script>
  <style>
    body {{ margin: 0; padding: 40px; background: #fff; }}
    .mermaid {{ display: flex; justify-content: center; }}
  </style>
</head>
<body>
  <div class="mermaid">
{diagram}
  </div>
</body>
</html>
"""

GRAPHS = {
    "v1": ("langgraph_graph_v1", build_sql_v1_graph),
    "v2": ("langgraph_graph_v2", build_sql_v2_graph),
}


def _render_mermaid_png(mermaid_text: str, png_path: Path) -> None:
    """Render a mermaid diagram to PNG using Playwright + local HTTP server."""
    html = _MERMAID_HTML.format(diagram=mermaid_text)
    html_path = png_path.parent / "_render.html"
    html_path.write_text(html)

    handler = http.server.SimpleHTTPRequestHandler
    port = 8765
    with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1920, "height": 1080})

            url = f"http://127.0.0.1:{port}/{html_path}"
            print(f"[info] Loading: {url}")
            page.goto(url, wait_until="networkidle", timeout=60_000)

            page.wait_for_selector("div.mermaid svg", timeout=30_000)
            page.wait_for_timeout(2000)

            svg_outer = page.eval_on_selector("div.mermaid svg", "el => el.outerHTML")
            print(f"[info] SVG length: {len(svg_outer)} chars")

            if len(svg_outer) < 100:
                print("[warn] SVG seems empty, waiting more...")
                page.wait_for_timeout(5000)

            page.screenshot(path=str(png_path), full_page=True)
            browser.close()

        httpd.shutdown()

    html_path.unlink(missing_ok=True)


def export_graph(name: str, prefix: str, build_fn, output_dir: Path) -> None:
    """Build a single graph and export .mmd + .png files."""
    graph = build_fn()
    mermaid_text = graph.get_graph().draw_mermaid()

    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Save Mermaid source
    mmd_path = output_dir / f"{prefix}.mmd"
    mmd_path.write_text(mermaid_text)
    print(f"[ok] Mermaid source: {mmd_path}")

    # 2. Render PNG
    png_path = output_dir / f"{prefix}.png"
    _render_mermaid_png(mermaid_text, png_path)

    png_size = png_path.stat().st_size
    print(f"[ok] PNG image: {png_path} ({png_size:,} bytes)")

    if png_size < 5000:
        print("[warn] PNG is very small, diagram may not have rendered correctly")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export LangGraph graph diagram(s)")
    parser.add_argument(
        "--version",
        choices=["v1", "v2", "all"],
        default="all",
        help="Which graph version to export (default: all)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/thangquang09"),
        help="Output directory (default: docs/thangquang09)",
    )
    args = parser.parse_args()

    versions = ["v1", "v2"] if args.version == "all" else [args.version]
    for v in versions:
        prefix, build_fn = GRAPHS[v]
        print(f"\n--- Exporting {v.upper()} ---")
        export_graph(v, prefix, build_fn, args.output)


if __name__ == "__main__":
    main()
