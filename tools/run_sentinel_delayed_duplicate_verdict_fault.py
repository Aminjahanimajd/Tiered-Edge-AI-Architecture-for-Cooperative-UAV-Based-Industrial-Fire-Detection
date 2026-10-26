#!/usr/bin/env python3
"""Inject late and duplicate Scout verdicts after Sentinel timeout finalization."""

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
    injector = rclpy.create_node("delayed_duplicate_verdict_injector")
    alerts = []
    decisions = []
    injector.create_subscription(HazardAlert, "/swarm/hazard_alert", alerts.append, 10)
    injector.create_subscription(HazardDecision, "/swarm/hazard_decision", decisions.append, 10)
    verdict_publisher = injector.create_publisher(HazardVerdict, "/swarm/hazard_verdict", 10)
    executor = SingleThreadedExecutor()
    executor.add_node(sentinel)
    executor.add_node(injector)
    samples = []
    try:
        discovery_deadline = time.monotonic() + 5.0
        while time.monotonic() < discovery_deadline:
            executor.spin_once(timeout_sec=0.05)
            if verdict_publisher.get_subscription_count() >= 1 and sentinel.decision_publisher.get_subscription_count() >= 1:
                break
        if verdict_publisher.get_subscription_count() < 1:
            raise RuntimeError("Sentinel verdict subscription was not discovered")
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
                matches = [message for message in decisions if message.event_id == event_id]
                if matches:
                    decision = matches[0]
                    break
            else:
                raise RuntimeError("timeout decision was not observed")
            if decision.decision != "TIMEOUT":
                raise RuntimeError("event did not finalize as TIMEOUT before late verdict")
            decision_count_before = len(decisions)
            injection_times = []
            for duplicate_index in range(2):
                now_ns = monotonic_ns()
                message = HazardVerdict()
                message.header.stamp = injector.get_clock().now().to_msg()
                message.header.frame_id = "scout_injected_fault"
                message.experiment_id = sentinel.experiment_id
                message.trial_id = sentinel.trial_id
                message.event_id = event_id
                message.source_device = "scout"
                message.hazard_type = "fire"
                message.verdict = "CONFIRMED"
                message.confidence = 0.90
                message.reason = "injected_late_duplicate_verdict"
                message.model_sha256 = "d533e320081be17ac91fb77c20a9de09f4bffada0d7f88c88326d57cd893bc35"
                message.alert_received_monotonic_ns = now_ns
                message.source_frame_monotonic_ns = 0
                message.verdict_monotonic_ns = now_ns
                verdict_publisher.publish(message)
                injection_times.append(now_ns)
                settle = time.monotonic() + 0.35
                while time.monotonic() < settle:
                    executor.spin_once(timeout_sec=0.02)
            if len(decisions) != decision_count_before:
                raise RuntimeError("late/duplicate verdict created an extra final decision")
            samples.append(
                {
                    "repetition": index + 1,
                    "event_id": event_id,
                    "final_decision": decision.decision,
                    "reason": decision.reason,
                    "late_verdict_injections": 2,
                    "late_verdict_monotonic_ns": injection_times,
                    "extra_final_decisions": 0,
                }
            )
        result = {
            "schema_version": 1,
            "status": "PASS",
            "fault": "late_and_duplicate_scout_verdict_after_timeout",
            "repetitions": arguments.count,
            "sentinel_timeout_ms_configured": timeout_ns / 1000000.0,
            "timeout_decisions": len(decisions),
            "injected_late_or_duplicate_verdicts": arguments.count * 2,
            "extra_final_decisions": 0,
            "samples": samples,
            "claim_boundary": (
                "Each synthetic Sentinel alert first finalized as TIMEOUT, after which two "
                "CONFIRMED verdicts with the finalized event ID were injected. This tests the "
                "deployed Sentinel's late/duplicate-verdict rejection path, not a natural "
                "network delay distribution, camera detection, flight, or industrial reliability."
            ),
        }
        with open(arguments.output, "w") as output:
            json.dump(result, output, indent=2, sort_keys=True)
            output.write("\n")
        print(json.dumps(result, sort_keys=True))
    finally:
        executor.remove_node(injector)
        executor.remove_node(sentinel)
        injector.destroy_node()
        sentinel.close()
        sentinel.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
