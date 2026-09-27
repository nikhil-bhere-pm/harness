import logging
import sys
from pathlib import Path

# Configure logger
LOG_FILE = Path("harness.log")

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logger = logging.getLogger("harness")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler (silent logging to harness.log)
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8", mode="a")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.propagate = False

def log_event(event_type: str, details: str, level: str = "info"):
    """Structured helper to log lifecycle events."""
    msg = f"[{event_type}] {details}"
    if level == "error":
        logger.error(msg)
    elif level == "warning":
        logger.warning(msg)
    else:
        logger.info(msg)
