"""Modal entrypoint for the FastAPI backend.

Usage:
  1. Install Modal locally: `uv pip install modal`
  2. Create a Modal secret named `da-agent-demo-env`
  3. Deploy: `modal deploy deploy/modal_app.py`
"""

from __future__ import annotations

from pathlib import Path

import modal

PROJECT_ROOT = Path(__file__).resolve().parents[1]

image = (
    modal.Image.from_dockerfile(
        str(PROJECT_ROOT / "docker" / "backend.Dockerfile"),
        context_dir=str(PROJECT_ROOT),
    )
    .env({
        "PATH": "/app/.venv/bin:/usr/local/bin:/usr/bin:/bin",
        "PYTHONPATH": "/app",
    })
)

app = modal.App("da-agent-demo")


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("da-agent-demo-env")],
)
@modal.asgi_app(label="da-agent-api")
def fastapi_app():
    from backend.main import app as fastapi_app_instance

    return fastapi_app_instance
