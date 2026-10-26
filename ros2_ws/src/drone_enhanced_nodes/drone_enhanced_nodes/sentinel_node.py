"""Sentinel fire-detection node with correlated Scout verification."""

from __future__ import print_function

import os
import time
import uuid

import rclpy
from rclpy.node import Node

from drone_enhanced_core import (
    AsyncJsonlLogger,
    HazardAlert,
    SentinelCoordinator,
    TargetBox,
    TemporalFilter,
    decode_yolov8,
)
from drone_enhanced_interfaces.msg import HazardAlert as HazardAlertMsg
from drone_enhanced_interfaces.msg import HazardDecision as HazardDecisionMsg
from drone_enhanced_interfaces.msg import HazardVerdict as HazardVerdictMsg

from .backends import TensorRTBackend
from .runtime_support import (
    build_gstreamer_yuy2_pipeline,
    create_session_directory,
    file_sha256,
    monotonic_ns,
    prepare_bgr_frame,
    resolve_session_ids,
    write_session_manifest,
)


class SentinelEnhanced(Node):
    def __init__(self):
        super().__init__("sentinel_enhanced")
        self._declare_parameters()
        self.formal_mode = bool(self.get_parameter("formal_mode").value)
        self.experiment_id, self.trial_id = resolve_session_ids(
            self.formal_mode,
            self.get_parameter("experiment_id").value,
            self.get_parameter("trial_id").value,
        )
        if bool(self.get_parameter("enable_flight_commands").value):
            raise ValueError(
                "flight commands are intentionally unavailable in the stationary "
                "evaluation node"
            )

        self.engine_path = str(self.get_parameter("engine_path").value)
        self.model_sha256 = file_sha256(self.engine_path)
        self.class_names = tuple(self.get_parameter("class_names").value)
        self.live_classes = tuple(self.get_parameter("live_hazard_classes").value)
        if self.live_classes != ("fire",):
            raise ValueError("the approved live evaluation policy is fire-only")
        self.confidence_threshold = float(
            self.get_parameter("confidence_threshold").value
        )
        self.nms_iou_threshold = float(
            self.get_parameter("nms_iou_threshold").value
        )
        self.resize_mode = str(self.get_parameter("resize_mode").value)

        self.backend = TensorRTBackend(self.engine_path)
        self._open_camera()
        self.temporal_filter = TemporalFilter(
            self.confidence_threshold,
            int(self.get_parameter("temporal_consecutive_frames").value),
        )
        self.coordinator = SentinelCoordinator(
            int(self.get_parameter("scout_timeout_ms").value) * 1000000,
            int(self.get_parameter("rejection_cooldown_ms").value) * 1000000,
            float(self.get_parameter("cooldown_radius_normalized").value),
        )
        self._active_context = None
        self._frame_sequence = 0

        log_directory = str(self.get_parameter("log_directory").value)
        session_directory, self.node_run_id = create_session_directory(
            log_directory,
            self.experiment_id,
            self.trial_id,
            "sentinel",
            self.formal_mode,
        )
        write_session_manifest(
            os.path.join(session_directory, "session_manifest.json"),
            self._manifest_values(),
        )
        self.event_logger = AsyncJsonlLogger(
            os.path.join(session_directory, "events.jsonl"), flush_every=10
        )

        self.alert_publisher = self.create_publisher(
            HazardAlertMsg, "/swarm/hazard_alert", 10
        )
        self.decision_publisher = self.create_publisher(
            HazardDecisionMsg, "/swarm/hazard_decision", 10
        )
        self.verdict_subscription = self.create_subscription(
            HazardVerdictMsg,
            "/swarm/hazard_verdict",
            self._verdict_callback,
            10,
        )
        inference_period = (
            int(self.get_parameter("inference_period_ms").value) / 1000.0
        )
        self.inference_timer = self.create_timer(inference_period, self._vision_tick)
        self.timeout_timer = self.create_timer(0.05, self._timeout_tick)
        self.get_logger().info(
            "Sentinel ready: experiment={} trial={} model={} fire-only, flight disabled".format(
                self.experiment_id, self.trial_id, self.model_sha256[:12]
            )
        )

    def _declare_parameters(self):
        values = {
            "formal_mode": False,
            "experiment_id": "",
            "trial_id": "",
            "camera_backend": "gstreamer_yuy2",
            "camera_device": "/dev/video2",
            "camera_width": 640,
            "camera_height": 480,
            "camera_fps": 30,
            "engine_path": "/workspace/ros2_ws/sentinel_v1.engine",
            "log_directory": "/workspace/ros2_ws/enhanced_logs",
            "class_names": ["fire", "smoke"],
            "live_hazard_classes": ["fire"],
            "confidence_threshold": 0.15,
            "nms_iou_threshold": 0.45,
            "temporal_consecutive_frames": 3,
            "resize_mode": "letterbox",
            "scout_timeout_ms": 10000,
            "rejection_cooldown_ms": 5000,
            "cooldown_radius_normalized": 0.10,
            "inference_period_ms": 33,
            "enable_flight_commands": False,
        }
        for name, value in values.items():
            self.declare_parameter(name, value)

    def _open_camera(self):
        import cv2

        self.camera_backend = str(self.get_parameter("camera_backend").value)
        self.camera_device = str(self.get_parameter("camera_device").value)
        self.camera_width = int(self.get_parameter("camera_width").value)
        self.camera_height = int(self.get_parameter("camera_height").value)
        self.camera_fps = int(self.get_parameter("camera_fps").value)
        if self.camera_backend != "gstreamer_yuy2":
            raise ValueError("camera_backend must be gstreamer_yuy2")
        self.camera_pipeline = build_gstreamer_yuy2_pipeline(
            self.camera_device,
            self.camera_width,
            self.camera_height,
            self.camera_fps,
        )
        self.camera = cv2.VideoCapture(self.camera_pipeline, cv2.CAP_GSTREAMER)
        if not self.camera.isOpened():
            raise RuntimeError(
                "Sentinel GStreamer camera pipeline did not open for {}".format(
                    self.camera_device
                )
            )

    def _manifest_values(self):
        return {
            "schema_version": 1,
            "node": "sentinel",
            "experiment_id": self.experiment_id,
            "trial_id": self.trial_id,
            "formal_mode": self.formal_mode,
            "node_run_id": self.node_run_id,
            "model_path": self.engine_path,
            "model_sha256": self.model_sha256,
            "binding_metadata": self.backend.binding_metadata,
            "camera_backend": self.camera_backend,
            "camera_device": self.camera_device,
            "camera_width": self.camera_width,
            "camera_height": self.camera_height,
            "camera_fps": self.camera_fps,
            "camera_pipeline": self.camera_pipeline,
            "class_names": list(self.class_names),
            "live_hazard_classes": list(self.live_classes),
            "confidence_threshold": self.confidence_threshold,
            "nms_iou_threshold": self.nms_iou_threshold,
            "temporal_consecutive_frames": self.temporal_filter.required_consecutive,
            "resize_mode": self.resize_mode,
            "flight_commands_enabled": False,
            "test_scope": "stationary_ground_fire_only",
        }

    def _record(self, event_type, now_ns, **values):
        record = {
            "schema_version": 1,
            "event_type": event_type,
            "device": "sentinel",
            "experiment_id": self.experiment_id,
            "trial_id": self.trial_id,
            "monotonic_ns": int(now_ns),
            "wall_time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        record.update(values)
        self.event_logger.log(record)

    def _vision_tick(self):
        ok, frame = self.camera.read()
        source_frame_ns = monotonic_ns()
        if not ok or frame is None:
            self._record("camera_read_failed", source_frame_ns)
            return
        self._frame_sequence += 1
        start_ns = monotonic_ns()
        try:
            tensor, transform = prepare_bgr_frame(
                frame,
                self.backend.model_width,
                self.backend.model_height,
                self.resize_mode,
                self.backend.layout,
            )
            raw_output = self.backend.infer(tensor)
            detections = decode_yolov8(
                raw_output,
                self.class_names,
                transform,
                self.confidence_threshold,
                self.nms_iou_threshold,
                self.live_classes,
            )
        except Exception as exc:
            self._record("inference_error", monotonic_ns(), reason=str(exc))
            self.get_logger().error("Sentinel inference failed: {}".format(exc))
            return
        completed_ns = monotonic_ns()
        best = detections[0] if detections else None
        confidence = 0.0 if best is None else best.confidence
        awaiting_scout = self.coordinator.active_alert is not None
        triggered = False if awaiting_scout else self.temporal_filter.update(confidence)
        self._record(
            "inference",
            completed_ns,
            source_frame_monotonic_ns=source_frame_ns,
            frame_sequence=self._frame_sequence,
            inference_latency_ms=(completed_ns - start_ns) / 1000000.0,
            fire_confidence=confidence,
            detection_count=len(detections),
            temporal_count=self.temporal_filter.count,
            temporal_triggered=triggered,
            coordination_state=self.coordinator.state.value,
            logger_dropped_records=self.event_logger.dropped_records,
        )
        if awaiting_scout:
            self._record(
                "local_tracking_observation",
                completed_ns,
                active_event_id=self.coordinator.active_alert.event_id,
                target_visible=best is not None,
                fire_confidence=confidence,
                target_u=None if best is None else best.center_u,
                target_v=None if best is None else best.center_v,
                flight_command_emitted=False,
            )
            return
        if triggered and best is not None:
            self._dispatch_detection(
                best,
                source_frame_ns,
                completed_ns,
                int(frame.shape[1]),
                int(frame.shape[0]),
            )

    def _dispatch_detection(
        self, detection, source_frame_ns, detection_ns, frame_width, frame_height
    ):
        target_box = TargetBox(
            detection.center_u,
            detection.center_v,
            detection.x2 - detection.x1,
            detection.y2 - detection.y1,
            frame_width,
            frame_height,
        )
        tracking = self.coordinator.begin_tracking(target_box, detection_ns)
        self.temporal_filter.reset()
        if not tracking.accepted:
            self._record(
                "alert_suppressed",
                detection_ns,
                reason=tracking.reason,
                target_box=target_box.to_dict(),
            )
            return
        alert_ns = monotonic_ns()
        alert = HazardAlert(
            self.experiment_id,
            self.trial_id,
            uuid.uuid4().hex,
            "sentinel",
            "fire",
            detection.confidence,
            self.temporal_filter.required_consecutive,
            source_frame_ns,
            alert_ns,
            self.model_sha256,
            target_box,
        )
        dispatched = self.coordinator.dispatch_alert(alert, alert_ns)
        if not dispatched.accepted:
            self._record("alert_dispatch_rejected", alert_ns, reason=dispatched.reason)
            return
        self._active_context = alert
        message = HazardAlertMsg()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = "sentinel_camera_normalized_image"
        message.experiment_id = alert.experiment_id
        message.trial_id = alert.trial_id
        message.event_id = alert.event_id
        message.source_device = alert.source_device
        message.hazard_type = alert.hazard_type
        message.confidence = alert.confidence
        message.temporal_count = alert.temporal_count
        message.source_frame_monotonic_ns = alert.source_frame_monotonic_ns
        message.alert_monotonic_ns = alert.alert_monotonic_ns
        message.model_sha256 = alert.model_sha256
        message.target_u = target_box.center_u
        message.target_v = target_box.center_v
        message.bbox_width = target_box.width
        message.bbox_height = target_box.height
        message.frame_width = target_box.frame_width
        message.frame_height = target_box.frame_height
        self.alert_publisher.publish(message)
        self._record("hazard_alert_published", alert_ns, **alert.to_dict())
        self.get_logger().warning(
            "Fire alert {} sent to Scout at u={:.3f}, v={:.3f}".format(
                alert.event_id, target_box.center_u, target_box.center_v
            )
        )

    def _verdict_callback(self, message):
        received_ns = monotonic_ns()
        if (
            message.experiment_id != self.experiment_id
            or message.trial_id != self.trial_id
        ):
            self._record(
                "verdict_ignored",
                received_ns,
                event_id=message.event_id,
                reason="experiment_or_trial_mismatch",
            )
            return
        result = self.coordinator.handle_verdict(
            message.event_id,
            message.verdict,
            message.confidence,
            received_ns,
            message.reason,
        )
        self._record(
            "verdict_received",
            received_ns,
            event_id=message.event_id,
            verdict=message.verdict,
            scout_confidence=float(message.confidence),
            accepted=result.accepted,
            reason=result.reason,
        )
        if result.final_decision is not None:
            self._publish_final_decision(result.final_decision, received_ns)

    def _timeout_tick(self):
        if self.coordinator.active_alert is None:
            return
        now_ns = monotonic_ns()
        result = self.coordinator.check_timeout(now_ns)
        if result.final_decision is not None:
            self._publish_final_decision(result.final_decision, now_ns)

    def _publish_final_decision(self, final, verdict_received_ns):
        alert = self._active_context
        if alert is None or alert.event_id != final.event_id:
            self.get_logger().error("Final decision has no matching alert context")
            return
        message = HazardDecisionMsg()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = "sentinel_decision"
        message.experiment_id = alert.experiment_id
        message.trial_id = alert.trial_id
        message.event_id = alert.event_id
        message.decision = final.decision
        message.hazard_type = alert.hazard_type
        message.sentinel_confidence = final.sentinel_confidence
        message.scout_confidence = final.scout_confidence
        message.detection_monotonic_ns = alert.source_frame_monotonic_ns
        message.alert_sent_monotonic_ns = alert.alert_monotonic_ns
        message.verdict_received_monotonic_ns = verdict_received_ns
        message.decision_monotonic_ns = final.decision_monotonic_ns
        message.reason = final.reason
        self.decision_publisher.publish(message)
        self._record(
            "final_decision",
            final.decision_monotonic_ns,
            event_id=final.event_id,
            decision=final.decision,
            hazard_type=alert.hazard_type,
            sentinel_confidence=final.sentinel_confidence,
            scout_confidence=final.scout_confidence,
            detection_monotonic_ns=alert.source_frame_monotonic_ns,
            alert_sent_monotonic_ns=alert.alert_monotonic_ns,
            verdict_received_monotonic_ns=verdict_received_ns,
            reason=final.reason,
        )
        if final.decision == "CONFIRMED":
            self.get_logger().error(
                "ALARM: Scout confirmed fire event {}".format(final.event_id)
            )
        else:
            self.get_logger().warning(
                "Event {} ended as {}; no alarm emitted".format(
                    final.event_id, final.decision
                )
            )
        self._active_context = None
        self.coordinator.reset_after_decision()

    def close(self):
        if hasattr(self, "camera"):
            self.camera.release()
        if hasattr(self, "event_logger"):
            self.event_logger.close()


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = SentinelEnhanced()
        rclpy.spin(node)
    except KeyboardInterrupt:
        # A bounded laboratory run is normally stopped with SIGINT.  Treat that
        # operator-requested stop as a clean shutdown while still allowing all
        # unexpected exceptions to remain visible.
        pass
    finally:
        if node is not None:
            node.close()
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
