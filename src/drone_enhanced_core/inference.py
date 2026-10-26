"""Hardware-independent image geometry, YOLO decoding, and non-max suppression.

The functions in this module intentionally avoid NumPy so they can be unit
tested on the development host.  Device adapters may pass NumPy arrays because
the decoder only relies on ``shape``-like nesting and numeric indexing.
"""

from __future__ import print_function

import math
from typing import NamedTuple


class ResizeTransform(NamedTuple):
    source_width: int
    source_height: int
    model_width: int
    model_height: int
    scale_x: float
    scale_y: float
    pad_x: float
    pad_y: float
    mode: str


class Detection(NamedTuple):
    class_id: int
    class_name: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def center_u(self):
        return (self.x1 + self.x2) * 0.5

    @property
    def center_v(self):
        return (self.y1 + self.y2) * 0.5


def compute_resize_transform(
    source_width, source_height, model_width, model_height, mode="letterbox"
):
    """Return the exact geometry needed to map detections to source pixels."""
    source_width = int(source_width)
    source_height = int(source_height)
    model_width = int(model_width)
    model_height = int(model_height)
    mode = str(mode).lower()
    if min(source_width, source_height, model_width, model_height) <= 0:
        raise ValueError("all image dimensions must be positive")
    if mode == "stretch":
        return ResizeTransform(
            source_width,
            source_height,
            model_width,
            model_height,
            float(model_width) / source_width,
            float(model_height) / source_height,
            0.0,
            0.0,
            mode,
        )
    if mode != "letterbox":
        raise ValueError("resize mode must be 'letterbox' or 'stretch'")
    scale = min(
        float(model_width) / source_width,
        float(model_height) / source_height,
    )
    resized_width = int(round(source_width * scale))
    resized_height = int(round(source_height * scale))
    return ResizeTransform(
        source_width,
        source_height,
        model_width,
        model_height,
        scale,
        scale,
        (model_width - resized_width) / 2.0,
        (model_height - resized_height) / 2.0,
        mode,
    )


def _clamp(value, low, high):
    return min(max(float(value), low), high)


def model_xywh_to_normalized_xyxy(x, y, width, height, transform):
    """Undo resize/padding and return a box normalized to the source frame."""
    x1 = (float(x) - float(width) * 0.5 - transform.pad_x) / transform.scale_x
    y1 = (float(y) - float(height) * 0.5 - transform.pad_y) / transform.scale_y
    x2 = (float(x) + float(width) * 0.5 - transform.pad_x) / transform.scale_x
    y2 = (float(y) + float(height) * 0.5 - transform.pad_y) / transform.scale_y
    x1 = _clamp(x1 / transform.source_width, 0.0, 1.0)
    y1 = _clamp(y1 / transform.source_height, 0.0, 1.0)
    x2 = _clamp(x2 / transform.source_width, 0.0, 1.0)
    y2 = _clamp(y2 / transform.source_height, 0.0, 1.0)
    return x1, y1, x2, y2


def _matrix_from_output(output, expected_channels=None):
    """Return ``(matrix, channel_first)`` for [1,C,N], [C,N], or [N,C]."""
    shape = tuple(int(value) for value in getattr(output, "shape", ()))
    if shape:
        if len(shape) == 3 and shape[0] == 1:
            output = output[0]
            shape = shape[1:]
        if len(shape) != 2 or min(shape) <= 0:
            raise ValueError("YOLO output must have shape [1,C,N], [C,N], or [N,C]")
        rows, columns = shape
    else:
        if not isinstance(output, (list, tuple)) or not output:
            raise ValueError("YOLO output must be a non-empty sequence")
        if len(output) == 1 and isinstance(output[0], (list, tuple)):
            first = output[0]
            if first and isinstance(first[0], (list, tuple)):
                output = first
        if not output or not isinstance(output[0], (list, tuple)):
            raise ValueError("YOLO output must be a two-dimensional matrix")
        row_length = len(output[0])
        if row_length == 0 or any(len(row) != row_length for row in output):
            raise ValueError("YOLO output rows must have equal non-zero length")
        rows = len(output)
        columns = row_length
    if expected_channels is not None:
        expected_channels = int(expected_channels)
        if rows == expected_channels:
            return output, True
        if columns == expected_channels:
            return output, False
    if rows <= 128 and columns > rows:
        return output, True
    if columns <= 128 and rows > columns:
        return output, False
    raise ValueError("cannot infer YOLO output layout from {}x{}".format(rows, columns))


