#!/usr/bin/env python3
"""Render claim-bounded visual aids from an immutable simulation run bundle."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


COLORS = {
    "PREFLIGHT": "#64748b",
    "TAKEOFF": "#2563eb",
    "PATROL": "#0891b2",
    "SUSPECT_HOLD": "#d97706",
    "SCOUT_DISPATCH": "#7c3aed",
    "VERIFYING": "#9333ea",
    "CONFIRMED_HOLD": "#dc2626",
    "REJECTED_RESUME": "#16a34a",
    "DEGRADED": "#e11d48",
    "RTL": "#0f766e",
    "LANDED": "#334155",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON on {path}:{line_number}: {exc}") from exc
    return records


def mission_transitions(records: list[dict]) -> dict[str, list[dict]]:
    result = {"sentinel": [], "scout": []}
    for record in records:
        vehicle = record.get("vehicle_id")
        if record.get("event") == "MISSION_STATE_TRANSITION" and vehicle in result:
            result[vehicle].append(record)
    return result


def _font(size: int, bold: bool = False):
    candidates = (
        Path("C:/Windows/Fonts/consolab.ttf" if bold else "C:/Windows/Fonts/consola.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def render_timeline(run_dir: Path, manifest: dict, records: list[dict], output: Path):
    image = Image.new("RGB", (1800, 1050), "#f8fafc")
    draw = ImageDraw.Draw(image)
    title_font, body_font, small_font = _font(34, True), _font(22), _font(17)
    run_id = run_dir.name
    draw.text((55, 35), "SIMULATION EVIDENCE — MISSION STATE TIMELINE", fill="#0f172a", font=title_font)
    draw.text((55, 86), f"Run: {run_id}", fill="#334155", font=body_font)
    draw.text(
        (55, 120),
        f"Fault: {manifest.get('injected_fault', 'none')}   Result: {manifest.get('status', 'UNKNOWN')}",
        fill="#334155",
        font=body_font,
    )
    transitions = mission_transitions(records)
    for row_index, vehicle in enumerate(("sentinel", "scout")):
        y = 245 + row_index * 270
        draw.text((55, y - 48), vehicle.upper(), fill="#0f172a", font=title_font)
        items = transitions[vehicle]
        width = max(145, int(1600 / max(1, len(items))))
        x = 55
        for item in items:
            state = str(item.get("destination_state", "UNKNOWN"))
            color = COLORS.get(state, "#475569")
            right = min(1745, x + width - 12)
            draw.rounded_rectangle((x, y, right, y + 92), radius=12, fill=color)
            label = "\n".join(textwrap.wrap(state, width=15))
            draw.multiline_text((x + 10, y + 12), label, fill="white", font=small_font, spacing=3)
            reason = str(item.get("reason", ""))
            draw.multiline_text(
                (x + 4, y + 105),
                "\n".join(textwrap.wrap(reason, width=max(15, width // 11)))[:130],
                fill="#475569",
                font=small_font,
                spacing=2,
            )
            x += width
    result = manifest.get("mission_result", {})
    draw.text((55, 805), "Terminal evidence", fill="#0f172a", font=title_font)
    y = 855
    for vehicle in ("sentinel", "scout"):
        row = result.get("vehicles", {}).get(vehicle, {})
        text = (
            f"{vehicle}: state={result.get('mission_states', {}).get(vehicle)}; "
            f"landed={row.get('landed')}; system_id={row.get('system_id')}; "
            f"final NED m={row.get('final_position_ned_m')}"
        )
        draw.text((55, y), text, fill="#334155", font=small_font)
        y += 34
    draw.text(
        (55, 980),
        "DERIVED FROM HASHED MACHINE-READABLE LOGS — NOT A GAZEBO GUI SCREENSHOT OR PHYSICAL-FLIGHT IMAGE",
        fill="#b91c1c",
        font=small_font,
    )
    image.save(output, optimize=True)


def render_terminal(run_dir: Path, manifest: dict, output: Path):
    image = Image.new("RGB", (1800, 1120), "#0b1020")
    draw = ImageDraw.Draw(image)
    title_font, body_font = _font(26, True), _font(17)
    draw.text((45, 30), "RENDERED TERMINAL TRANSCRIPT", fill="#93c5fd", font=title_font)
    draw.text((45, 72), f"Run: {run_dir.name}", fill="#cbd5e1", font=body_font)
    lines = []
    for name in ("mission.stdout.txt", "mission.stderr.txt"):
        path = run_dir / name
        if path.is_file():
            lines.append(f"--- {name} (SHA-256 {sha256(path)}) ---")
            lines.extend(path.read_text(encoding="utf-8", errors="replace").splitlines())
    wrapped = []
    for line in lines:
        wrapped.extend(textwrap.wrap(line, width=160, replace_whitespace=False) or [""])
    wrapped = wrapped[-50:]
    y = 115
    for line in wrapped:
        draw.text((45, y), line, fill="#e2e8f0", font=body_font)
        y += 19
    draw.text(
        (45, 1075),
        "DERIVED IMAGE; THE UTF-8 TRANSCRIPT AND RUN MANIFEST ARE THE AUTHORITATIVE RAW EVIDENCE",
        fill="#fca5a5",
        font=body_font,
    )
    image.save(output, optimize=True)


def render(run_dir: Path) -> dict:
    run_dir = run_dir.resolve()
    manifest_path = run_dir / "manifest.json"
    events_path = run_dir / "mission_events.jsonl"
    if not manifest_path.is_file() or not events_path.is_file():
        raise FileNotFoundError("run directory must contain manifest.json and mission_events.jsonl")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = load_jsonl(events_path)
    output_dir = run_dir / "visual_evidence"
    output_dir.mkdir(exist_ok=True)
    timeline = output_dir / "mission_state_timeline.png"
    terminal = output_dir / "rendered_terminal_transcript.png"
    render_timeline(run_dir, manifest, records, timeline)
    render_terminal(run_dir, manifest, terminal)
    result = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "classification": "derived_visual_evidence",
        "claim_boundary": "Derived from logs; not a Gazebo GUI capture, physical-flight image, or independent quantitative source.",
        "source": {
            "manifest": "../manifest.json",
            "manifest_sha256": sha256(manifest_path),
            "event_log": "../mission_events.jsonl",
            "event_log_sha256": sha256(events_path),
        },
        "outputs": {
            timeline.name: sha256(timeline),
            terminal.name: sha256(terminal),
        },
        "generator": {
            "path": "tools/render_simulation_evidence.py",
            "sha256": sha256(Path(__file__)),
            "command": ["python", "tools/render_simulation_evidence.py", "--run-dir", str(run_dir)],
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(render(args.run_dir), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
