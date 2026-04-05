import sys
from pathlib import Path

from loguru import logger as _loguru_logger


def _unicode_sink(message) -> None:
    text = str(message)
    sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
    sys.stdout.buffer.flush()


def _debug_file_format(record) -> str:
    run_id = record["extra"].get("run_id", "-") if record.get("extra") else "-"
    node_name = record["extra"].get("node_name", "-") if record.get("extra") else "-"
    task_id = record["extra"].get("task_id", "-") if record.get("extra") else "-"
    user_query = record["extra"].get("user_query", "-") if record.get("extra") else "-"
    time_str = record["time"].strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    level_str = record["level"].name.ljust(8)
    return f"{time_str} | {level_str} | {run_id} | {node_name} | {task_id} | {user_query[:80]} | {record['message']}\n"


# Global logger instance
logger = _loguru_logger


def ensure_debug_file_sink(log_path: str, level: str = "DEBUG") -> None:
    """Add a debug file sink. Console stays on default format (INFO).
    Debug file uses _debug_file_format with all columns.
    """
    _loguru_logger.remove()
    # Console — default format, INFO level only
    _loguru_logger.add(
        sink=_unicode_sink,
        level="INFO",
        backtrace=False,
        diagnose=False,
    )
    # Debug file — all columns, DEBUG level
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _loguru_logger.add(
        sink=str(path),
        level=level.upper(),
        format=_debug_file_format,
        rotation="50 MB",
        retention=3,
        compression="gz",
        backtrace=False,
        diagnose=False,
    )


# Global logger rule: use loguru across the project.
_loguru_logger.remove()
_loguru_logger.add(
    sink=_unicode_sink,
    level="INFO",
    backtrace=False,
    diagnose=False,
)


def set_log_level(level: str) -> None:
    _loguru_logger.remove()
    _loguru_logger.add(
        sink=_unicode_sink,
        level=level.upper(),
        backtrace=False,
        diagnose=False,
    )
