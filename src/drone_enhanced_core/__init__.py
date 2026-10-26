"""ROS-independent core logic for the enhanced Sentinel–Scout system."""

from .event_log import AsyncJsonlLogger
from .frame_buffer import FrameSnapshot, LatestFrameBuffer
from .ground_truth import GroundTruthRecorder
from .inference import (
    Detection,
    ResizeTransform,
    compute_resize_transform,
    decode_yolov8,
    non_max_suppression,
)
from .protocol import HazardAlert, TargetBox
from .simulation import make_simulated_alert, replay_coordination
from .state_machine import (
    CoordinatorState,
    FinalDecision,
    SentinelCoordinator,
    TemporalFilter,
    TransitionResult,
)

__all__ = [
    "AsyncJsonlLogger",
    "CoordinatorState",
    "FinalDecision",
    "FrameSnapshot",
    "GroundTruthRecorder",
    "HazardAlert",
    "LatestFrameBuffer",
    "Detection",
    "ResizeTransform",
    "SentinelCoordinator",
    "TargetBox",
    "TemporalFilter",
    "TransitionResult",
    "compute_resize_transform",
    "decode_yolov8",
    "non_max_suppression",
    "make_simulated_alert",
    "replay_coordination",
]
