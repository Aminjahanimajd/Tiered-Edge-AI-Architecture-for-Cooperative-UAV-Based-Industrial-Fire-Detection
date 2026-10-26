# M2 Correlated ROS 2 Round-Trip Evaluation

**Evaluation date:** 29 July 2026  
**Probe revision:** `a9a75fb`  
**Analysis method:** `analyze_ros_roundtrip.py`  
**Status:** three camera-free trials completed, 300/300 correlated replies observed

## Objective

I measured application-level round-trip time and observed correlated reply
delivery between the Sentinel and Scout. The Sentinel published an injected
`HazardAlert`; the Scout callback published a `HazardVerdict` with the same
experiment, trial, and event identity; and the Sentinel measured the duration
from local publication to its local correlated-verdict callback.

This request/reply method uses only the Sentinel's monotonic clock for each
duration. It therefore avoids cross-device clock subtraction and does not depend
on the measured wall-clock offset. It measures round-trip time, not one-way
latency.

## Safety and configuration

Both drones remained stationary with propellers removed. No camera, model
inference, full enhanced node, flight command, or lighter was used.

The fixed communication configuration was:

- RMW: `rmw_cyclonedds_cpp`;
- interface: `wlan0` through the hashed SwarmNet Cyclone DDS profile;
- QoS: reliable, volatile, history depth 100;
- request topic: `/swarm/hazard_alert`;
- reply topic: `/swarm/hazard_verdict`;
- initiator: Sentinel in a disposable Foxy container;
- responder: Scout in native Foxy;
- events per trial: 100; and
- per-event timeout: 1 s.

I used ROS domains 43, 44, and 45 for trials `ros-rtt-001`, `ros-rtt-002`, and
`ros-rtt-003`. Each event used a unique sequence-bearing event ID. The next event
was sent after the previous event received a reply or reached its timeout. This
was a sequential latency test, not a maximum-throughput or congestion test.

The probe file SHA-256 verified on both devices as
`b2a01b232c4439f5f5c6f9d38024a661d210eb3ce181f40b6bcfc0d98829fa91`.

## Metrics and formulas

For each successful event:

```text
RTT_ms = (Sentinel verdict-callback monotonic ns
          - Sentinel alert-publication monotonic ns) / 1,000,000
```

For each trial and the pooled 300 observations, I calculated mean, median,
minimum, maximum, population standard deviation, and linearly interpolated
percentiles. Population variance uses divisor `n`. Percentile index is
`(n - 1) * percentage / 100`.

I also retained counts above 10, 20, 50, and 100 ms. Tukey tail observations are
defined as values greater than `Q3 + 1.5 * (Q3 - Q1)`. They are retained, not
deleted or winsorized.

## Per-trial results

