# Enhanced Sentinel–Scout Protocol Specification

**Version:** 0.1.0 (implemented protocol with bounded stationary deployment evidence)  
**Scope:** stationary fire/flame detection and independent verification

## Coordinate semantics

`target_u`, `target_v`, `bbox_width`, and `bbox_height` are normalized values
in the **Sentinel source-camera image frame**:

- origin: top-left of the Sentinel image;
- `u`: increases left to right;
- `v`: increases top to bottom;
- normalized range: `[0,1]`;
- box fields describe the Sentinel detection only.

They are not latitude, longitude, vehicle coordinates, or Scout image
coordinates. Scout uses an alert as a trigger and searches its own current
field of view independently.

## Identifiers

- `experiment_id`: one complete experimental campaign/configuration;
- `trial_id`: one ground-truth exposure or negative trial;
- `event_id`: one Sentinel alert and its correlated Scout/final outcome.

Identifiers are opaque non-empty strings. An `event_id` must never be reused
within an experiment.

## Time fields

ROS `Header.stamp` contains synchronized UTC/ROS time for cross-device
correlation. Every `*_monotonic_ns` field contains nanoseconds from the local
device monotonic clock and is used for durations on that device.

Monotonic values from different devices must not be subtracted directly.
Cross-device one-way latency requires clock-offset estimation. Round-trip time
can be computed on the originating device without synchronized monotonic clock
epochs.

## Topics and messages

### `/swarm/hazard_alert`

Type: `drone_enhanced_interfaces/HazardAlert`  
Direction: Sentinel → Scout

Published only after the Sentinel temporal filter reaches its configured
consecutive-frame count. Contains correlation IDs, source-frame metadata,
model identity, confidence, and normalized Sentinel image box.

### `/swarm/hazard_verdict`

Type: `drone_enhanced_interfaces/HazardVerdict`  
Direction: Scout → Sentinel

Valid verdict values:

- `CONFIRMED`;
- `REJECTED`;
- `ERROR`.

Scout returns at most one verdict for an `event_id`. Duplicate messages may be
delivered by the transport but must not produce a second final decision.

### `/swarm/hazard_decision`

Type: `drone_enhanced_interfaces/HazardDecision`  
Direction: Sentinel → logger/operator/consumer

Valid final decision values:

- `CONFIRMED`;
- `REJECTED`;
- `TIMEOUT`;
- `ERROR`.

Exactly one accepted final decision is emitted per Sentinel `event_id`.

## State sequence

```text
SEARCHING
  -> TRACKING
  -> AWAITING_SCOUT
  -> CONFIRMED | REJECTED | TIMEOUT | ERROR
  -> SEARCHING
```

An unrelated, duplicate, or late event ID cannot close the active event.

## Rejection cooldown

Historical permanent spatial blacklisting is replaced by a configured
time-limited cooldown in normalized Sentinel image space. It exists only to
prevent immediate repeated alerts after a verified rejection. After expiration
the same image region is eligible again. The radius and duration are logged as
experiment configuration and must be evaluated empirically.

## Logging

Every raw event record is JSON Lines and contains, as applicable:

- schema version;
- experiment/trial/event IDs;
- device and process identity;
- UTC and monotonic timestamps;
- model SHA-256;
- thresholds and temporal count;
- frame identity and freshness;
- inference latency;
- alert/verdict/final-decision status;
- logging queue drop counters.

The runtime uses a bounded non-blocking queue and one dedicated file writer.
Raw files are append-only. Corrections and exclusions are separate records;
raw observations are never overwritten.

## Implemented QoS and measurement boundary

The nodes pass depth 10 to ROS 2 alert, verdict and decision publishers/subscribers. This uses the corresponding default reliable, volatile, keep-last profile rather than a separately tuned deadline/liveliness policy. The Scout camera subscription uses `qos_profile_sensor_data`.

Stationary exchange and fault results are documented in the dated hardware/network reports. They do not establish airborne delivery guarantees, complete restart recovery or independently validated deadline/liveliness settings.
