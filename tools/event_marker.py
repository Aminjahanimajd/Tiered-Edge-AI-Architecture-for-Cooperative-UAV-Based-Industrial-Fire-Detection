#!/usr/bin/env python3
"""Interactive operator marker for controlled stationary fire trials."""

from __future__ import print_function

import argparse
import json
import sys

from drone_enhanced_core.ground_truth import GroundTruthRecorder, VALID_CONDITIONS


def audible_marker(enabled):
    if not enabled:
        return
    try:
        import winsound

        winsound.Beep(1200, 150)
    except (ImportError, RuntimeError):
        sys.stdout.write("\a")
        sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--trial-id", required=True)
    parser.add_argument("--condition", required=True, choices=sorted(VALID_CONDITIONS))
    parser.add_argument("--repetition", required=True, type=int)
    parser.add_argument("--audible-marker", action="store_true")
    parser.add_argument("--metadata-json", default="{}")
    arguments = parser.parse_args()
    metadata = json.loads(arguments.metadata_json)
    if not isinstance(metadata, dict):
        raise ValueError("--metadata-json must decode to an object")
    if arguments.repetition <= 0:
        raise ValueError("--repetition must be positive")
    metadata["repetition"] = arguments.repetition

    recorder = GroundTruthRecorder(
        arguments.output,
        arguments.experiment_id,
        arguments.trial_id,
        arguments.condition,
        metadata,
    )
    print("Marker active. Commands: s=start, e=end, n=note, c=correction, q=complete")
    try:
        while True:
            command = input("marker> ").strip().lower()
            try:
                if command == "s":
                    record = recorder.mark_visible_start()
                    audible_marker(arguments.audible_marker)
                elif command == "e":
                    record = recorder.mark_visible_end()
                    audible_marker(arguments.audible_marker)
                elif command == "n":
                    record = recorder.add_note(input("note> "))
                elif command == "c":
                    sequence = int(input("sequence to correct> "))
                    correction = input("correction> ")
                    reason = input("reason> ")
                    record = recorder.append_correction(sequence, correction, reason)
                elif command == "q":
                    record = recorder.complete(input("completion note (optional)> "))
                    print(json.dumps(record, sort_keys=True))
                    break
                else:
                    print("Unknown command")
                    continue
                print(json.dumps(record, sort_keys=True))
            except (RuntimeError, ValueError) as exc:
                print("Marker rejected command: {}".format(exc))
    except (KeyboardInterrupt, EOFError):
        recorder.abort("operator_interrupted_marker")
        print("\nTrial marked aborted; raw records were preserved.")


if __name__ == "__main__":
    main()
