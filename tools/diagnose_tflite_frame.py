#!/usr/bin/env python3
"""Report raw YOLO class scores and decoded detections for one TFLite frame."""

from __future__ import print_function

import argparse
import json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model")
    parser.add_argument("image")
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    import cv2
    import numpy as np
    from drone_enhanced_core import decode_yolov8
    from drone_enhanced_nodes.backends import TFLiteBackend
    from drone_enhanced_nodes.runtime_support import prepare_bgr_frame

    frame = cv2.imread(args.image, cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError("image could not be read")
    backend = TFLiteBackend(args.model, args.threads)
    tensor, transform = prepare_bgr_frame(
        frame, backend.model_width, backend.model_height, "letterbox", backend.layout
    )
    output = backend.infer(tensor)
    matrix = np.asarray(output)[0]
    candidates = matrix.T if matrix.shape[0] == 7 else matrix
    scores = candidates[:, 4:7]
    names = ("fire", "smoke", "non_fire")
    top = []
    for flat_index in np.argsort(scores, axis=None)[-20:][::-1]:
        anchor, class_id = np.unravel_index(flat_index, scores.shape)
        top.append(
            {
                "anchor": int(anchor),
                "class_id": int(class_id),
                "class_name": names[int(class_id)],
                "score": float(scores[anchor, class_id]),
                "xywh": [float(value) for value in candidates[anchor, :4]],
            }
        )
    decoded = {}
    for coordinate_space in ("model_pixels", "normalized"):
        decoded[coordinate_space] = {}
        for threshold in (0.01, 0.05, 0.10, 0.25, 0.50):
            detections = decode_yolov8(
                output,
                names,
                transform,
                threshold,
                0.45,
                ("fire",),
                coordinate_space,
            )
            decoded[coordinate_space][str(threshold)] = [
                dict(item._asdict()) for item in detections[:20]
            ]
    result = {
        "status": "PASS",
        "model": args.model,
        "image": args.image,
        "input_shape": [int(value) for value in tensor.shape],
        "output_shape": [int(value) for value in output.shape],
        "class_names_assumed": list(names),
        "per_channel_max": {
            names[index]: float(np.max(scores[:, index])) for index in range(3)
        },
        "per_channel_argmax_anchor": {
            names[index]: int(np.argmax(scores[:, index])) for index in range(3)
        },
        "top_raw_scores": top,
        "decoded_fire_by_coordinate_space_and_threshold": decoded,
        "preprocessed_min": float(np.min(tensor)),
        "preprocessed_max": float(np.max(tensor)),
        "preprocessed_mean": float(np.mean(tensor)),
    }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
