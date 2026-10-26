import json

from tools.render_simulation_evidence import load_jsonl, mission_transitions


def test_transition_extraction_keeps_vehicle_tracks_separate(tmp_path):
    path = tmp_path / "events.jsonl"
    rows = [
        {"event": "MISSION_STATE_TRANSITION", "vehicle_id": "sentinel", "destination_state": "PATROL"},
        {"event": "UNVERIFIED_HAZARD_RECORD", "vehicle_id": "sentinel"},
        {"event": "MISSION_STATE_TRANSITION", "vehicle_id": "scout", "destination_state": "DEGRADED"},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    tracks = mission_transitions(load_jsonl(path))
    assert [row["destination_state"] for row in tracks["sentinel"]] == ["PATROL"]
    assert [row["destination_state"] for row in tracks["scout"]] == ["DEGRADED"]
