"""Append-only operator ground-truth events for controlled stationary trials."""

from __future__ import print_function

import json
import os
import time
from datetime import datetime, timezone


VALID_CONDITIONS = {
    "fire",
    "empty_background",
    "displayed_fire_video",
    "orange_red_object",
    "direct_light_glare",
    "fog_cloud_visual",
    "reflective_surface",
    "other_negative",
}


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def monotonic_ns():
    function = getattr(time, "monotonic_ns", None)
    if function is not None:
        return function()
    return int(time.monotonic() * 1000000000)


class GroundTruthRecorder(object):
    """Write operator events durably while enforcing a valid marker sequence."""

    def __init__(self, path, experiment_id, trial_id, condition, metadata=None):
        self.path = os.path.abspath(path)
        self.experiment_id = self._require_id("experiment_id", experiment_id)
        self.trial_id = self._require_id("trial_id", trial_id)
        self.condition = str(condition).strip().lower()
        if self.condition not in VALID_CONDITIONS:
            raise ValueError("unsupported condition: {}".format(condition))
        parent = os.path.dirname(self.path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        self._output = open(self.path, "x", encoding="utf-8")
        self._sequence = 0
        self._visible = False
        self._completed = False
        self._write(
            "TRIAL_STARTED",
            {
                "condition": self.condition,
                "metadata": dict(metadata or {}),
            },
        )

    @staticmethod
    def _require_id(name, value):
        value = str(value).strip()
        if not value:
            raise ValueError("{} cannot be empty".format(name))
        return value

    @property
    def sequence(self):
        return self._sequence

    @property
    def visible(self):
        return self._visible

    def _write(self, event_type, values=None):
        if self._completed:
            raise RuntimeError("trial is already complete")
        self._sequence += 1
        record = {
            "schema_version": 1,
            "sequence": self._sequence,
            "event_type": str(event_type),
            "experiment_id": self.experiment_id,
            "trial_id": self.trial_id,
            "condition": self.condition,
            "wall_time_utc": utc_now_iso(),
            "monotonic_ns": monotonic_ns(),
        }
        record.update(values or {})
        self._output.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
        self._output.write("\n")
        self._output.flush()
        os.fsync(self._output.fileno())
        return dict(record)

    def mark_visible_start(self, note=""):
        if self.condition != "fire":
            raise RuntimeError("visibility markers are valid only for fire trials")
        if self._visible:
            raise RuntimeError("fire is already marked visible")
        record = self._write("HAZARD_VISIBLE_START", {"note": str(note)})
        self._visible = True
        return record

    def mark_visible_end(self, note=""):
        if not self._visible:
            raise RuntimeError("fire is not currently marked visible")
        record = self._write("HAZARD_VISIBLE_END", {"note": str(note)})
        self._visible = False
        return record

    def add_note(self, note):
        note = str(note).strip()
        if not note:
            raise ValueError("note cannot be empty")
        return self._write("OPERATOR_NOTE", {"note": note})

    def append_correction(self, corrected_sequence, correction, reason):
        corrected_sequence = int(corrected_sequence)
        if corrected_sequence <= 0 or corrected_sequence > self._sequence:
            raise ValueError("corrected_sequence must identify an earlier record")
        correction = str(correction).strip()
        reason = str(reason).strip()
        if not correction or not reason:
            raise ValueError("correction and reason cannot be empty")
        return self._write(
            "CORRECTION",
            {
                "corrected_sequence": corrected_sequence,
                "correction": correction,
                "reason": reason,
            },
        )

    def complete(self, note=""):
        if self._visible:
            raise RuntimeError("mark HAZARD_VISIBLE_END before completing the trial")
        record = self._write("TRIAL_COMPLETED", {"note": str(note)})
        self._completed = True
        self._output.close()
        return record

    def abort(self, reason):
        if self._completed:
            return
        self._visible = False
        self._write("TRIAL_ABORTED", {"reason": str(reason)})
        self._completed = True
        self._output.close()

    def close(self):
        if not self._completed:
            self.abort("recorder_closed_without_trial_completion")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None and not self._completed:
            self.abort("context_closed_without_explicit_completion")
        elif exc_type is not None and not self._completed:
            self.abort("exception: {}".format(exc_value))
