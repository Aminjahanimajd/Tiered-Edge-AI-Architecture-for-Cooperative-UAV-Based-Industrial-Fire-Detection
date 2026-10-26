#!/usr/bin/env python3
"""Exercise the deployed Sentinel timeout path while no Scout node exists."""

from __future__ import print_function

import argparse
import json
import time


def monotonic_ns():
    function = getattr(time, "monotonic_ns", None)
    return function() if function is not None else int(time.monotonic() * 1000000000)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--output", required=True)
    arguments, ros_arguments = parser.parse_known_args()
    if arguments.count < 1 or arguments.count > 20:
        parser.error("--count must be in [1, 20]")

    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from drone_enhanced_core import Detection
    from drone_enhanced_interfaces.msg import HazardAlert, HazardDecision, HazardVerdict
    from drone_enhanced_nodes.sentinel_node import SentinelEnhanced

    rclpy.init(args=ros_arguments)
    sentinel = SentinelEnhanced()
    sentinel.inference_timer.cancel()
    observer = rclpy.create_node("sentinel_scout_unavailable_observer")
    observed_alerts = []
    observed_decisions = []
    unexpected_verdicts = []
    observer.create_subscription(HazardAlert, "/swarm/hazard_alert", observed_alerts.append, 10)
    observer.create_subscription(HazardDecision, "/swarm/hazard_decision", observed_decisions.append, 10)
    observer.create_subscription(HazardVerdict, "/swarm/hazard_verdict", unexpected_verdicts.append, 10)
    executor = SingleThreadedExecutor()
    executor.add_node(sentinel)
    executor.add_node(observer)
    samples = []
    try:
        discovery_deadline = time.monotonic() + 5.0
        while time.monotonic() < discovery_deadline:
            executor.spin_once(timeout_sec=0.05)
            if sentinel.alert_publisher.get_subscription_count() >= 1 and sentinel.decision_publisher.get_subscription_count() >= 1:
                break
        if sentinel.alert_publisher.get_subscription_count() < 1 or sentinel.decision_publisher.get_subscription_count() < 1:
            raise RuntimeError("local evidence observer was not discovered")

        detection = Detection(0, "fire", 0.75, 0.45, 0.45, 0.55, 0.55)
        timeout_ns = int(sentinel.coordinator.timeout_ns)
        for index in range(arguments.count):
            injected_ns = monotonic_ns()
            sentinel._dispatch_detection(detection, injected_ns, injected_ns, 640, 480)
            if sentinel._active_context is None:
                raise RuntimeError("synthetic detection was not dispatched")
            event_id = sentinel._active_context.event_id
            deadline = time.monotonic() + timeout_ns / 1e9 + 3.0
            while time.monotonic() < deadline:
                executor.spin_once(timeout_sec=0.05)
                matches = [message for message in observed_decisions if message.event_id == event_id]
                if matches:
                    decision = matches[0]
                    break
            else:
                raise RuntimeError("Sentinel timeout decision was not observed")
            if decision.decision != "TIMEOUT" or decision.reason != "Scout response timeout":
                raise RuntimeError("unexpected unavailable-Scout decision")
            alert_matches = [message for message in observed_alerts if message.event_id == event_id]
            if len(alert_matches) != 1:
                raise RuntimeError("expected exactly one observed Sentinel alert")
            samples.append(
                {
                    "repetition": index + 1,
                    "event_id": event_id,
                    "decision": decision.decision,
                    "reason": decision.reason,
                    "alert_sent_monotonic_ns": int(decision.alert_sent_monotonic_ns),
                    "decision_monotonic_ns": int(decision.decision_monotonic_ns),
                    "alert_to_decision_ms": (
                        int(decision.decision_monotonic_ns) - int(decision.alert_sent_monotonic_ns)
                    ) / 1000000.0,
                    "sentinel_confidence": float(decision.sentinel_confidence),
                    "scout_confidence": float(decision.scout_confidence),
                }
            )
            settle_deadline = time.monotonic() + 0.25
            while time.monotonic() < settle_deadline:
                executor.spin_once(timeout_sec=0.02)

        if unexpected_verdicts:
            raise RuntimeError("a Scout verdict was observed while the Scout process was declared unavailable")
        if len(observed_alerts) != arguments.count or len(observed_decisions) != arguments.count:
            raise RuntimeError("alert/decision counts did not match repetitions")
        result = {
            "schema_version": 1,
            "status": "PASS",
            "fault": "scout_verification_process_unavailable",
            "repetitions": arguments.count,
            "sentinel_timeout_ms_configured": timeout_ns / 1000000.0,
            "observed_alerts": len(observed_alerts),
            "observed_timeout_decisions": len(observed_decisions),
            "observed_scout_verdicts": len(unexpected_verdicts),
            "samples": samples,
            "claim_boundary": (
                "Synthetic detections were injected at the deployed Sentinel node's alert-dispatch "
                "boundary while no Scout verification process was running. This exercises the "
                "actual Sentinel ROS publication and timeout-decision path, but not camera detection, "
                "network disconnection, flight, or industrial reliability."
            ),
        }
        with open(arguments.output, "w") as output:
            json.dump(result, output, indent=2, sort_keys=True)
            output.write("\n")
        print(json.dumps(result, sort_keys=True))
    finally:
        executor.remove_node(observer)
        executor.remove_node(sentinel)
        observer.destroy_node()
        sentinel.close()
        sentinel.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
