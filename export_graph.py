"""Export LangGraph graph as Mermaid (.mmd) and image (.png).

Usage:
    .venv/bin/python export_graph.py              # saves to docs/thangquang09/
    .venv/bin/python export_graph.py --output ./  # custom output dir
"""

from __future__ import annotations

import argparse
import http.server
import socketserver
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.graph.graph import build_sql_v1_graph

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


def export_graph(output_dir: Path) -> None:
    """Build the graph, export .mmd and .png files."""
    graph = build_sql_v1_graph()
    mermaid_text = graph.get_graph().draw_mermaid()

    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Save Mermaid source
    mmd_path = output_dir / "langgraph_graph.mmd"
    mmd_path.write_text(mermaid_text)
    print(f"[ok] Mermaid source: {mmd_path}")

    # 2. Render PNG via Playwright + local HTTP server
    html = _MERMAID_HTML.format(diagram=mermaid_text)
    html_path = output_dir / "_render.html"
    html_path.write_text(html)

    png_path = output_dir / "langgraph_graph.png"

    # Start local HTTP server to avoid file:// CORS issues with CDN
    handler = http.server.SimpleHTTPRequestHandler
    port = 8765
    with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1920, "height": 1080})

            # Serve via HTTP to allow external scripts
            url = f"http://127.0.0.1:{port}/{html_path}"
            print(f"[info] Loading: {url}")
            page.goto(url, wait_until="networkidle", timeout=60_000)

            # Wait for SVG to appear
            page.wait_for_selector("div.mermaid svg", timeout=30_000)
            page.wait_for_timeout(2000)

            # Debug: check SVG content
            svg_outer = page.eval_on_selector("div.mermaid svg", "el => el.outerHTML")
            print(f"[info] SVG length: {len(svg_outer)} chars")

            if len(svg_outer) < 100:
                print("[warn] SVG seems empty, waiting more...")
                page.wait_for_timeout(5000)

            # Take screenshot
            page.screenshot(path=str(png_path), full_page=True)
            browser.close()

        httpd.shutdown()

    html_path.unlink(missing_ok=True)

    # Verify output
    png_size = png_path.stat().st_size
    print(f"[ok] PNG image: {png_path} ({png_size:,} bytes)")

    if png_size < 5000:
        print("[warn] PNG is very small, diagram may not have rendered correctly")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export LangGraph graph diagram")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/thangquang09"),
        help="Output directory (default: docs/thangquang09)",
    )
    args = parser.parse_args()
    export_graph(args.output)


if __name__ == "__main__":
    main()
