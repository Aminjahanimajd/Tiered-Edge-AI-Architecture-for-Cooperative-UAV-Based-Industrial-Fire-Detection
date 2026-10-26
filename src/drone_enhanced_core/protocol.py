"""Validated protocol objects shared by host tests and ROS 2 adapters.

The classes avoid dataclasses so the core remains compatible with Python 3.6,
which is installed on the historical Jetson Nano and VOXL 2 environments.
"""

from __future__ import print_function

import math
import re


SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _require_nonempty(name, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("{} must be a non-empty string".format(name))
    return value.strip()


def _require_finite(name, value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("{} must be finite".format(name))
    return value


def _require_unit_interval(name, value):
    value = _require_finite(name, value)
    if value < 0.0 or value > 1.0:
        raise ValueError("{} must be in [0, 1]".format(name))
    return value


class TargetBox(object):
    """Normalized box in the source camera's image coordinate frame.

    ``center_u`` increases from image left to right and ``center_v`` increases
    from image top to bottom. These values are never geographic coordinates
    and are not transferable to another camera without calibrated geometry.
    """

    __slots__ = (
        "center_u",
        "center_v",
        "width",
        "height",
        "frame_width",
        "frame_height",
    )

    def __init__(
        self,
        center_u,
        center_v,
        width,
        height,
        frame_width,
        frame_height,
    ):
        self.center_u = _require_unit_interval("center_u", center_u)
        self.center_v = _require_unit_interval("center_v", center_v)
        self.width = _require_unit_interval("width", width)
        self.height = _require_unit_interval("height", height)
        self.frame_width = int(frame_width)
        self.frame_height = int(frame_height)
        if self.width <= 0.0 or self.height <= 0.0:
            raise ValueError("box width and height must be greater than zero")
        if self.frame_width <= 0 or self.frame_height <= 0:
            raise ValueError("frame dimensions must be positive")

    def to_dict(self):
        return {
            "center_u": self.center_u,
            "center_v": self.center_v,
            "width": self.width,
            "height": self.height,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "coordinate_frame": "source_camera_normalized_image",
        }


class HazardAlert(object):
    """Correlated Sentinel alert passed to Scout for independent verification."""

    __slots__ = (
        "experiment_id",
        "trial_id",
        "event_id",
        "source_device",
        "hazard_type",
        "confidence",
        "temporal_count",
        "source_frame_monotonic_ns",
        "alert_monotonic_ns",
        "model_sha256",
        "target_box",
    )

    def __init__(
        self,
        experiment_id,
        trial_id,
        event_id,
        source_device,
        hazard_type,
        confidence,
        temporal_count,
        source_frame_monotonic_ns,
        alert_monotonic_ns,
        model_sha256,
        target_box,
    ):
        self.experiment_id = _require_nonempty("experiment_id", experiment_id)
        self.trial_id = _require_nonempty("trial_id", trial_id)
        self.event_id = _require_nonempty("event_id", event_id)
        self.source_device = _require_nonempty("source_device", source_device)
        self.hazard_type = _require_nonempty("hazard_type", hazard_type).lower()
        self.confidence = _require_unit_interval("confidence", confidence)
        self.temporal_count = int(temporal_count)
        self.source_frame_monotonic_ns = int(source_frame_monotonic_ns)
        self.alert_monotonic_ns = int(alert_monotonic_ns)
        self.model_sha256 = _require_nonempty("model_sha256", model_sha256)
        self.target_box = target_box

        if self.temporal_count <= 0:
            raise ValueError("temporal_count must be positive")
        if self.source_frame_monotonic_ns < 0 or self.alert_monotonic_ns < 0:
            raise ValueError("monotonic timestamps must be non-negative")
        if self.alert_monotonic_ns < self.source_frame_monotonic_ns:
            raise ValueError("alert time cannot precede the source frame")
        if not SHA256_RE.match(self.model_sha256):
            raise ValueError("model_sha256 must contain 64 hexadecimal characters")
        if not isinstance(self.target_box, TargetBox):
            raise TypeError("target_box must be a TargetBox")

    def to_dict(self):
        return {
            "experiment_id": self.experiment_id,
            "trial_id": self.trial_id,
            "event_id": self.event_id,
            "source_device": self.source_device,
            "hazard_type": self.hazard_type,
            "confidence": self.confidence,
            "temporal_count": self.temporal_count,
            "source_frame_monotonic_ns": self.source_frame_monotonic_ns,
            "alert_monotonic_ns": self.alert_monotonic_ns,
            "model_sha256": self.model_sha256.lower(),
            "target_box": self.target_box.to_dict(),
        }
