from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks

from app.logger import logger
from backend.models.responses import EvalRunResponse

router = APIRouter(prefix="/evals", tags=["evals"])


def _run_eval_suite() -> None:
    """Run evals/runner.py in a background thread."""
    import subprocess
    import sys

    logger.info("backend.evals background eval run started")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "evals.runner"],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode == 0:
            logger.info("backend.evals run completed successfully")
        else:
            logger.error(
                "backend.evals run failed rc={rc} stderr={err}",
                rc=result.returncode,
                err=result.stderr[-500:] if result.stderr else "",
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("backend.evals run exception: {error}", error=str(exc))


@router.post("/run", response_model=EvalRunResponse)
async def run_evals(background_tasks: BackgroundTasks) -> EvalRunResponse:
    """
    Trigger the eval suite in the background.

    Returns immediately with 200; eval runs asynchronously.
    Results will be written to evals/reports/.
    """
    background_tasks.add_task(_run_eval_suite)
    logger.info("backend.evals triggered via API")
    return EvalRunResponse(message="Eval suite started in background", status="started")
