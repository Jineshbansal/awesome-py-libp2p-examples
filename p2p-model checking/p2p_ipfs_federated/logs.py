"""Logging setup – identical to the original project's logs.py."""

import logging
from rich.logging import RichHandler


def setup_logging(log_topic: str):
    root = logging.getLogger()
    root.handlers.clear()

    logging.basicConfig(
        level="DEBUG",
        format="%(message)s",
        handlers=[
            RichHandler(
                rich_tracebacks=True,
                show_time=False,
                show_path=True,
            )
        ],
    )

    logging.getLogger().setLevel(logging.CRITICAL)

    logger = logging.getLogger(log_topic)
    logger.setLevel(logging.DEBUG)
    return logger