def _candidate(matrix, channel_first, anchor_index, channel_index):
    if channel_first:
        return float(matrix[channel_index][anchor_index])
    return float(matrix[anchor_index][channel_index])


def _decode_yolov8_numpy(
    output,
    class_names,
    transform,
    confidence_threshold,
    iou_threshold,
    allowed,
    output_coordinate_space,
    np,
):
    """Vectorized candidate filtering for real NumPy device outputs."""
    matrix = np.asarray(output)
    if matrix.ndim == 3 and matrix.shape[0] == 1:
        matrix = matrix[0]
    if matrix.ndim != 2 or min(matrix.shape) <= 0:
        raise ValueError("YOLO output must have shape [1,C,N], [C,N], or [N,C]")
    expected_channels = 4 + len(class_names)
    if matrix.shape[0] == expected_channels:
        candidates = matrix.transpose()
    elif matrix.shape[1] == expected_channels:
        candidates = matrix
    else:
        raise ValueError(
            "output has shape {} but {} channels were expected".format(
                tuple(int(value) for value in matrix.shape), expected_channels
            )
        )

    scores = candidates[:, 4:]
    class_ids = np.argmax(scores, axis=1)
    confidences = scores[np.arange(scores.shape[0]), class_ids]
    mask = np.isfinite(confidences) & (confidences >= confidence_threshold)
    if allowed is not None:
        allowed_ids = [
            index for index, name in enumerate(class_names) if name in allowed
        ]
        if not allowed_ids:
            return []
        class_allowed = np.zeros(len(class_names), dtype=np.bool_)
        class_allowed[allowed_ids] = True
        mask &= class_allowed[class_ids]

    coordinates = candidates[:, :4]
    mask &= np.all(np.isfinite(coordinates), axis=1)
    selected = np.nonzero(mask)[0]
    if selected.size == 0:
        return []

    coordinates = coordinates[selected]
    if output_coordinate_space == "normalized":
        coordinates = coordinates.copy()
        coordinates[:, (0, 2)] *= transform.model_width
        coordinates[:, (1, 3)] *= transform.model_height
    selected_class_ids = class_ids[selected]
    selected_confidences = confidences[selected]
    x_values = coordinates[:, 0]
    y_values = coordinates[:, 1]
    widths = coordinates[:, 2]
    heights = coordinates[:, 3]
    x1 = (x_values - widths * 0.5 - transform.pad_x) / transform.scale_x
    y1 = (y_values - heights * 0.5 - transform.pad_y) / transform.scale_y
    x2 = (x_values + widths * 0.5 - transform.pad_x) / transform.scale_x
    y2 = (y_values + heights * 0.5 - transform.pad_y) / transform.scale_y
    x1 = np.clip(x1 / transform.source_width, 0.0, 1.0)
    y1 = np.clip(y1 / transform.source_height, 0.0, 1.0)
    x2 = np.clip(x2 / transform.source_width, 0.0, 1.0)
    y2 = np.clip(y2 / transform.source_height, 0.0, 1.0)
    valid = (x2 > x1) & (y2 > y1)

    decoded = []
    for position in np.nonzero(valid)[0]:
        class_id = int(selected_class_ids[position])
        decoded.append(
            Detection(
                class_id,
                class_names[class_id],
                float(selected_confidences[position]),
                float(x1[position]),
                float(y1[position]),
                float(x2[position]),
                float(y2[position]),
            )
        )
    return non_max_suppression(decoded, iou_threshold)


