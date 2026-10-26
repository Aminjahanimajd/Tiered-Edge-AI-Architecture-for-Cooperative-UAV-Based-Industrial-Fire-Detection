# M3 duplicate/stale verdict fault implementation — 13 August 2026

I added the `duplicate_or_stale_verdict` fault to the dual-PX4 hierarchical
mission runner. During verification, the runner first submits a deliberately
wrong event ID and requires the controller to reject it. It then applies the
valid active-event verdict once and submits the same verdict a second time.
The second submission must also be rejected because the event has already been
finalized. Both rejected inputs are written to the mission event log with the
event ID and rejection reason. The mission may continue to its normal safe
confirmed or rejected branch only if both invalid inputs were rejected.

The host suite passed 211 tests after the change. Existing controller tests
independently cover mismatched active events, finalized-event reuse, and
duplicate final verdicts. The outer runner test confirms that the fault name is
preserved in the container command.

This checkpoint is implementation evidence, not an executed Gazebo fault
result. The attempted visual/spawn session failed before scene readiness, so I
did not label the fault as triggered and did not produce a mission success
observation. A versioned simulator run remains required after the isolated
simulation runtime is healthy. The tracked source hashes and this limitation
are in
`manifests/duplicate_stale_verdict_fault_implementation_20260813.json`.

## Executed Gazebo pilot

The first executed bundle (`duplicate_stale_v1`) completed the inner fault
mission successfully: it rejected the wrong event ID and the repeated final
verdict, verified both system identities, and landed both vehicles. The outer
bundle was nevertheless `FAIL` because its single ROS topic inventory was
sampled before DDS routing completed. I retained this pre-fix result rather
than relabelling it.

I replaced the one-shot inventory with bounded polling that records every
attempt and reran as `duplicate_stale_v2`. The corrected bundle passed. It
recorded 12 typed transitions, rejected both invalid verdict inputs, observed
all ten required ROS command/telemetry topics, and ended with Sentinel and
Scout in `LANDED`. The Sentinel required three mode/arm attempts and the Scout
one; no health check was bypassed. The v2 manifest and event-log hashes are
`cf61db31ba0b72b6a728f8ac079be2816f57dcedefaf1a52801cbbf724530565`
and `834cf493ffcf30fd5e18950a32c96e9cb3401b58ae8b450074a0e6fd586ab269`.

This is one development pilot, not the required 20-run formal fault result.
The v1/v2 lineage is indexed in
`manifests/hierarchical_px4_guard_fault_pilots_20260813.json`.
