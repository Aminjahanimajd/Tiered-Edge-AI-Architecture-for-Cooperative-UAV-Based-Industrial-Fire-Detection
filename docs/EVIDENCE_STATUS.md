# Final evidence status and result map

This file is the current publication-level summary. Dated experiment reports describe their historical cutoff and may mention then-pending work. Do not interpret a prepared protocol, model conversion or passing host test as a completed field experiment.

| Programme | Admitted evidence | Main record |
| --- | --- | --- |
| Predictive comparison | Six models, frozen grouped splits, one-time test; EfficientDet ranking reversed between validation and test | [Selection freeze](MODEL_SELECTION_FREEZE_20260809.md), [test evaluation](TEST_EVALUATION_20260809.md), `artifacts/experiments/model_screening_v1/` |
| Exact deployed inference | Historical YOLOv8n-640 TensorRT / YOLOv8s-640 TFLite measurements, not a completed 12-cell deployment screen | [Hardware report](M4_HARDWARE_LAB_20260803.md), `artifacts/experiments/hardware_lab_20260803/derived/backend_comparison_r1/benchmark_analysis.json` |
| Decoder optimization | Separate before/after runs, 72.1% Sentinel mean pipeline reduction | [Optimization report](M2_DECODER_OPTIMIZATION_20260729.md), `evidence/decoder/` |
| Full-service coexistence | >30 min host-resource observation; 30,426 Sentinel frames; a separate final 36-event Scout probe | [Endurance report](M6_FULL_SERVICE_ENDURANCE_20260929.md), `artifacts/experiments/hardware_full_service_20260929/` |
| Physical workflow | Marked condition-specific observations; not general accuracy | [Hardware report](M4_HARDWARE_LAB_20260803.md), `artifacts/experiments/hardware_lab_20260803/derived/postfix_integrated_validation_r1/analysis.json` |
| Network | Loaded 1,000-event stationary round-trip experiment | [Network report](M7_LOADED_ROS2_ROUNDTRIP_20260928.md), `evidence/network/` |
| Fault handling | Bounded camera-interface, stale-frame, process-unavailable and late/duplicate-verdict repetitions | Four `M7_*FAULT*` / stale-stream reports in this folder |
| Simulated mission | One accepted v17 visual mission and earlier development/fault pilots | [Mission report](M8_DUAL_PX4_VISUAL_MISSION_20260930.md), `artifacts/experiments/hierarchical_px4_visual_confirmed_20260930_v17/` |
| External evaluation | Preparation only, no admitted predictive result | Thesis Results/Discussion; `config/external_evaluation_sources_v1.json` |

## Limits retained in the public release

- Small unstable flame: 1/10 confirmations in that marked condition.
- Complete-service Scout alert-to-verdict p95: 2,617.746 ms, above the frozen 2,000 ms target.
- Sentinel swap growth: 0.921875 MiB, so the strict no-growth criterion failed.
- The corrected 36-event probe covers the final three minutes, not a full 30-minute continuous hierarchy-load trial.
- No complete six-model/two-device Pareto evaluation, common-stimulus accuracy ablation, formal 310-run simulation campaign or external generalization evaluation.
- No integrated physical flight, vision-derived geographic localization, physical smoke validation or operational industrial-site validation.
- Simulator trigger, coordinates and verdict come from the scenario, not YOLO inference on rendered camera frames.
- Both simulator proxy airframes inherit X500 dynamics and lack a completed physical-parameter calibration.

The software implements safeguards and a traceable decision path. These observations do not establish perfect detection, a measured accuracy gain from cooperation, general network reliability or flight certification.

## Check the published artifacts

`python tools/verify_publication.py` checks bundled hashes and selected headline metrics. This is a transcription/integrity check, not an independent reproduction of private training or hardware experiments.
