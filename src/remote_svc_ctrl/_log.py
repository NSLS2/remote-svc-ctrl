"""Logging utilities for remote-svc-ctrl."""

import logging
import sys

logger = logging.getLogger("remote-svc-ctrl")

# Define color codes as constants for readability
RED = "\033[31m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
BLUE = "\033[34m"
CYAN = "\033[36m"
WHITE_ON_RED = "\033[41;97m"
BRIGHT_RED = "\033[31;1m"
BRIGHT_YELLOW = "\033[33;1m"
RESET = "\033[0m"  # Resets the color to default


class ColorFormatter(logging.Formatter):
    """ANSI color formatter for warnings and errors."""

    COLOR_MAP = {
        logging.DEBUG: CYAN,
        logging.INFO: GREEN,
        logging.WARNING: BRIGHT_YELLOW,
        logging.ERROR: BRIGHT_RED,
        logging.CRITICAL: WHITE_ON_RED,
    }

    def __init__(self, fmt: str, use_color: bool = True):
        super().__init__(fmt)
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        if self.use_color and record.levelno in self.COLOR_MAP:
            # Temporarily modify the levelname with color codes
            original_levelname = record.levelname
            # Pad to 8 characters (length of "CRITICAL") for consistent alignment
            padded_levelname = original_levelname.ljust(8)
            record.levelname = (
                f"{self.COLOR_MAP[record.levelno]}{padded_levelname}{RESET}"
            )
            base = super().format(record)
            # Restore the original levelname
            record.levelname = original_levelname
            return base
        # For non-colored output, still pad for consistency
        original_levelname = record.levelname
        record.levelname = original_levelname.ljust(8)
        base = super().format(record)
        record.levelname = original_levelname
        return base


handler = logging.StreamHandler()
use_color = sys.stderr.isatty()
fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
handler.setFormatter(ColorFormatter(fmt, use_color=use_color))
logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False


def set_log_level(level: str | int) -> None:
    """Set the log level for the logger.

    Parameters
    ----------
    level : str or int
        The log level to set. Can be a string (e.g., "DEBUG", "INFO") or an integer.
    """
    if isinstance(level, str):
        level = level.upper()
        if level not in logging._nameToLevel:  # noqa: SLF001
            raise ValueError(f"Invalid log level: {level}")
        level = logging._nameToLevel[level]  # noqa: SLF001
    logger.setLevel(level)
