# M8 Dual-PX4/Gazebo Visual Mission — 30 September 2026

## Purpose and evidence boundary

I executed and recorded one complete confirmed-hazard development mission using
two namespaced PX4 v1.17.0 SITL instances in Gazebo 8 with ROS 2 Jazzy. The
Sentinel used the orange X500 V2-derived proxy and system ID 2; the Scout used
the blue ModalAI Development Kit/Starling-derived proxy and system ID 3. The
vehicles used separate ROS 2 namespaces, DDS identities, command topics, and
PX4 logs.

The airframes are provisional simulation proxies. The hazard position, the
low-confidence trigger, target acquisition, and final verdict are scenario
truth. They are not outputs of the physical cameras or trained detectors. This
run is evidence that the recorded mission software and PX4 command paths were
executable under the simulated conditions. It is not physical-flight
certification, simulator-fidelity validation, vision-derived localization, an
industrial-site trial, or a formal reliability estimate.

## Accepted run and sequence

The authoritative run is
`hierarchical_px4_visual_confirmed_20260930_v17`, event
`scenario-fire-tank-a`. Its manifest status, spawn status, visual-capture
status, and mission status are all `PASS`. All ten required Sentinel and Scout
PX4 ROS 2 input/output topics were present. Both identities were verified and
the final typed state was `LANDED` for both vehicles.

| Elapsed from mission start | Recorded event |
|---:|---|
| 0.000 s | Mission node starts |
| 39.821 s | Sentinel reaches patrol and begins the route |
| 105.215 s | Scenario-defined low-confidence fire candidate triggers |
| 105.216 s | Sentinel holds and tracks the scenario target |
| 133.424 s | Scout takeoff completes and transit begins |
| 144.124 s | Scout reaches the scenario-defined safe standoff |
| 144.125 s | Sentinel releases tracking and resumes independent patrol |
| 147.223 s | Scenario-defined Scout verdict is applied as `CONFIRMED` |
| 147.223 s | `HazardDecision` is published to the simulated alarm interface |
| 214.253 s | Both vehicles are landed and disarmed |

The target was defined at local ENU `[12.0, 5.0, 4.0]` m. The Scout dispatch
setpoint was `[7.704840098842366, 3.6577625308882395, 5.0]` m, giving a
commanded horizontal standoff of exactly 4.5 m. These coordinates come from the
versioned scenario manifest, not from image-space localization.

The accepted run used a 60 s landing timeout. A retained v16 attempt completed
patrol, alert, dispatch, confirmation, alarm publication, and return, but it
missed the earlier 30 s landing bound while the recorder slowed the simulator.
The bound was therefore changed explicitly and recorded; the v16 failure was
not overwritten.

## Retained development history

Earlier attempts remain in the evidence tree:

- v7 passed its then-current mission checks, but its screenshot-derived video,
  role presentation, annotations, and camera framing were rejected during
  visual review. It is superseded and is not thesis visual evidence.
- v14 failed during PX4/XRCE cleanup and later timed out; it remains a failure
  record.
- v15 was interrupted after only partial startup/capture evidence and has no
  accepted run manifest.
- v16 completed the main confirmed-hazard sequence but failed the recorded
  30 s landing timeout.
- v17 passed the revised, explicit 60 s landing bound and all identity, topic,
  mission, and visual-capture gates.

## Visual evidence

The defense bundle is:

`artifacts/experiments/hierarchical_px4_visual_confirmed_20260930_v17/visual_delivery_v6/`

The principal video, `gazebo_full_mission_defense.mp4`, is a continuous
1280-by-720 H.264 recording at 25 frames/s with 6,595 frames and a duration of
approximately 263.8 s. It has no burned-in mission notes. The separate SRT
timeline and event log provide the semantic trace. The video SHA-256 is
`cc83606c76183e9b9c3e67160f7eb18521098c22a42d6eb566a9e9b702116812`.

The corrected six-panel thesis contact sheet is
`simulation_mission_contact_sheet.png`, SHA-256
`84ff7a9b6dd61ddc0f2121187e961d9ac4fcaea601dcf47dee1b744f6afa4011`.
Its legend distinguishes the orange cross-shaped Sentinel, blue dome-shaped
Scout, and coloured floor discs used only as home markers. The Scout-transit
still is sampled five seconds after the recorded transit transition so that it
shows displacement while remaining within the transit interval. The
safe-standoff panel uses the registered accepted capture frame, while the fifth
panel reproduces exact fields from the retained alarm event rather than
presenting an unrelated scene frame as a ROS message.

### Final visual-review disposition

On 30 September 2026, after inspecting the continuous v3 delivery, I accepted
its role presentation and end-to-end sequence as suitable visual evidence for
the thesis and oral defence. The v6 derived delivery retains the identical
accepted video hash and corrects only the thesis contact sheet. This review
supersedes the rejection of the v7 delivery. It is a presentation-quality
decision only: the machine-readable
manifest, event log and PX4/ROS 2 records remain the evidentiary basis for the
mission events and timings.

## Traceability and interpretation

The v17 run manifest SHA-256 is
`468debf0734252d34cab2feb710d522e68830595e4953974d711b40338a62f4a`.
The event-log SHA-256 is
`53ca0b7408cbf80ad531d90beeaf9161a9f123e4be335c982b6b6280fade9c31`.
The continuous native recording SHA-256 is
`e5836b26827da8a739711d8f585711549992978037bda36ec0721c356478e7a5`.
The visual-delivery manifest records every source and derived hash, the video
conversion command, the selected still offsets, vehicle identities, target and
standoff coordinates, final states, and evidence boundary.

This single accepted run supports a bounded executability statement for RQ4.
The preregistered 310-run nominal/fault campaign was not completed, so no
mission-success probability or operational reliability claim is reported.
