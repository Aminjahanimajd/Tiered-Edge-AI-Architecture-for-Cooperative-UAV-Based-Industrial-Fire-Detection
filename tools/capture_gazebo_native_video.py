#!/usr/bin/env python3
"""Capture scene-only Gazebo GUI frames and encode a traceable MP4."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def screenshot_request(directory, timeout_ms=5000):
    command = [
        "gz", "service", "-s", "/gui/screenshot",
        "--reqtype", "gz.msgs.StringMsg",
        "--reptype", "gz.msgs.Boolean",
        "--timeout", str(timeout_ms),
        "--req", 'data: "{}"'.format(Path(directory)),
    ]
    completed = subprocess.run(command, text=True, capture_output=True, timeout=10)
    passed = completed.returncode == 0 and "data: true" in completed.stdout
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "passed": passed,
    }


def wait_for_new_png(directory, known, timeout_s=5.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        current = set(Path(directory).glob("*.png"))
        added = sorted(current - known)
        if added:
            return added[0]
        time.sleep(0.05)
    raise TimeoutError("Gazebo accepted screenshot request but no PNG appeared")


def camera_follow(target, timeout_ms=5000):
    """Ask Gazebo's own camera plugin to follow one named scene model."""
    command = [
        "gz", "service", "-s", "/gui/follow",
        "--reqtype", "gz.msgs.StringMsg",
        "--reptype", "gz.msgs.Boolean",
        "--timeout", str(timeout_ms),
        "--req", 'data: "{}"'.format(str(target)),
    ]
    completed = subprocess.run(command, text=True, capture_output=True, timeout=10)
    return {
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "action": "follow",
        "target": str(target),
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "passed": completed.returncode == 0 and "data: true" in completed.stdout,
    }


def _x11_dimensions(display):
    completed = subprocess.run(
        ["xdpyinfo", "-display", display],
        text=True,
        capture_output=True,
        timeout=10,
    )
    match = re.search(r"dimensions:\s+(\d+)x(\d+)\s+pixels", completed.stdout)
    if completed.returncode != 0 or match is None:
        raise RuntimeError("could not determine the WSLg X11 display dimensions")
    width, height = (int(match.group(1)), int(match.group(2)))
    return width - width % 2, height - height % 2


def _windows_path(path):
    completed = subprocess.run(
        ["wslpath", "-w", str(Path(path).resolve())],
        text=True,
        capture_output=True,
        timeout=10,
    )
    if completed.returncode != 0:
        raise RuntimeError("wslpath failed: {}".format(completed.stderr))
    return completed.stdout.strip()


