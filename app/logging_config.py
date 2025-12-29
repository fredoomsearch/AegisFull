from __future__ import annotations

import logging
import sys
from typing import Optional

from app.config import settings


def setup_logging(level: Optional[str] = None) -> None:
    lvl = (level or settings.log_level or "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, lvl, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
