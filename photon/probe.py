"""Small shared helpers for device probe result serialization."""

from __future__ import annotations

from typing import Any

from .hidpp import FeatureInfo


def feature_dict(feature: FeatureInfo) -> dict[str, Any]:
    return feature.__dict__


def probe_dict(
    path: str,
    interface: dict[str, Any],
    status: str,
    error: str | None,
    root: FeatureInfo | None,
    features: tuple[FeatureInfo, ...],
) -> dict[str, Any]:
    return {
        "path": path,
        "interface": interface,
        "status": status,
        "error": error,
        "root_feature_set": feature_dict(root) if root is not None else None,
        "features": [feature_dict(feature) for feature in features],
    }
