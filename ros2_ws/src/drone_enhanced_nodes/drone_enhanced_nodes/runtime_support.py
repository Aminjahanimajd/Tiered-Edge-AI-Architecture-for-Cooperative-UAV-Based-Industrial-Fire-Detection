"""Shared device runtime utilities with hardware imports kept lazy."""

from __future__ import print_function

import hashlib
import json
import os
import time
import uuid

from drone_enhanced_core.inference import compute_resize_transform


def monotonic_ns():
    function = getattr(time, "monotonic_ns", None)
    if function is not None:
        return function()
    return int(time.monotonic() * 1000000000)


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while True:
            block = source.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def resolve_session_ids(formal_mode, experiment_id, trial_id):
    experiment_id = str(experiment_id).strip()
    trial_id = str(trial_id).strip()
    if formal_mode and (not experiment_id or not trial_id):
        raise ValueError("formal_mode requires explicit experiment_id and trial_id")
    if not experiment_id:
        experiment_id = "development"
    if not trial_id:
        trial_id = "uncontrolled"
    return experiment_id, trial_id


def create_session_directory(
    log_directory, experiment_id, trial_id, node_name, formal_mode
):
    """Use one immutable formal path or a unique development-run subfolder."""
    base = os.path.join(log_directory, experiment_id, trial_id, node_name)
    if formal_mode:
        path = base
        run_id = "formal"
    else:
        run_id = "run-{}".format(uuid.uuid4().hex[:12])
        path = os.path.join(base, run_id)
    if not os.path.isdir(path):
        os.makedirs(path)
    return path, run_id


def write_session_manifest(path, values):
    """Create, never overwrite, the configuration record for one node run."""
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        os.makedirs(parent)
    payload = dict(values)
    payload["manifest_written_utc"] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
    )
    with open(path, "x", encoding="utf-8") as output:
        json.dump(payload, output, indent=2, sort_keys=True)
        output.write("\n")


def build_gstreamer_yuy2_pipeline(device, width, height, fps):
    """Build the verified D435i YUY2-to-BGR low-latency capture pipeline."""
    device = str(device).strip()
    width = int(width)
    height = int(height)
    fps = int(fps)
    if not device.startswith("/dev/video"):
        raise ValueError("camera device must be an explicit /dev/video path")
    if min(width, height, fps) <= 0:
        raise ValueError("camera width, height, and fps must be positive")
    return (
        "v4l2src device={} ! "
        "video/x-raw, format=YUY2, width={}, height={}, framerate={}/1 ! "
        "videoconvert ! video/x-raw, format=BGR ! "
        "appsink drop=true max-buffers=1 sync=false"
    ).format(device, width, height, fps)


def prepare_bgr_frame(frame, model_width, model_height, resize_mode, layout):
    """Create normalized RGB FP32 input and return its geometry transform."""
    import cv2
    import numpy as np

    source_height, source_width = frame.shape[:2]
    transform = compute_resize_transform(
        source_width, source_height, model_width, model_height, resize_mode
    )
    if resize_mode == "stretch":
        resized = cv2.resize(frame, (model_width, model_height))
    else:
        resized_width = int(round(source_width * transform.scale_x))
        resized_height = int(round(source_height * transform.scale_y))
        resized_core = cv2.resize(frame, (resized_width, resized_height))
        top = int(round(transform.pad_y - 0.1))
        bottom = model_height - resized_height - top
        left = int(round(transform.pad_x - 0.1))
        right = model_width - resized_width - left
        resized = cv2.copyMakeBorder(
            resized_core,
            top,
            bottom,
            left,
            right,
            cv2.BORDER_CONSTANT,
            value=(114, 114, 114),
        )
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    tensor = rgb.astype(np.float32) / 255.0
    if layout == "NCHW":
        tensor = np.transpose(tensor, (2, 0, 1))[None, ...]
    elif layout == "NHWC":
        tensor = tensor[None, ...]
    else:
        raise ValueError("unsupported tensor layout: {}".format(layout))
    return np.ascontiguousarray(tensor), transform


def decode_ros_image_to_bgr(message, configured_yuv420_format="nv21"):
    """Decode a bounded set of ROS Image layouts with geometry validation."""
    import cv2
    import numpy as np

    raw = np.frombuffer(message.data, dtype=np.uint8)
    width = int(message.width)
    height = int(message.height)
    step = int(message.step)
    encoding = str(message.encoding).strip().lower()
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")

    if encoding in ("mono8", "8uc1") or raw.size == width * height:
        if raw.size != width * height:
            raise ValueError("mono8 payload length does not match image dimensions")
        if step not in (0, width):
            raise ValueError(
                "mono8 step {} does not match expected {}".format(step, width)
            )
        gray = raw.reshape((height, width))
        frame = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        decoded_as = (
            "mono8"
            if encoding in ("mono8", "8uc1")
            else "mono8_size_inferred"
        )
    elif encoding in ("nv12", "nv21") or raw.size == width * height * 3 // 2:
        if raw.size != width * height * 3 // 2:
            raise ValueError("YUV420 payload length does not match image dimensions")
        selected_format = encoding if encoding in ("nv12", "nv21") else str(
            configured_yuv420_format
        ).lower()
        if selected_format not in ("nv12", "nv21"):
            raise ValueError("configured YUV420 format must be nv12 or nv21")
        yuv = raw.reshape((height * 3 // 2, width))
        conversion = (
            cv2.COLOR_YUV2BGR_NV12
            if selected_format == "nv12"
            else cv2.COLOR_YUV2BGR_NV21
        )
        frame = cv2.cvtColor(yuv, conversion)
        decoded_as = selected_format
    elif encoding in ("yuv422", "uyvy", "yuyv", "yuy2") or raw.size == width * height * 2:
        if raw.size != width * height * 2:
            raise ValueError("YUV422 payload length does not match image dimensions")
        if step not in (0, width * 2):
            raise ValueError(
                "YUV422 step {} does not match expected {}".format(step, width * 2)
            )
        yuv = raw.reshape((height, width, 2))
        if encoding in ("yuyv", "yuy2"):
            frame = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_YUY2)
            decoded_as = "yuyv"
        else:
            frame = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_UYVY)
            decoded_as = "uyvy"
    elif encoding in ("rgb8", "bgr8") or raw.size == width * height * 3:
        if raw.size != width * height * 3:
            raise ValueError("three-channel payload length does not match dimensions")
        if step not in (0, width * 3):
            raise ValueError(
                "three-channel step {} does not match expected {}".format(
                    step, width * 3
                )
            )
        three_channel = raw.reshape((height, width, 3))
        if encoding == "rgb8":
            frame = cv2.cvtColor(three_channel, cv2.COLOR_RGB2BGR)
            decoded_as = "rgb8"
        else:
            frame = three_channel.copy()
            decoded_as = "bgr8" if encoding == "bgr8" else "three_channel_size_inferred"
    else:
        raise ValueError(
            "unsupported image buffer: {} bytes for {}x{} encoding {}".format(
                raw.size, width, height, encoding
            )
        )
    return frame, {
        "width": width,
        "height": height,
        "step": step,
        "encoding": encoding,
        "decoded_as": decoded_as,
        "data_length": int(raw.size),
    }
