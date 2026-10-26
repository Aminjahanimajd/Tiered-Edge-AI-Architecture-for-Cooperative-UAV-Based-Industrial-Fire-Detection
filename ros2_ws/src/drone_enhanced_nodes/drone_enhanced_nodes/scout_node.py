"""Scout independent fire-verification node with a bounded worker queue."""

from __future__ import print_function

import os
import queue
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image

from drone_enhanced_core import (
    AsyncJsonlLogger,
    HazardAlert,
    LatestFrameBuffer,
    TargetBox,
    decode_yolov8,
)
from drone_enhanced_interfaces.msg import HazardAlert as HazardAlertMsg
from drone_enhanced_interfaces.msg import HazardVerdict as HazardVerdictMsg

from .backends import TFLiteBackend
from .runtime_support import (
    create_session_directory,
    decode_ros_image_to_bgr,
    file_sha256,
    monotonic_ns,
    prepare_bgr_frame,
    resolve_session_ids,
    write_session_manifest,
)


class ScoutEnhanced(Node):
    _STOP = object()

    def __init__(self):
        super().__init__("scout_enhanced")
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

        self.model_path = str(self.get_parameter("model_path").value)
        self.model_sha256 = file_sha256(self.model_path)
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
        self.output_coordinate_space = str(
            self.get_parameter("output_coordinate_space").value
        ).strip().lower()
        if self.output_coordinate_space not in ("model_pixels", "normalized"):
            raise ValueError(
                "output_coordinate_space must be model_pixels or normalized"
            )
        self.yuv420_format = str(self.get_parameter("yuv420_format").value).lower()
        if self.yuv420_format not in ("nv12", "nv21"):
            raise ValueError("yuv420_format must be nv12 or nv21")
        self.max_frame_age_ns = (
            int(self.get_parameter("max_frame_age_ms").value) * 1000000
        )
        self.diagnostic_capture_directory = str(
            self.get_parameter("diagnostic_capture_directory").value
        ).strip()
        self.backend = TFLiteBackend(
            self.model_path, int(self.get_parameter("interpreter_threads").value)
        )
        self.frame_buffer = LatestFrameBuffer()
        self._work_queue = queue.Queue(maxsize=1)
        self._seen_event_ids = set()
        self._verdict_event_ids = set()
        self._seen_lock = threading.Lock()

        log_directory = str(self.get_parameter("log_directory").value)
        session_directory, self.node_run_id = create_session_directory(
            log_directory,
            self.experiment_id,
            self.trial_id,
            "scout",
            self.formal_mode,
        )
        write_session_manifest(
            os.path.join(session_directory, "session_manifest.json"),
            self._manifest_values(),
        )
        self.event_logger = AsyncJsonlLogger(
            os.path.join(session_directory, "events.jsonl"), flush_every=10
        )

        self.verdict_publisher = self.create_publisher(
            HazardVerdictMsg, "/swarm/hazard_verdict", 10
        )
        self.alert_subscription = self.create_subscription(
            HazardAlertMsg, "/swarm/hazard_alert", self._alert_callback, 10
        )
        camera_topic = str(self.get_parameter("camera_topic").value)
        self.camera_subscription = self.create_subscription(
            Image, camera_topic, self._camera_callback, qos_profile_sensor_data
        )
        self._worker = threading.Thread(
            target=self._verification_worker, name="scout-verification-worker"
        )
        self._worker.daemon = True
        self._worker.start()
        self.get_logger().info(
            "Scout ready: experiment={} trial={} model={} fire-only, flight disabled".format(
                self.experiment_id, self.trial_id, self.model_sha256[:12]
            )
        )

    def _declare_parameters(self):
        values = {
            "formal_mode": False,
            "experiment_id": "",
            "trial_id": "",
            "camera_topic": "/hires_small_color",
            "yuv420_format": "nv21",
            "model_path": "/home/root/colcon_ws/best.tflite",
            "log_directory": "/home/root/colcon_ws/enhanced_logs",
            "class_names": ["fire", "smoke", "non_fire"],
            "live_hazard_classes": ["fire"],
            "confidence_threshold": 0.50,
            "nms_iou_threshold": 0.45,
            "resize_mode": "letterbox",
            "output_coordinate_space": "normalized",
            "interpreter_threads": 4,
            "max_frame_age_ms": 500,
            "diagnostic_capture_directory": "",
            "enable_flight_commands": False,
        }
        for name, value in values.items():
            self.declare_parameter(name, value)

    def _manifest_values(self):
        return {
            "schema_version": 1,
            "node": "scout",
            "experiment_id": self.experiment_id,
            "trial_id": self.trial_id,
            "formal_mode": self.formal_mode,
            "node_run_id": self.node_run_id,
            "model_path": self.model_path,
            "model_sha256": self.model_sha256,
            "input_shape": [
                int(value) for value in self.backend.input_metadata["shape"]
            ],
            "input_dtype": str(self.backend.input_metadata["dtype"]),
            "output_shape": [
                int(value) for value in self.backend.output_metadata["shape"]
            ],
            "output_dtype": str(self.backend.output_metadata["dtype"]),
            "class_names": list(self.class_names),
            "live_hazard_classes": list(self.live_classes),
            "confidence_threshold": self.confidence_threshold,
            "nms_iou_threshold": self.nms_iou_threshold,
            "resize_mode": self.resize_mode,
            "output_coordinate_space": self.output_coordinate_space,
            "yuv420_format": self.yuv420_format,
            "max_frame_age_ns": self.max_frame_age_ns,
            "diagnostic_capture_directory": self.diagnostic_capture_directory,
            "interpreter_threads": int(
                self.get_parameter("interpreter_threads").value
            ),
            "flight_commands_enabled": False,
            "sentinel_coordinates_used_for_scout_inference": False,
            "test_scope": "stationary_ground_fire_only",
        }

    def _record(self, event_type, now_ns, **values):
        record = {
            "schema_version": 1,
            "event_type": event_type,
            "device": "scout",
            "experiment_id": self.experiment_id,
            "trial_id": self.trial_id,
            "monotonic_ns": int(now_ns),
            "wall_time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        record.update(values)
        self.event_logger.log(record)

    def _camera_callback(self, message):
        received_ns = monotonic_ns()
        try:
            frame, decode_metadata = decode_ros_image_to_bgr(
                message, self.yuv420_format
            )
            sequence = self.frame_buffer.update(frame, received_ns)
            if sequence == 1:
                self._record(
                    "first_camera_frame",
                    received_ns,
                    **decode_metadata
                )
        except Exception as exc:
            self._record("camera_decode_error", received_ns, reason=str(exc))
            self.get_logger().error("Scout camera decode failed: {}".format(exc))

    def _alert_callback(self, message):
        received_ns = monotonic_ns()
        try:
            alert = HazardAlert(
                message.experiment_id,
                message.trial_id,
                message.event_id,
                message.source_device,
                message.hazard_type,
                message.confidence,
                message.temporal_count,
                message.source_frame_monotonic_ns,
                message.alert_monotonic_ns,
                message.model_sha256,
                TargetBox(
                    message.target_u,
                    message.target_v,
                    message.bbox_width,
                    message.bbox_height,
                    message.frame_width,
                    message.frame_height,
                ),
            )
        except Exception as exc:
            self._record(
                "invalid_alert", received_ns, event_id=message.event_id, reason=str(exc)
            )
            return
        if (
            alert.experiment_id != self.experiment_id
            or alert.trial_id != self.trial_id
        ):
            self._record(
                "alert_ignored",
                received_ns,
                event_id=alert.event_id,
                reason="experiment_or_trial_mismatch",
            )
            return
        with self._seen_lock:
            if alert.event_id in self._seen_event_ids:
                self._record(
                    "alert_ignored",
                    received_ns,
                    event_id=alert.event_id,
                    reason="duplicate_event_id",
                )
                return
            self._seen_event_ids.add(alert.event_id)
        work = (alert, received_ns)
        try:
            self._work_queue.put_nowait(work)
            self._record(
                "hazard_alert_received",
                received_ns,
                event_id=alert.event_id,
                sentinel_confidence=alert.confidence,
                sentinel_target_box=alert.target_box.to_dict(),
                target_coordinates_used_for_inference=False,
            )
        except queue.Full:
            self._publish_verdict(
                alert,
                received_ns,
                received_ns,
                "ERROR",
                0.0,
                0,
                "verification_worker_busy",
            )

    def _verification_worker(self):
        while True:
            work = self._work_queue.get()
            alert = None
            alert_received_ns = None
            try:
                if work is self._STOP:
                    return
                alert, alert_received_ns = work
                self._verify(alert, alert_received_ns)
            except Exception as exc:
                self.get_logger().error("Scout verification worker failed: {}".format(exc))
                if alert is not None:
                    now_ns = monotonic_ns()
                    self._publish_verdict(
                        alert,
                        alert_received_ns,
                        now_ns,
                        "ERROR",
                        0.0,
                        0,
                        "unexpected_worker_error: {}".format(exc),
                    )
            finally:
                self._work_queue.task_done()

    def _verify(self, alert, alert_received_ns):
        started_ns = monotonic_ns()
        snapshot, frame_status = self.frame_buffer.snapshot(
            started_ns, self.max_frame_age_ns
        )
        if snapshot is None:
            self._publish_verdict(
                alert,
                alert_received_ns,
                started_ns,
                "ERROR",
                0.0,
                0,
                frame_status.lower(),
            )
            return
        try:
            diagnostic_frame_path = ""
            diagnostic_frame_sha256 = ""
            if self.diagnostic_capture_directory:
                import cv2

                if not os.path.isdir(self.diagnostic_capture_directory):
                    os.makedirs(self.diagnostic_capture_directory)
                diagnostic_frame_path = os.path.join(
                    self.diagnostic_capture_directory,
                    "{}_{}.jpg".format(self.trial_id, alert.event_id),
                )
                if not cv2.imwrite(diagnostic_frame_path, snapshot.frame):
                    raise RuntimeError("diagnostic frame write failed")
                diagnostic_frame_sha256 = file_sha256(diagnostic_frame_path)
            tensor, transform = prepare_bgr_frame(
                snapshot.frame,
                self.backend.model_width,
                self.backend.model_height,
                self.resize_mode,
                self.backend.layout,
            )
            inference_start_ns = monotonic_ns()
            output = self.backend.infer(tensor)
            inference_end_ns = monotonic_ns()
            import numpy as np

            matrix = np.asarray(output)
            if matrix.ndim == 3 and matrix.shape[0] == 1:
                matrix = matrix[0]
            expected_channels = 4 + len(self.class_names)
            fire_channel = 4 + self.class_names.index("fire")
            if matrix.shape[0] == expected_channels:
                raw_fire_max = float(np.nanmax(matrix[fire_channel, :]))
            elif matrix.shape[1] == expected_channels:
                raw_fire_max = float(np.nanmax(matrix[:, fire_channel]))
            else:
                raise ValueError("unexpected output shape for raw fire score")
            detections = decode_yolov8(
                output,
                self.class_names,
                transform,
                self.confidence_threshold,
                self.nms_iou_threshold,
                self.live_classes,
                self.output_coordinate_space,
            )
        except Exception as exc:
            self._publish_verdict(
                alert,
                alert_received_ns,
                started_ns,
                "ERROR",
                0.0,
                snapshot.monotonic_ns,
                "inference_error: {}".format(exc),
            )
            return
        best = detections[0] if detections else None
        verdict = "CONFIRMED" if best is not None else "REJECTED"
        confidence = 0.0 if best is None else best.confidence
        reason = (
            "independent_scout_fire_detection"
            if best is not None
            else "no_scout_fire_detection_above_threshold"
        )
        self._record(
            "verification_inference",
            inference_end_ns,
            event_id=alert.event_id,
            source_frame_monotonic_ns=snapshot.monotonic_ns,
            frame_sequence=snapshot.sequence,
            frame_age_at_start_ms=(started_ns - snapshot.monotonic_ns) / 1000000.0,
            queue_delay_ms=(started_ns - alert_received_ns) / 1000000.0,
            inference_latency_ms=(inference_end_ns - inference_start_ns) / 1000000.0,
            fire_confidence=confidence,
            raw_fire_max=raw_fire_max,
            detection_count=len(detections),
            diagnostic_frame_path=diagnostic_frame_path,
            diagnostic_frame_sha256=diagnostic_frame_sha256,
            target_coordinates_used_for_inference=False,
            logger_dropped_records=self.event_logger.dropped_records,
        )
        self._publish_verdict(
            alert,
            alert_received_ns,
            inference_end_ns,
            verdict,
            confidence,
            snapshot.monotonic_ns,
            reason,
        )

    def _publish_verdict(
        self,
        alert,
        alert_received_ns,
        verdict_ns,
        verdict,
        confidence,
        source_frame_ns,
        reason,
    ):
        with self._seen_lock:
            if alert.event_id in self._verdict_event_ids:
                self._record(
                    "verdict_suppressed",
                    verdict_ns,
                    event_id=alert.event_id,
                    reason="verdict_already_published",
                )
                return
            self._verdict_event_ids.add(alert.event_id)
        message = HazardVerdictMsg()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = "scout_camera"
        message.experiment_id = alert.experiment_id
        message.trial_id = alert.trial_id
        message.event_id = alert.event_id
        message.source_device = "scout"
        message.verdict = verdict
        message.hazard_type = alert.hazard_type
        message.confidence = float(confidence)
        message.alert_received_monotonic_ns = int(alert_received_ns)
        message.source_frame_monotonic_ns = int(source_frame_ns)
        message.verdict_monotonic_ns = int(verdict_ns)
        message.model_sha256 = self.model_sha256
        message.reason = str(reason)
        self.verdict_publisher.publish(message)
        self._record(
            "hazard_verdict_published",
            verdict_ns,
            event_id=alert.event_id,
            verdict=verdict,
            scout_confidence=float(confidence),
            alert_received_monotonic_ns=alert_received_ns,
            source_frame_monotonic_ns=source_frame_ns,
            reason=reason,
        )
        self.get_logger().warning(
            "Event {} verified as {} (fire confidence {:.3f})".format(
                alert.event_id, verdict, confidence
            )
        )

    def close(self):
        if hasattr(self, "_worker") and self._worker.is_alive():
            self._work_queue.put(self._STOP)
            self._worker.join(10.0)
            if self._worker.is_alive():
                raise RuntimeError("Scout verification worker did not stop")
        if hasattr(self, "event_logger"):
            self.event_logger.close()


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = ScoutEnhanced()
        rclpy.spin(node)
    except KeyboardInterrupt:
        # Bounded laboratory runs are stopped with SIGINT. Preserve unexpected
        # exceptions, but treat the intentional stop as a clean shutdown.
        pass
    finally:
        if node is not None:
            node.close()
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
