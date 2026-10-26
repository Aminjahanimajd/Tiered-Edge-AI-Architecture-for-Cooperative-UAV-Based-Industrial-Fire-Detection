# Safety and scope

This is a bachelor's research prototype, not a certified detector, emergency-alarm product, autonomous-flight system or industrial deployment package.

- Physical trials were stationary, with propellers removed. No integrated physical-flight validation is claimed.
- `enable_flight_commands` stays false in the physical-node configuration. Never disable safety locks to reproduce a bench measurement.
- Simulator commands must target isolated PX4 SITL instances only. Do not connect physical flight controllers to a simulator command experiment.
- Scenario coordinates use local ENU ground truth. Physical hazard-message coordinates refer to the Sentinel image plane. They are not interchangeable.
- Do not infer fire absence from a rejection, timeout, missing frame or missing event. The system showed weak retention for small unstable flame.
- Do not use recorded processing latencies as guaranteed response times. The complete-service Scout p95 exceeded its target.
- Device installation scripts and systemd examples are for reviewed, isolated research environments. They are not universal installation or unattended startup instructions.
- Follow laboratory, battery, electrical, fire, aviation and privacy requirements independently of this code.

Use existing approved fire-safety equipment and procedures; this prototype must not replace them.
