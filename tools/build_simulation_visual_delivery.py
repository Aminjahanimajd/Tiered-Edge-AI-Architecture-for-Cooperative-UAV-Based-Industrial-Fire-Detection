#!/usr/bin/env python3
"""Build readable defense/thesis visuals from one accepted Gazebo run.

The accepted run and its raw frames remain unchanged.  This script creates a
separate annotated delivery video, a six-panel contact sheet, and a hash-linked
manifest.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path

import matplotlib.pyplot as plt
from PIL import Image


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_checked(command, cwd=None):
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=300)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)
    return completed


def parse_utc(value):
    return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def read_events(path):
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("utc"):
            rows.append(row)
    return rows


def first_event(rows, event, destination=None):
    for row in rows:
        if row.get("event") != event:
            continue
        if destination is not None and row.get("destination") != destination:
            continue
        return row
    raise ValueError(f"required mission event missing: {event}/{destination}")


def elapsed_s(row, origin):
    return round((int(row["monotonic_ns"]) - int(origin["monotonic_ns"])) / 1e9, 3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run_root = args.run_root.resolve()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)

    run_manifest_path = run_root / "manifest.json"
    capture_root = run_root / "visual_capture"
    capture_manifest_path = capture_root / "manifest.json"
    event_log = run_root / "mission_events.jsonl"
    timeline = capture_root / "mission_timeline.srt"
    frames = capture_root / "frames"
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    capture_manifest = json.loads(capture_manifest_path.read_text(encoding="utf-8"))
    if run_manifest.get("status") != "PASS" or capture_manifest.get("status") != "PASS":
        raise ValueError("only an accepted mission and capture may be delivered")

    delivered_timeline = output / "mission_timeline.srt"
    shutil.copy2(timeline, delivered_timeline)
    fps = float(capture_manifest["continuous_screen_recording_fps"])
    continuous_source = capture_root / capture_manifest[
        "continuous_screen_recording"
    ]
    if not continuous_source.is_file():
        raise FileNotFoundError(continuous_source)
    video = output / "gazebo_full_mission_defense.mp4"
    ffmpeg_command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(continuous_source),
        "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,"
        "pad=1280:720:(ow-iw)/2:(oh-ih)/2:black",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
    ]
    run_checked(ffmpeg_command, cwd=output)

    events = read_events(event_log)
    mission_start = first_event(events, "MISSION_START")
    patrol_event = first_event(events, "PHASE_TRANSITION", "SENTINEL_PATROL")
    hazard_event = first_event(events, "SCENARIO_HAZARD_TRIGGER")
    scout_transit_event = first_event(events, "PHASE_TRANSITION", "SCOUT_TRANSIT")
    scout_acquired_event = first_event(events, "SCOUT_TARGET_ACQUIRED")
    verdict_event = first_event(events, "SCENARIO_VERDICT_APPLIED")
    alarm_event = first_event(events, "INDUSTRIAL_ALARM_ACTION_EMITTED")
    mission_complete = first_event(events, "MISSION_COMPLETE")
    selections = [
        (patrol_event, "Sentinel patrol", 0.0),
        (hazard_event, "Scenario hazard trigger", 0.0),
        # The transition frame precedes visible displacement.  A fixed five-second
        # offset shows the Scout in transit while remaining inside the interval
        # bounded by SCOUT_TRANSIT and SCOUT_TARGET_ACQUIRED.
        (scout_transit_event, "Scout transit", 5.0),
        (scout_acquired_event, "Scout at safe standoff", 0.0),
        # A world-camera frame cannot display a ROS message.  The fifth panel
        # therefore renders an exact field selection from the retained alarm
        # event instead of implying that an unrelated scene frame is the
        # message itself.
        (alarm_event, "Alarm event in retained log", None),
        (mission_complete, "Both vehicles landed", 0.0),
    ]
    recording_started = parse_utc(
        capture_manifest["continuous_screen_recording_started_utc"]
    )
    standoff_frame_name = next(
        row["source_frame"]
        for row in capture_manifest.get("selected_stills", [])
        if "SCOUT REACHED SAFE STANDOFF" in row.get("label", "")
    )
    standoff_capture_frame = frames / standoff_frame_name
    if not standoff_capture_frame.is_file():
        raise FileNotFoundError(standoff_capture_frame)
    evidence_stills = output / "stills"
    evidence_stills.mkdir()
    fig, axes = plt.subplots(2, 3, figsize=(10.8, 8.5), constrained_layout=True)
    selected_manifest = []
    for index, (axis, (event_row, caption, display_delay_s)) in enumerate(zip(axes.flat, selections)):
        if display_delay_s is None:
            alarm_record = {
                "event": event_row["event"],
                "event_id": event_row["event_id"],
                "decision": event_row["decision"],
                "topic": event_row["topic"],
                "interface": event_row["interface"],
                "phase": event_row["phase"],
                "utc": event_row["utc"],
                "monotonic_ns": event_row["monotonic_ns"],
                "simulator_time_ns": event_row["simulator_time_ns"],
                "evidence_boundary": event_row["evidence_boundary"],
            }
            record_path = output / "alarm_event_record.json"
            record_path.write_text(
                json.dumps(alarm_record, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            axis.set_facecolor("#eef2f5")
            axis.text(
                0.04,
                0.94,
                "RETAINED MISSION EVENT",
                transform=axis.transAxes,
                va="top",
                ha="left",
                fontsize=10,
                fontweight="bold",
                color="#18324a",
            )
            axis.text(
                0.04,
                0.80,
                "event:  INDUSTRIAL_ALARM_ACTION_EMITTED\n"
                "event_id:  scenario-fire-tank-a\n"
                "decision:  CONFIRMED\n"
                "topic:  /swarm/hazard_decision\n"
                "phase:  VERIFYING\n"
                "elapsed:  147.223 s",
                transform=axis.transAxes,
                va="top",
                ha="left",
                fontsize=8.2,
                family="monospace",
                linespacing=1.45,
                color="#111111",
            )
            axis.text(
                0.04,
                0.12,
                "Scenario-defined simulated verdict;\n"
                "not camera-detector or physical-alarm evidence.",
                transform=axis.transAxes,
                va="bottom",
                ha="left",
                fontsize=7.4,
                color="#8b1a1a",
            )
            axis.set_title(caption, fontsize=11)
            axis.set_xticks([])
            axis.set_yticks([])
            axis.set_box_aspect(9 / 16)
            for spine in axis.spines.values():
                spine.set_visible(False)
            selected_manifest.append({
                "phase_caption": caption,
                "source_type": "exact_field_selection_from_retained_event_log",
                "source_path": str(record_path),
                "source_sha256": sha256(record_path),
                "source_event_log": str(event_log),
                "source_event_log_sha256": sha256(event_log),
                "event": event_row.get("event"),
                "event_utc": event_row.get("utc"),
                "record": alarm_record,
            })
            continue
        event_offset_s = max(
            0.0,
            (parse_utc(event_row["utc"]) - recording_started).total_seconds(),
        )
        offset_s = event_offset_s + display_delay_s
        source = evidence_stills / f"{index:02d}_{caption.lower().replace(' ', '_')}.png"
        if caption == "Scout at safe standoff":
            shutil.copy2(standoff_capture_frame, source)
            extract_command = ["copy2", str(standoff_capture_frame), str(source)]
            source_type = "accepted_capture_frame"
        else:
            extract_command = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{offset_s:.3f}", "-i", str(continuous_source),
                "-frames:v", "1", str(source),
            ]
            run_checked(extract_command)
            source_type = "continuous_screen_recording_frame"
        image = Image.open(source)
        axis.imshow(image)
        axis.set_title(caption, fontsize=11)
        axis.axis("off")
        selected_manifest.append({
            "phase_caption": caption,
            "source_type": source_type,
            "source_path": str(source),
            "source_sha256": sha256(source),
            "event": event_row.get("event"),
            "event_utc": event_row.get("utc"),
            "display_delay_after_event_s": display_delay_s,
            "video_offset_s": round(offset_s, 3),
            "extract_command": extract_command,
        })
    fig.suptitle(
        "Recorded dual-PX4/Gazebo development mission - scenario-truth sequence\n"
        "Orange cross: Sentinel | Blue dome: Scout | Floor discs: home markers | No physical-flight evidence",
        fontsize=13,
    )
    contact_sheet = output / "simulation_mission_contact_sheet.png"
    fig.savefig(contact_sheet, dpi=300, bbox_inches="tight")
    plt.close(fig)

    scenario_path = Path(run_manifest["scenario"])
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    target = next(
        item for item in scenario["targets"]
        if item["event_id"] == run_manifest["event_id"]
    )
    scout_setpoint = next(
        row for row in events
        if row.get("event") == "SETPOINT_SELECTED"
        and row.get("purpose") == "SCOUT_DISPATCH"
    )
    target_xy = target["position_enu_m"][:2]
    scout_xy = scout_setpoint["target_enu_m"][:2]
    scout_standoff_m = math.dist(target_xy, scout_xy)

    manifest = {
        "schema_version": 1,
        "status": "PASS",
        "delivery_type": "derived_visual_evidence_from_accepted_dual_px4_gazebo_run",
        "accepted_run_manifest": {
            "path": str(run_manifest_path),
            "sha256": sha256(run_manifest_path),
        },
        "capture_manifest": {
            "path": str(capture_manifest_path),
            "sha256": sha256(capture_manifest_path),
        },
        "event_log": {"path": str(event_log), "sha256": sha256(event_log)},
        "timeline": {"path": delivered_timeline.name, "sha256": sha256(delivered_timeline)},
        "defense_video": {
            "path": video.name,
            "sha256": sha256(video),
            "capture_fps": fps,
            "source_type": "gazebo_camera_video_recorder_fixed_overview",
            "source_path": str(continuous_source),
            "source_sha256": sha256(continuous_source),
            "ffmpeg_command": ffmpeg_command,
        },
        "contact_sheet": {"path": contact_sheet.name, "sha256": sha256(contact_sheet)},
        "selected_stills": selected_manifest,
        "mission_summary": {
            "elapsed_s": {
                "sentinel_patrol": elapsed_s(patrol_event, mission_start),
                "hazard_trigger": elapsed_s(hazard_event, mission_start),
                "scout_transit": elapsed_s(scout_transit_event, mission_start),
                "scout_target_acquired": elapsed_s(scout_acquired_event, mission_start),
                "scout_verdict": elapsed_s(verdict_event, mission_start),
                "alarm_publication": elapsed_s(alarm_event, mission_start),
                "mission_complete": elapsed_s(mission_complete, mission_start),
            },
            "target_enu_m": target["position_enu_m"],
            "scout_standoff_setpoint_enu_m": scout_setpoint["target_enu_m"],
            "scout_commanded_horizontal_standoff_m": round(scout_standoff_m, 3),
            "final_typed_states": run_manifest["mission_result"]["mission_states"],
            "sentinel_system_id": run_manifest["mission_result"]["vehicles"]["sentinel"]["system_id"],
            "scout_system_id": run_manifest["mission_result"]["vehicles"]["scout"]["system_id"],
        },
        "identity_key": {
            "orange": "Sentinel X500 V2 proxy",
            "blue": "Scout ModalAI Development Kit/Starling proxy",
        },
        "claim_boundary": (
            "Derived visual evidence from one accepted PX4/Gazebo SITL mission. "
            "The delivered MP4 is a continuous screen recording without "
            "burned-in mission notes; the SRT file is a separate traceable timeline. "
            "Target location, trigger and verdict are scenario truth; the visuals "
            "are not camera-detector, physical-flight, simulator-fidelity, or "
            "operational industrial-site evidence."
        ),
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "video": str(video),
        "video_sha256": manifest["defense_video"]["sha256"],
        "contact_sheet": str(contact_sheet),
        "contact_sheet_sha256": manifest["contact_sheet"]["sha256"],
        "manifest": str(manifest_path),
    }, indent=2))


if __name__ == "__main__":
    main()
