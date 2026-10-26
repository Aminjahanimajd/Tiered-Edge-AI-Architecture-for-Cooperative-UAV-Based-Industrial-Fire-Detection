# M6 Stationary Complete-Service Endurance — 29 September 2026

## Scope and safety state

I evaluated whether the deployed Sentinel and Scout pipelines could coexist
for at least 30 minutes with the normal stationary service stack. Both
aircraft remained on the laboratory bench with their propellers removed. The
Sentinel Pixhawk was powered and connected to the Jetson through the retained
MAVProxy telemetry bridge; the Scout retained its VOXL camera, PX4, IMU,
MAVLink, QVIO, portal, and related platform services. Both ROS 2 nodes used
`enable_flight_commands=false`. No vehicle command, arming, motor output, or
physical flight was authorized.

This trial measures stationary service coexistence and host-wide resource
behavior. It does not measure electrical power, energy, detector accuracy,
ignition-to-detection latency, physical-flight reliability, or operational
industrial reliability.

## Configuration and retained attempts

The accepted device run is `fullstack-20260929-r2`. The Sentinel used the
deployed 640-pixel TensorRT engine with SHA-256
`16f9018ac299c6f525610a877d798392ec26d53fccb84b589ff6533d76589bf2`
and the live D435i. The Scout used the 640-pixel TFLite model with SHA-256
`d533e320081be17ac91fb77c20a9de09f4bffada0d7f88c88326d57cd893bc35`,
the live `/tracking` stream, and one interpreter thread. Host resources were
sampled at approximately 1 Hz.

I retained two configuration-development outcomes:

1. `fullstack-20260929-r1` is retained as an earlier setup attempt.
2. The intended 30-minute hierarchy probe used trial identifier
   `fullstack-20260929-r2-probe`, whereas both device nodes used
   `fullstack-20260929-r2`. The Scout correctly rejected all 360 alerts at its
   trial-isolation gate. This probe therefore failed and supplies no latency
   measurement. I corrected only the probe identifier and ran a separate
   180.245 s probe near the end of the service window. It received 36/36
   correlated verdicts.

The failed probe remains part of the evidence. The corrected three-minute
result is not relabelled as a 30-minute hierarchy-load test.

## Results

| Measure | Sentinel Jetson Nano | Scout VOXL 2 |
|---|---:|---:|
| Host-resource observation | 1,939.7 s | 1,934.8 s |
| Resource samples | 1,552 | 1,833 |
| Inference frames / verification inferences | 30,426 | 36 |
| Inference latency, mean | 60.035 ms | 2,439.066 ms |
| Inference latency, p95 | 61.170 ms | 2,511.611 ms |
| Host CPU, mean | 32.65% | 42.44% |
| Host CPU, p95 | 34.27% | 48.46% |
| Minimum `MemAvailable` | 1,589.9 MiB | 4,873.8 MiB |
| Swap growth, first to last sample | 0.922 MiB | 0 MiB |
| Maximum valid thermal-zone reading | 51.0 degrees C | 48.2 degrees C |
| Camera errors | 0 | not represented by an error event |
| Maximum logger-dropped count | 0 | 0 |
| Wrapper disposition | bounded stop passed | bounded stop passed |

The corrected probe received 36/36 verdicts with zero missing, duplicate,
unexpected, or correlation-mismatched records. Synthetic alert-to-verdict
latency was 2,526.056 ms mean, 2,506.953 ms median, 2,485.620 ms minimum,
2,734.914 ms maximum, and 2,617.746 ms p95 (population standard deviation
52.421 ms, n=36). This latency begins at alert publication and includes ROS 2
transport, Scout queueing, live-frame inference, and verdict transport. It
excludes Sentinel camera inference and must not be interpreted as ignition-to-
detection latency.

The Sentinel MAVProxy service remained active before and after the run and
both snapshots retained `link 1 OK`. The existing service log also contained a
`fence breach` warning. No flight command was sent during this experiment, so
the warning is reported as a health observation rather than a tested recovery
condition. The Scout's normal platform services were present in the before and
after snapshots.

## Acceptance and interpretation

The run passed these preregistered checks:

- both resource-observation windows exceeded 1,800 s;
- both wrappers completed their bounded-stop procedure;
- all device control-manifest hashes matched after transfer;
- both models continued inference without a logged camera error, OOM, silent
  stop, or logger-record loss;
- Sentinel p95 inference latency remained below 200 ms;
- Sentinel minimum available memory remained above 512 MiB;
- the corrected three-minute probe was complete and correctly correlated;
- MAVProxy remained active with a vehicle link before and after the run.

Two constraints were not satisfied. Scout p95 alert-to-verdict latency was
2,617.746 ms, 617.746 ms above the 2 s target. Sentinel swap increased by
0.922 MiB between the first and last host samples, so the strict no-swap-growth
criterion is recorded as unmet even though the maximum observed swap use was
less than 1 MiB. These outcomes are retained as measured resource constraints;
the acceptance thresholds were not changed after observing the data.

The evidence supports a bounded claim of 30-minute stationary coexistence of
the live cameras, deployed edge inference, ROS 2, asynchronous logging,
SwarmNet, Scout PX4 services, and Sentinel MAVProxy/Pixhawk telemetry. It also
supports a separate 36-event live Scout-verification probe during the final
three minutes. It does not establish 30 minutes of continuous hierarchical
requests or an integrated Sentinel-camera-to-final-decision latency.

## Traceability

The immutable transferred archives are:

- Sentinel: `artifacts/experiments/hardware_full_service_20260929/raw/`
  `sentinel_full_service_20260929.tar.gz`, SHA-256
  `77a51870543a1ec48d29d0b3efb70cb71f62a21cc8fb32717780ad70d4f8c450`;
- Scout: `artifacts/experiments/hardware_full_service_20260929/raw/`
  `scout_full_service_20260929.tar.gz`, SHA-256
  `705cb09814a49a64850fd23b4481a304ce2674ecb99089c8e521c97105544093`.

All 11 Sentinel and 12 Scout files listed in the device-side control manifests
matched their recorded SHA-256 values after transfer. The reproducible derived
record is
`artifacts/experiments/hardware_full_service_20260929/derived/`
`full_service_summary.json`. The resource time-series and latency figures in
the adjacent `figures/` directory are derived from the hash-linked JSONL
inputs. Raw archives and extracted evidence remain separate from derived
outputs.
