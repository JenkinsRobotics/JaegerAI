# core/logging_utils.py
# Centralized logging configuration for the Mochi application.

import logging
import sys

# --- Advanced Log Format ---
# This format provides detailed context for each log message, including
# the module, function, and line number where the log was generated.
LOG_FORMAT = "%(asctime)s - %(levelname)-8s - %(name)-15s - [%(module)s:%(funcName)s:%(lineno)d] - %(message)s"

def setup_logger(name: str, level=logging.INFO) -> logging.Logger:
    """
    Sets up a logger with a consistent, detailed format.

    Args:
        name: The name for the logger (typically __name__).
        level: The minimum logging level to capture.

    Returns:
        A configured logging.Logger instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False  # Prevent duplicate logs in parent loggers

    # Avoid adding handlers if they already exist
    if not logger.handlers:
        # --- Handler for stdout (INFO level) ---
        # This handler will only process logs at the INFO level.
        info_handler = logging.StreamHandler(sys.stdout)
        info_handler.setLevel(logging.INFO)
        info_handler.addFilter(lambda record: record.levelno == logging.INFO)
        info_handler.setFormatter(logging.Formatter(LOG_FORMAT))

        # --- Handler for stderr (WARNING and above) ---
        # This handler will process WARNING, ERROR, and CRITICAL logs.
        err_handler = logging.StreamHandler(sys.stderr)
        err_handler.setLevel(logging.WARNING)
        err_handler.setFormatter(logging.Formatter(LOG_FORMAT))

        logger.addHandler(info_handler)
        logger.addHandler(err_handler)

    return logger
