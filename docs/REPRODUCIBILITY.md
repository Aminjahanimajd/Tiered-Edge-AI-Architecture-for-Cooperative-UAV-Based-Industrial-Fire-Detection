# Reproduction guide

## 1. Portable software checks

Use Python 3.12 and an isolated environment. Install the root package and `requirements-dev.txt`, then run:

```sh
python -m pytest tests -q
python tools/verify_publication.py
python tools/replay_coordination.py duplicate_confirmation
```

The release was checked locally with **264 tests passing and 5 explicitly skipped**. The skips concern the complete private model/calibration archive and an external-data decode record. They do not turn missing artifacts into passing gates. The readiness tools still report absent inputs as blocked/fail. These results are host-software checks, not renewed hardware measurements.

The core retains compatibility-oriented code for historical device Python environments; analysis/orchestration utilities require newer Python. Do not install current host-test packages into the historical Jetson/VOXL images.

## 2. Inspect or regenerate selected results

Install `requirements-analysis.txt` for plotting. The six-model CSVs and JSONs are bundled at their historical relative paths:

```sh
python tools/generate_model_comparison_figures.py --validation-csv artifacts/experiments/model_screening_v1/validation_comparison_v1/consolidated_20260809/validation_model_comparison.csv --test-csv artifacts/experiments/model_screening_v1/test_comparison_v1/consolidated_20260809/test_model_comparison.csv --output-directory output/model_figures
```

Host-resource JSONL samples are included under `artifacts/experiments/hardware_full_service_20260929/extracted/`. The retained full-service renderer exposes `render_resources()` for these inputs. Its complete CLI additionally requires inference/probe event logs from the private archive; do not supply synthetic substitutes and label them as original evidence.

Network sample CSV and summary are in `evidence/network/`. Read [the network report](M7_LOADED_ROS2_ROUNDTRIP_20260928.md) for the round-trip clock boundary. The private raw initiator/responder logs are identified by hash in the summary.

Selected raw records retain their original bytes, hashes and historical paths. Some original paths resolve only in the private archive. The [publication manifest](../evidence/publication_manifest.json) lists the files actually bundled here. A hash alone does not reconstruct an omitted file.

## 3. Hardware environments

The Sentinel used Jetson Nano 4 GB with NVIDIA L4T/Ubuntu 18.04 on the host and ROS 2 Foxy inside an L4T-compatible Docker container. The Scout used the native VOXL 2 / Ubuntu 18.04 / ROS 2 Foxy environment and ModalAI camera/MPA services. Matching ROS middleware and interfaces, not identical host OS installations, enabled the two-node exchange. See thesis Chapters 3 and 5 for exact recorded software distinctions.

The physical ROS packages are in `ros2_ws/src/`. Build them with the historical Foxy toolchain and the root core package available to Python. Backends need device-specific TensorRT/PyCUDA/GStreamer or TFLite/camera services, separately supplied model files and verified hashes. The generic runtime YAML is an example, not a substitute for a particular experiment's frozen launch configuration. In particular, the endurance Scout used `/tracking` and one TFLite thread, while the generic example differs.

No ROS Foxy, NVIDIA, ModalAI, PX4 or model runtime is silently downloaded by the quick-start tests. No physical deployment was rerun when preparing this repository.

## 4. Simulated aerial mission

See [simulation/README.md](../simulation/README.md). The accepted run used two PX4 v1.17.0 SITL instances, Gazebo 8 and ROS 2 Jazzy, isolated from the physical Foxy deployment. The host-side orchestrator in `tools/run_hierarchical_px4_mission.py` reflects the original Windows/WSL/Docker setup; it is not a one-command portable simulator installer.

The versioned visual scenario is `config/simulation_scenarios_visual_v3.json`. An isolated runtime and ROS/PX4 interfaces are required to rerun it. Both provisional models inherit upstream X500 dynamics. The command-line runner uses a conservative default landing bound; the accepted v17 trial explicitly used `--landing-timeout-s 60`. Reusing a different timeout creates a different configuration.

ROS 2 sends actual namespaced offboard setpoints/commands to SITL and reads PX4 telemetry. The scenario supplies the hazard event, local-ENU location and verdict. It does not close the loop with camera-based detection. Recorded terminal states and alarm publication are supported by the event log, not the video alone.

## 5. Thesis build

Follow [thesis/README.md](../thesis/README.md). The frozen PDF is the authoritative published dissertation. Font/TeX version differences can change layout or PDF bytes on a rebuild; verify extracted content and figures, not only page count.

## 6. Data and model availability

The source-family freeze records 3,558 training, 700 validation and 733 test images. Dataset images, trained models, framework environments and the complete raw archive are excluded. The lineage/configuration describes acquisition and preprocessing but does not grant data rights or guarantee that upstream files remain available. See [RIGHTS_AND_DATA.md](../RIGHTS_AND_DATA.md).
