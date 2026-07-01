from __future__ import annotations

"""Crypto ML model metadata package."""

from .models import ModelCatalog, TrainedModel, discover_trained_models

__all__ = ["ModelCatalog", "TrainedModel", "discover_trained_models"]
