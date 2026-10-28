"""Engine-neutral logging facade.

Stdlib ``logging`` adapters with the same signatures as the engine's log
functions, so domains and Semente-level code never import the engine. The agno
backend configures its own loggers; everything else logs through here.
"""

from __future__ import annotations

import logging

_logger = logging.getLogger("semente")


def log_debug(msg, center: bool = False, symbol: str = "*", log_level: int = 1, *args, exc_info: bool = False, **kwargs):
    _logger.debug(msg, exc_info=exc_info)


def log_info(msg, center: bool = False, symbol: str = "*", *args, exc_info: bool = False, **kwargs):
    _logger.info(msg, exc_info=exc_info)


def log_warning(msg, *args, exc_info: bool = False, **kwargs):
    _logger.warning(msg, exc_info=exc_info)


def log_error(msg, *args, exc_info: bool = False, **kwargs):
    # exc_info=True inside an except block keeps the traceback in the log
    _logger.error(msg, exc_info=exc_info)


__all__ = ["log_debug", "log_info", "log_warning", "log_error"]