def box_iou(first, second):
    intersection_width = max(0.0, min(first.x2, second.x2) - max(first.x1, second.x1))
    intersection_height = max(0.0, min(first.y2, second.y2) - max(first.y1, second.y1))
    intersection = intersection_width * intersection_height
    first_area = max(0.0, first.x2 - first.x1) * max(0.0, first.y2 - first.y1)
    second_area = max(0.0, second.x2 - second.x1) * max(0.0, second.y2 - second.y1)
    union = first_area + second_area - intersection
    return 0.0 if union <= 0.0 else intersection / union


def non_max_suppression(detections, iou_threshold):
    """Apply class-aware greedy NMS to normalized detections."""
    iou_threshold = float(iou_threshold)
    if not 0.0 <= iou_threshold <= 1.0:
        raise ValueError("iou_threshold must be in [0, 1]")
    pending = sorted(detections, key=lambda item: item.confidence, reverse=True)
    kept = []
    while pending:
        selected = pending.pop(0)
        kept.append(selected)
        pending = [
            candidate
            for candidate in pending
            if candidate.class_id != selected.class_id
            or box_iou(selected, candidate) <= iou_threshold
        ]
    return kept


def decode_yolov8(
    output,
    class_names,
    transform,
    confidence_threshold,
    iou_threshold=0.45,
    allowed_class_names=None,
    output_coordinate_space="model_pixels",
):
    """Decode Ultralytics YOLOv8 detect output with no objectness channel.

    Supported layouts are ``[1, 4 + classes, anchors]`` and
    ``[anchors, 4 + classes]``. ``output_coordinate_space`` must explicitly
    identify whether output ``xywh`` values are model-input pixels or values
    normalized to the model input. Coordinates are returned normalized to the
    original source image after undoing stretch or letterbox geometry.
    """
    confidence_threshold = float(confidence_threshold)
    if not 0.0 <= confidence_threshold <= 1.0:
        raise ValueError("confidence_threshold must be in [0, 1]")
    class_names = tuple(str(name) for name in class_names)
    if not class_names:
        raise ValueError("class_names cannot be empty")
    allowed = None if allowed_class_names is None else set(allowed_class_names)
    output_coordinate_space = str(output_coordinate_space).strip().lower()
    if output_coordinate_space not in ("model_pixels", "normalized"):
        raise ValueError(
            "output_coordinate_space must be 'model_pixels' or 'normalized'"
        )
    try:
        import numpy as np
    except ImportError:
        np = None
    if np is not None and isinstance(output, np.ndarray):
        return _decode_yolov8_numpy(
            output,
            class_names,
            transform,
            confidence_threshold,
            iou_threshold,
            allowed,
            output_coordinate_space,
            np,
        )
    matrix, channel_first = _matrix_from_output(output, 4 + len(class_names))
    channels = len(matrix) if channel_first else len(matrix[0])
    anchors = len(matrix[0]) if channel_first else len(matrix)
    if channels != 4 + len(class_names):
        raise ValueError(
            "output has {} channels but {} were expected".format(
                channels, 4 + len(class_names)
            )
        )

    decoded = []
    for anchor in range(anchors):
        scores = [
            _candidate(matrix, channel_first, anchor, 4 + index)
            for index in range(len(class_names))
        ]
        class_id = max(range(len(scores)), key=lambda index: scores[index])
        confidence = scores[class_id]
        if not math.isfinite(confidence) or confidence < confidence_threshold:
            continue
        class_name = class_names[class_id]
        if allowed is not None and class_name not in allowed:
            continue
        coordinates = [
            _candidate(matrix, channel_first, anchor, index) for index in range(4)
        ]
        if not all(math.isfinite(value) for value in coordinates):
            continue
        if output_coordinate_space == "normalized":
            coordinates = [
                coordinates[0] * transform.model_width,
                coordinates[1] * transform.model_height,
                coordinates[2] * transform.model_width,
                coordinates[3] * transform.model_height,
            ]
        x1, y1, x2, y2 = model_xywh_to_normalized_xyxy(
            coordinates[0], coordinates[1], coordinates[2], coordinates[3], transform
        )
        if x2 <= x1 or y2 <= y1:
            continue
        decoded.append(
            Detection(class_id, class_name, confidence, x1, y1, x2, y2)
        )
    return non_max_suppression(decoded, iou_threshold)
