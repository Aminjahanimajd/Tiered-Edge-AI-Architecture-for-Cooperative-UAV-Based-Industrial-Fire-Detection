from tools.materialize_coco_calibration_subset import build


def test_build_filters_images_and_annotations_without_changing_metadata():
    source = {
        "info": {"name": "frozen"},
        "categories": [{"id": 1, "name": "fire"}],
        "images": [{"id": 1}, {"id": 2}, {"id": 3}],
        "annotations": [
            {"id": 10, "image_id": 1},
            {"id": 11, "image_id": 3},
        ],
    }
    result = build(source, {1, 2})
    assert result["info"] == source["info"]
    assert [row["id"] for row in result["images"]] == [1, 2]
    assert [row["id"] for row in result["annotations"]] == [10]


def test_build_rejects_unknown_image_id():
    try:
        build({"images": [{"id": 1}], "annotations": []}, {2})
    except ValueError as error:
        assert "absent" in str(error)
    else:
        raise AssertionError("unknown image ID was accepted")
