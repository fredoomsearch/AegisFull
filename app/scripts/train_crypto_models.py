from __future__ import annotations

"""
Thin wrapper to the canonical trainer (train_models.py).

Kept for backward compatibility. Prefer calling train_models.py directly.
"""

import json
import os
def main() -> None:
    # Delegate to the main trainer.
    from app.scripts.train_models import main as train_main

    print("[train_crypto_models] Delegating to train_models.py ...")
    train_main()


if __name__ == "__main__":
    main()
