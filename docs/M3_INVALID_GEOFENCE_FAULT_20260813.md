# M3 invalid/out-of-geofence target fault — 13 August 2026

I implemented the `invalid_or_out_of_geofence_target` simulation fault at the
boundary between Sentinel detection and Scout dispatch. The fault constructs a
local-ENU target one metre beyond the scenario's east geofence and passes it to
the Scout command guard. The guard must reject the coordinate before any Scout
takeoff target is set. The runner records the rejected coordinate and reason,
creates an unverified-hazard record, enters `DEGRADED`, and begins the safe
RTL/landing sequence for active vehicles.

The suspect-report call deliberately uses `request_scout=False` for this fault,
so the typed Scout state remains `PREFLIGHT` until the invalid command has been
rejected. This prevents the log from implying that Scout dispatch began when no
valid navigation target existed.

The complete host suite passed 212 tests. Existing unit evidence verifies that
the command guard rejects an out-of-geofence target, and the outer-runner test
verifies that the fault selection reaches the mission node. This is
implementation evidence only. The current Gazebo session failed before scene
readiness, so an executed versioned fault mission remains pending. Source
hashes and the limitation are frozen in
`manifests/invalid_geofence_fault_implementation_20260813.json`.

## Executed Gazebo pilot

The versioned `invalid_geofence_v1` run passed. The injected local-ENU target
`[25.0, 0.0, 1.0]` m was rejected because its east coordinate exceeded the
scenario boundary. All ten required ROS topics were present. Scout issued no
mode, arm, trajectory, or land command attempt, while Sentinel entered the
degraded recovery path and landed. Both final typed states were `LANDED`, both
system identities were verified, and the event log retained nine transitions.

The raw manifest SHA-256 is
`4124cd2a7c06e5cfa60fa45b74b0d196f46c633299c0f7de9279a265bb3b37d0`;
the event-log SHA-256 is
`53c77bc48cfa512466ba2fc7b17a0034fbc9f80dda689d89776a165ed1329247`.
This is a single development pilot, not a reliability estimate or physical
geofence validation. Twenty frozen formal repetitions remain required in M8.
