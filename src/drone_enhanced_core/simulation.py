"""Deterministic coordination replay used before live ROS 2 integration."""

from __future__ import print_function

from .protocol import HazardAlert, TargetBox
from .state_machine import SentinelCoordinator


def make_simulated_alert(event_id="simulated-event-1"):
    return HazardAlert(
        "simulation",
        "protocol-replay",
        event_id,
        "sentinel",
        "fire",
        0.75,
        3,
        1000000000,
        1010000000,
        "a" * 64,
        TargetBox(0.5, 0.5, 0.1, 0.1, 640, 480),
    )


def replay_coordination(verdict_events, timeout_ns=1000000000):
    """Replay verdict dictionaries and return transition and final records.

    Each verdict dictionary contains `event_id`, `verdict`, `confidence`, and
    `now_ns`. A final timeout check is made after the configured deadline.
    """
    alert = make_simulated_alert()
    coordinator = SentinelCoordinator(
        timeout_ns=timeout_ns,
        rejection_cooldown_ns=5000000000,
        cooldown_radius=0.1,
    )
    records = []
    tracking = coordinator.begin_tracking(alert.target_box, alert.alert_monotonic_ns)
    records.append(
        {
            "action": "begin_tracking",
            "accepted": tracking.accepted,
            "state": tracking.state.value,
            "reason": tracking.reason,
        }
    )
    dispatch = coordinator.dispatch_alert(alert, alert.alert_monotonic_ns)
    records.append(
        {
            "action": "dispatch_alert",
            "accepted": dispatch.accepted,
            "state": dispatch.state.value,
            "reason": dispatch.reason,
            "event_id": alert.event_id,
        }
    )
    finals = []
    for event in verdict_events:
        result = coordinator.handle_verdict(
            event["event_id"],
            event["verdict"],
            event["confidence"],
            event["now_ns"],
            event.get("reason", "simulated verdict"),
        )
        record = {
            "action": "handle_verdict",
            "input_event_id": event["event_id"],
            "input_verdict": event["verdict"],
            "accepted": result.accepted,
            "state": result.state.value,
            "reason": result.reason,
        }
        if result.final_decision is not None:
            final = result.final_decision._asdict()
            record["final_decision"] = final
            finals.append(final)
        records.append(record)
    if not finals:
        result = coordinator.check_timeout(alert.alert_monotonic_ns + timeout_ns + 1)
        record = {
            "action": "check_timeout",
            "accepted": result.accepted,
            "state": result.state.value,
            "reason": result.reason,
        }
        if result.final_decision is not None:
            final = result.final_decision._asdict()
            record["final_decision"] = final
            finals.append(final)
        records.append(record)
    return {"records": records, "final_decisions": finals}
