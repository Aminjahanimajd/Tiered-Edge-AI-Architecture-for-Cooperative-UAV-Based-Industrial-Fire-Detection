from tools.export_yolo_onnx_candidates import candidates


def test_candidate_filter_keeps_only_ultralytics_models():
    registry = {
        "models": [
            {
                "model_id": "yolo",
                "native_framework": "ultralytics",
                "input_size": 416,
                "native_artifacts": [{"path": "a.pt", "sha256": "abc"}],
            },
            {
                "model_id": "ssd",
                "native_framework": "tensorflow_object_detection_api",
                "input_size": 320,
                "native_artifacts": [{"path": "ckpt", "sha256": "def"}],
            },
        ]
    }
    assert candidates(registry) == [{
        "model_id": "yolo",
        "input_size": 416,
        "source_path": "a.pt",
        "source_sha256": "abc",
    }]
