import sys

from loguru import logger


def _unicode_sink(message) -> None:
    text = str(message)
    sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
    sys.stdout.buffer.flush()


# Global logger rule: use loguru across the project.
logger.remove()
logger.add(
    sink=_unicode_sink,
    level="INFO",
    backtrace=False,
    diagnose=False,
)


def set_log_level(level: str) -> None:
    logger.remove()
    logger.add(
        sink=_unicode_sink,
        level=level.upper(),
        backtrace=False,
        diagnose=False,
    )