def _start_continuous_screen_recording(destination, stop_file, fps=15):
    """Start a native Windows recording scoped to the Gazebo window."""
    script = Path(__file__).with_name("capture_windows_window_video.py")
    command = [
        "python.exe", _windows_path(script),
        "--output", _windows_path(destination),
        "--stop-file", _windows_path(stop_file),
        "--fps", str(int(fps)),
        "--title-regex", "Gazebo|industrial_inspection",
        "--wait-s", "60",
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    ready = Path(destination).with_suffix(".ready.json")
    deadline = time.monotonic() + 65
    while time.monotonic() < deadline:
        if ready.is_file():
            geometry = json.loads(ready.read_text(encoding="utf-8"))
            return process, command, geometry
        if process.poll() is not None:
            raise RuntimeError(
                "Windows window recorder exited before ready: {}".format(
                    process.communicate()[1]
                )
            )
        time.sleep(0.1)
    process.terminate()
    raise TimeoutError("Windows window recorder did not become ready")


def _stop_continuous_screen_recording(process, stop_file, timeout_s=30):
    Path(stop_file).write_text("stop\n", encoding="utf-8")
    try:
        stderr = process.communicate(timeout=timeout_s)[1]
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            stderr = process.communicate(timeout=10)[1]
        except subprocess.TimeoutExpired:
            process.kill()
            stderr = process.communicate()[1]
    return process.returncode, stderr


def _start_gazebo_camera_recording(destination, service_timeout_s=60.0):
    """Start Gazebo's native CameraVideoRecorder overview stream."""
    service = "/defense_overview/record_video"
    deadline = time.monotonic() + float(service_timeout_s)
    request = 'start: true, format:"mp4", save_filename:"{}"'.format(
        Path(destination).resolve()
    )
    command = [
        "gz", "service", "-s", service,
        "--reqtype", "gz.msgs.VideoRecord",
        "--reptype", "gz.msgs.Boolean",
        "--timeout", "5000", "--req", request,
    ]
    attempts = []
    while time.monotonic() < deadline:
        completed = subprocess.run(
            command, text=True, capture_output=True, timeout=10
        )
        attempts.append({
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        })
        if completed.returncode == 0 and "data: true" in completed.stdout:
            return command, attempts, {"service": service, "fps": 15}
        time.sleep(0.5)
    raise TimeoutError("Gazebo camera-video recorder service was unavailable")


def _stop_gazebo_camera_recording(destination, timeout_s=30.0):
    command = [
        "gz", "service", "-s", "/defense_overview/record_video",
        "--reqtype", "gz.msgs.VideoRecord",
        "--reptype", "gz.msgs.Boolean",
        "--timeout", "5000", "--req", "stop: true",
    ]
    completed = subprocess.run(
        command, text=True, capture_output=True, timeout=10
    )
    deadline = time.monotonic() + float(timeout_s)
    destination = Path(destination)
    while time.monotonic() < deadline:
        if destination.is_file() and destination.stat().st_size > 1024:
            break
        time.sleep(0.2)
    passed = (
        completed.returncode == 0
        and "data: true" in completed.stdout
        and destination.is_file()
        and destination.stat().st_size > 1024
    )
    return passed, command, completed.stdout, completed.stderr


def _read_event_rows(event_log):
    path = Path(event_log)
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("utc"):
            rows.append(row)
    return rows


def _camera_target(rows):
    """Select the visually relevant vehicle without changing mission behavior."""
    phase = rows[-1].get("phase", "PREPARING") if rows else "PREPARING"
    if phase in {
        "SCOUT_PRIME", "SCOUT_TAKEOFF", "SCOUT_TRANSIT", "VERIFYING",
        "CONFIRMED_HOLD",
    }:
        return "modalai_devkit_scout_proxy_2"
    return "x500_v2_sentinel_proxy_1"


def _parse_utc(value):
    return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _srt_time(seconds):
    milliseconds = max(0, int(round(float(seconds) * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _event_label(row):
    event = row.get("event", "")
    if event == "PHASE_TRANSITION":
        return "MISSION PHASE: {}\n{}".format(
            row.get("destination", row.get("phase", "UNKNOWN")),
            row.get("reason", ""),
        )
    labels = {
        "MISSION_START": "PRE-FLIGHT: dual PX4 SITL mission initialized",
        "SCENARIO_HAZARD_TRIGGER": (
            "SCENARIO-DEFINED LOW-CONFIDENCE FIRE CANDIDATE\n"
            "Sentinel alert and target tracking start"
        ),
        "SIMULATED_TARGET_TRACKING_ACTIVE": (
            "SENTINEL TRACKING (SCENARIO TRUTH)\nScout dispatch in progress"
        ),
        "SCOUT_TARGET_ACQUIRED": (
            "SCOUT REACHED SAFE STANDOFF\nTarget acquisition uses scenario truth"
        ),
        "SIMULATED_TARGET_TRACKING_RELEASED": (
            "SCOUT HAS ACQUIRED TARGET\nSentinel resumes independent patrol"
        ),
        "SCENARIO_VERDICT_APPLIED": (
            "SCOUT VERDICT: {} (SCENARIO-DEFINED)".format(
                row.get("verdict", "UNKNOWN")
            )
        ),
        "INDUSTRIAL_ALARM_ACTION_EMITTED": (
            "CONFIRMED: HazardDecision published to alarm interface"
        ),
        "MISSION_COMPLETE": "MISSION COMPLETE: both vehicles landed and disarmed",
        "MISSION_FAIL": "MISSION FAILED: {}".format(row.get("reason", "unknown")),
    }
    return labels.get(event)


def _write_timeline_srt(event_log, capture_start, capture_end, destination):
    rows = _read_event_rows(event_log)
    markers = []
    for row in rows:
        label = _event_label(row)
        if label:
            relative = (_parse_utc(row["utc"]) - capture_start).total_seconds()
            markers.append((max(0.0, relative), label, row))
    if not markers:
        markers = [(0.0, "SIMULATION INITIALIZATION", {})]
    if markers[0][0] > 0:
        markers.insert(0, (0.0, "SIMULATION INITIALIZATION", {}))
    duration = max(0.1, (capture_end - capture_start).total_seconds())
    cues = []
    for index, (start, label, row) in enumerate(markers):
        stop = markers[index + 1][0] if index + 1 < len(markers) else duration
        stop = max(start + 0.1, min(duration, stop))
        text = (
            "PX4/Gazebo SITL - PROVISIONAL AIRFRAME PROXIES\n"
            "{}\n"
            "Scenario truth; not camera-detector or physical-flight evidence"
        ).format(label)
        cues.append((start, stop, text, row))
    lines = []
    for index, (start, stop, text, _) in enumerate(cues, 1):
        lines.extend([
            str(index),
            "{} --> {}".format(_srt_time(start), _srt_time(stop)),
            text,
            "",
        ])
    Path(destination).write_text("\n".join(lines), encoding="utf-8")
    return cues


def _encode_frames(frames, fps, destination, subtitle=None):
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-framerate", str(fps), "-i", str(Path(frames) / "frame_%06d.png"),
    ]
    filters = ["scale=trunc(iw/2)*2:trunc(ih/2)*2"]
    if subtitle is not None:
        filters.append(
            "subtitles={}:force_style='FontName=DejaVu Sans,FontSize=16,"
            "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,"
            "Alignment=2,MarginV=24'".format(Path(subtitle).name)
        )
    command.extend([
        "-vf", ",".join(filters), "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(destination),
    ])
    completed = subprocess.run(
        command,
        cwd=Path(destination).parent if subtitle is not None else None,
        text=True,
        capture_output=True,
        timeout=300,
    )
    if completed.returncode != 0 or not Path(destination).is_file():
        raise RuntimeError("FFmpeg encoding failed: {}".format(completed.stderr))
    return command, completed.stderr


def capture_until_stop(
    output, fps, stop_event, event_log, service_timeout_s=120.0,
    ready_event=None,
):
    """Capture a complete GUI mission until the orchestrator signals completion."""
    if fps <= 0:
        raise ValueError("fps must be positive")
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    frames = output / "frames"
    frames.mkdir(parents=True)
    started_dt = datetime.datetime.now(datetime.timezone.utc)
    deadline = time.monotonic() + float(service_timeout_s)
    records, actions = [], []
    screenshot_failures = []
    current_target = "fixed-wide-camera"
    interval = 1.0 / fps
    index = 0
    screen_video = output / "gazebo_continuous_overview.mp4"
    screen_native_directory = Path(
        "/home/sefroyek/drone_enhanced_sim/native_video_captures"
    )
    screen_native_directory.mkdir(parents=True, exist_ok=True)
    screen_native_video = screen_native_directory / (
        output.parent.name + "_gazebo_continuous_overview.mp4"
    )
    if screen_native_video.exists():
        raise FileExistsError(screen_native_video)
    screen_process = None
    screen_command = None
    screen_geometry = None
    screen_attempts = None
    screen_started_dt = None
    while not stop_event.is_set():
        iteration_start = time.monotonic()
        rows = _read_event_rows(event_log)
        known = set(frames.glob("*.png"))
        result = screenshot_request(frames)
        if not result["passed"]:
            if not records and time.monotonic() < deadline:
                time.sleep(0.5)
                continue
            # The GUI screenshot service can briefly disappear while the
            # render window is busy.  It is supplementary evidence only; the
            # Gazebo camera recorder must continue until mission completion.
            screenshot_failures.append({
                "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "returncode": result["returncode"],
                "stdout": result["stdout"],
                "stderr": result["stderr"],
            })
            stop_event.wait(min(interval, 0.5))
            continue
        image = wait_for_new_png(frames, known)
        index += 1
        sequential = frames / "frame_{:06d}.png".format(index)
        image.replace(sequential)
        records.append({
            "index": index,
            "captured_utc": datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat(),
            "camera_target": current_target,
            "source_filename": image.name,
            "path": sequential.name,
        })
        if ready_event is not None and not ready_event.is_set():
            ready_event.set()
        if screen_process is None:
            screen_command, screen_attempts, screen_geometry = (
                _start_gazebo_camera_recording(screen_native_video)
            )
            screen_started_dt = datetime.datetime.now(datetime.timezone.utc)
            screen_process = "gazebo-native-camera-recorder-active"
        remaining = interval - (time.monotonic() - iteration_start)
        if remaining > 0:
            stop_event.wait(remaining)
    if len(records) < 2:
        raise RuntimeError("fewer than two Gazebo frames were captured")

    if screen_process is None:
        raise RuntimeError("continuous screen recorder did not start")
    screen_passed, screen_stop_command, screen_stdout, screen_stderr = (
        _stop_gazebo_camera_recording(screen_native_video)
    )
    if not screen_passed:
        raise RuntimeError(
            "continuous screen recording failed: {}".format(screen_stderr)
        )
    shutil.copy2(screen_native_video, screen_video)
    if not screen_video.is_file() or screen_video.stat().st_size <= 1024:
        raise RuntimeError("finalized native Gazebo video copy is missing")

    completed_dt = datetime.datetime.now(datetime.timezone.utc)
    source_video = output / "gazebo_scene_only_full_mission.mp4"
    source_command, source_stderr = _encode_frames(
        frames, fps, source_video
    )
    timeline = output / "mission_timeline.srt"
    cues = _write_timeline_srt(
        event_log, started_dt, completed_dt, timeline
    )
    annotated_video = output / "gazebo_full_mission_annotated.mp4"
    annotated_command, annotated_stderr = _encode_frames(
        frames, fps, annotated_video, timeline
    )

    stills = output / "selected_stills"
    stills.mkdir()
    capture_times = [_parse_utc(row["captured_utc"]) for row in records]
    selected = []
    for cue_index, (start, _, label, _) in enumerate(cues):
        target_dt = started_dt + datetime.timedelta(seconds=start)
        nearest = min(
            range(len(capture_times)),
            key=lambda item: abs((capture_times[item] - target_dt).total_seconds()),
        )
        slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:48]
        destination = stills / "{:02d}_{}.png".format(cue_index, slug)
        shutil.copy2(frames / records[nearest]["path"], destination)
        selected.append({
            "label": label,
            "source_frame": records[nearest]["path"],
            "path": str(destination.relative_to(output)),
            "sha256": sha256(destination),
        })

    manifest = {
        "schema_version": 2,
        "status": "PASS",
        "capture_method": "Gazebo GUI /gui/screenshot until mission completion",
        "continuous_capture_method": (
            "Gazebo CameraVideoRecorder fixed overview camera at 15 fps"
        ),
        "started_utc": started_dt.isoformat(),
        "completed_utc": completed_dt.isoformat(),
        "capture_request_fps": fps,
        "captured_frame_count": len(records),
        "frames": [dict(row, sha256=sha256(frames / row["path"])) for row in records],
        "camera_actions": actions,
        "camera_policy": "fixed wide view; no automatic vehicle following",
        "continuous_screen_recording": screen_video.name,
        "continuous_screen_recording_started_utc": (
            screen_started_dt.isoformat() if screen_started_dt else None
        ),
        "continuous_screen_recording_sha256": sha256(screen_video),
        "continuous_screen_recording_native_path": str(screen_native_video),
        "continuous_screen_recording_native_sha256": sha256(screen_native_video),
        "continuous_screen_recording_fps": 15,
        "continuous_screen_recording_geometry": screen_geometry,
        "continuous_screen_recording_command": screen_command,
        "continuous_screen_recording_start_attempts": screen_attempts,
        "continuous_screen_recording_stop_command": screen_stop_command,
        "continuous_screen_recording_stop_stdout": screen_stdout,
        "continuous_screen_recording_stderr": screen_stderr,
        "screenshot_service_failure_count": len(screenshot_failures),
        "screenshot_service_failures": screenshot_failures,
        "event_log": str(Path(event_log)),
        "event_log_sha256": sha256(event_log) if Path(event_log).is_file() else None,
        "timeline_path": timeline.name,
        "timeline_sha256": sha256(timeline),
        "source_video": source_video.name,
        "source_video_sha256": sha256(source_video),
        "annotated_video": annotated_video.name,
        "annotated_video_sha256": sha256(annotated_video),
        "selected_stills": selected,
        "source_ffmpeg_command": source_command,
        "source_ffmpeg_stderr": source_stderr,
        "annotated_ffmpeg_command": annotated_command,
        "annotated_ffmpeg_stderr": annotated_stderr,
        "claim_boundary": (
            "Complete visual demonstration of one PX4/Gazebo SITL mission using "
            "provisional airframe proxies and scenario-defined target truth. The "
            "video is not camera-detector, physical-flight, industrial-site, or "
            "simulator-fidelity evidence."
        ),
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def run(output, frame_count, fps):
    if frame_count < 2:
        raise ValueError("frame_count must be at least 2")
    if fps <= 0:
        raise ValueError("fps must be positive")
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    frames = output / "frames"
    frames.mkdir(parents=True)
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    requests, captured = [], []
    interval = 1.0 / fps
    for index in range(frame_count):
        iteration_start = time.monotonic()
        known = set(frames.glob("*.png"))
        result = screenshot_request(frames)
        requests.append(result)
        if not result["passed"]:
            raise RuntimeError("Gazebo screenshot request failed at frame {}".format(index))
        image = wait_for_new_png(frames, known)
        captured.append(image)
        remaining = interval - (time.monotonic() - iteration_start)
        if remaining > 0 and index + 1 < frame_count:
            time.sleep(remaining)

    video = output / "gazebo_scene_only.mp4"
    ffmpeg = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-framerate", str(fps), "-pattern_type", "glob", "-i",
        str(frames / "*.png"), "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", str(video),
    ]
    encoded = subprocess.run(ffmpeg, text=True, capture_output=True, timeout=120)
    if encoded.returncode != 0 or not video.is_file():
        raise RuntimeError("FFmpeg encoding failed: {}".format(encoded.stderr))

    manifest = {
        "schema_version": 1,
        "capture_method": "repeated Gazebo GUI /gui/screenshot service frames",
        "started_utc": started,
        "completed_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "requested_frame_count": frame_count,
        "captured_frame_count": len(captured),
        "capture_request_fps": fps,
        "encoded_playback_fps": fps,
        "frame_sha256": [sha256(path) for path in captured],
        "video_path": video.name,
        "video_sha256": sha256(video),
        "video_bytes": video.stat().st_size,
        "request_pass_count": sum(item["passed"] for item in requests),
        "ffmpeg_command": ffmpeg,
        "ffmpeg_stderr": encoded.stderr,
        "status": "PASS",
        "claim_boundary": (
            "Scene-only visual method pilot; not a formal mission, detector, "
            "physical-flight, simulator-fidelity, or reliability result."
        ),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": "PASS", "output": str(output), "video": str(video)}, indent=2))
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frame-count", type=int, default=20)
    parser.add_argument("--fps", type=float, default=2.0)
    args = parser.parse_args()
    return 0 if run(args.output, args.frame_count, args.fps)["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
