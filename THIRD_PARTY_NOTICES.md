# Third-party components and notices

Third-party components are referenced, not relicensed as original work. This is a dependency notice, not a legal determination that every possible downstream use is compliant.

| Component/material | Role | Source / rights notice |
| --- | --- | --- |
| Ultralytics YOLOv8 | Detector training/export and historical model implementations | [Ultralytics licensing](https://www.ultralytics.com/license), AGPL-3.0 / enterprise options |
| TensorFlow, TensorFlow Lite, Object Detection API | Scout inference and comparison candidates | [TensorFlow repository](https://github.com/tensorflow/tensorflow), inspect upstream license and model terms |
| NVIDIA TensorRT, CUDA, L4T / JetPack | Jetson inference/runtime | [NVIDIA TensorRT](https://developer.nvidia.com/tensorrt), vendor terms apply; binaries not included |
| ROS 2, Cyclone DDS | Messaging, interfaces and coordination | [ROS 2](https://github.com/ros2/ros2), [Cyclone DDS](https://github.com/eclipse-cyclonedds/cyclonedds); component-specific licenses |
| PX4-Autopilot | Simulated flight controller and upstream X500 dynamics | [PX4](https://github.com/PX4/PX4-Autopilot), BSD-3-Clause; runtime not vendored |
| Gazebo | Simulation rendering and physics | [Gazebo Sim](https://github.com/gazebosim/gz-sim), upstream Apache-2.0 |
| ModalAI MPA / VOXL services | Camera and platform integration | [ModalAI documentation](https://docs.modalai.com/); component-specific vendor terms |
| UNIME seal and thesis-template composition | Academic identification in thesis/slides | [Supplied UNIME template](https://www.overleaf.com/latex/templates/unime-computer-sciences-bachelors-thesis-template/nyjjqxrnhzzs); university mark remains its owner's property |
| Dataset-derived examples in academic documents | Illustration of the research data/method | See thesis citations and dataset provenance; not licensed by the AGPL software notice |

The customized physical platforms and original proxy definitions are distinguished from upstream components in the thesis. Both provisional simulator airframes inherit X500 dynamics; their separate visual geometry does not establish calibrated dynamic equivalence to the two real aircraft.

No model weights, vendor SDK binaries, datasets, copied MAVProxy implementation or third-party environment directories are included in this release.