| Trial | Replies | Missing | Median (ms) | Mean (ms) | P95 (ms) | Maximum (ms) | SD (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|
| `ros-rtt-001` | 100 | 0 | 5.977 | 10.756 | 13.212 | 400.453 | 39.279 |
| `ros-rtt-002` | 100 | 0 | 6.158 | 7.204 | 12.665 | 35.748 | 4.535 |
| `ros-rtt-003` | 100 | 0 | 5.560 | 6.496 | 10.532 | 32.393 | 3.583 |

Every initiator event received one correlated `CONFIRMED` reply from source
`scout`. The initiator observed no mismatched or unexpected event ID. The
responder observed all 100 request IDs in each trial and no duplicate event ID.

## Pooled descriptive result

Across 300 sequential events:

- received replies: 300;
- missing replies: 0;
- observed application-level reply fraction: 1.000;
- correlation mismatches: 0;
- responder duplicates: 0;
- median RTT: 5.878 ms;
- mean RTT: 8.152 ms;
- minimum RTT: 3.359 ms;
- P95 RTT: 12.758 ms;
- P99 RTT: 32.407 ms;
- maximum RTT: 400.453 ms; and
- population standard deviation: 22.998 ms.

Thirty observations exceeded 10 ms, five exceeded 20 ms, one exceeded 50 ms,
and one exceeded 100 ms. The pooled Tukey upper fence was 11.455 ms; 20 retained
observations exceeded that descriptive threshold.

The largest event was `rtt001-0085` at 400.453 ms. It was still below the 1 s
timeout and produced a correctly correlated reply. The next three largest values
were 35.748, 33.788, and 32.393 ms. The isolated 400 ms event explains why the
pooled mean and standard deviation are much larger than the median and P95.

## Engineering interpretation

The three trials demonstrate low typical camera-free request/reply delay on the
configured SwarmNet path: all trial medians were between 5.56 and 6.16 ms and all
P95 values were below 13.22 ms. They also demonstrate a substantial tail event.
For hierarchical decision logic, timeout selection should therefore consider
the latency distribution and tail behavior rather than only the mean.

The 300/300 result is evidence that no application-level reply was missing in
these three short, sequential sessions. It is not a general reliability
guarantee. Reliable DDS can retransmit network packets below the application
layer, so a received reply does not prove zero packet loss. The experiment also
did not include concurrent inference, camera traffic, ROS image topics, network
interference, long duration, drone movement, or industrial conditions.

No confidence interval or statistical-significance test is reported. The 300
observations are serial samples from three consecutive sessions under one setup;
independence and representativeness of other conditions are not established.

## Claim boundary

The thesis may state:

> In three camera-free sequential trials over the isolated SwarmNet
> configuration, all 300 injected Sentinel alerts received a correlated Scout
> verdict. Median application-level ROS 2 round-trip time was 5.878 ms across the
> pooled observations, P95 was 12.758 ms, and one 400.453 ms tail event occurred.

The thesis must not relabel this result as one-way latency, packet-loss rate,
camera-to-alarm delay, inference-loaded performance, flight performance, or a
universal reliability guarantee.

## Evidence and reproducibility

The six initiator/responder record hashes are:

- Trial 1 Scout:
  `f7316a83da0361dc7b86d4a8d77a41f692a6c76e5c70894dd07135a4716d7293`;
- Trial 1 Sentinel:
  `9f50e5a0da1ca816dd4024c357af8b490986712e31b8fbac29c3fc26a5ff24d8`;
- Trial 2 Scout:
  `7b4bfce279f5dacea05e60d0c2491c7cd1bed7141444170567acee98dfe4de82`;
- Trial 2 Sentinel:
  `7a4ac6617e99e2f236ce3f75a2ef2c27856a4ee8d345ec50b7de69d20d57e827`;
- Trial 3 Scout:
  `b0c1b93725a6f20aa2eee1b68add2d529786430355510b52321399f1db1a4f3d`;
- Trial 3 Sentinel:
  `4907f64c1e534121bd16dfaa0b9e2fa07a6e0eef8a6496538553f23de41d4b10`.

All six records passed and their evidence-index SHA-256 is
`539f11a88ebc140be636aa172f1202af2a8927e7d30c24b4b4097d291c7d3496`.

The processed 300-row CSV SHA-256 is
`a9813c4de5de8f4025947983a22b1e2cec8ea80540d8fa0adfcbcb7874d8112f`.
The analysis JSON SHA-256 is
`2c61e2a8531efb70f9921c736d22baef28270be4a6e5c3dbe671b14bc6a7364b`.

`tools/analyze_ros_roundtrip.py` verifies every source-record hash, checks the
three initiator/responder pairs, exports all observations, recalculates trial and
pooled summaries, and preserves the explicit claim boundary.

## Thesis placement

- **Methodology:** request/reply protocol, QoS, isolated domains, sequence IDs,
  local monotonic timing, formulas, and thresholds.
- **Results:** per-trial and pooled latency tables and observed delivery counts.
- **Discussion:** typical delay, tail event, timeout selection, and conditional
  hierarchical coordination.
- **Limitations:** short camera-free sequential trials, DDS retransmission,
  uncontrolled background load, no inference or image traffic, and no
  inferential statistics.
- **Appendix:** 300-row CSV, six raw envelopes, analysis JSON, and source hashes.
