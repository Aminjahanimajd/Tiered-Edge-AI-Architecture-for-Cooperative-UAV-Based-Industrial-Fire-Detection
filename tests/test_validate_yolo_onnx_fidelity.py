from tools.validate_yolo_onnx_fidelity import match_predictions, xywh_iou


def test_iou_and_greedy_match_contract():
    native = [{"image_id": 1, "category_id": 1, "bbox": [0, 0, 10, 10], "score": 0.8}]
    converted = [{"image_id": 1, "category_id": 1, "bbox": [0, 0, 10, 10], "score": 0.79}]
    assert xywh_iou(native[0]["bbox"], converted[0]["bbox"]) == 1.0
    result = match_predictions(native, converted)
    assert result["detection_match_rate"] == 1.0
    assert abs(result["mean_absolute_confidence_difference"] - 0.01) < 1e-9


def test_unmatched_extra_detection_reduces_rate():
    native = [{"image_id": 1, "category_id": 1, "bbox": [0, 0, 10, 10], "score": 0.8}]
    converted = native + [{"image_id": 1, "category_id": 1, "bbox": [20, 20, 2, 2], "score": 0.2}]
    assert match_predictions(native, converted)["detection_match_rate"] == 0.5
