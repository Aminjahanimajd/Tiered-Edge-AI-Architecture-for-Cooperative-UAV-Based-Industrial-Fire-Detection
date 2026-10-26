#!/usr/bin/env python3
"""Verify the published subset, without hardware, model inference or private inputs."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(relative):
    return json.loads((ROOT / relative).read_text(encoding='utf-8'))


def near(actual, expected, tolerance=1e-6):
    if not math.isclose(actual, expected, abs_tol=tolerance, rel_tol=0):
        raise ValueError(f'Numerical contract mismatch: {actual} != {expected}')


def verify():
    manifest = load('evidence/publication_manifest.json')
    for relative, expected in manifest['files'].items():
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT.resolve()):
            raise ValueError('Manifest path escapes repository')
        if not path.is_file():
            raise FileNotFoundError(relative)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError('Published artifact hash mismatch: ' + relative)

    model_root = 'artifacts/experiments/model_screening_v1/'
    with (ROOT / (model_root + 'validation_comparison_v1/consolidated_20260809/validation_model_comparison.csv')).open(newline='', encoding='utf-8') as stream:
        validation = list(csv.DictReader(stream))
    with (ROOT / (model_root + 'test_comparison_v1/consolidated_20260809/test_model_comparison.csv')).open(newline='', encoding='utf-8') as stream:
        test = list(csv.DictReader(stream))
    if len(validation) != 6 or len(test) != 6:
        raise ValueError('Expected all six candidates on both frozen splits')
    if {r['model_id'] for r in validation} != {r['model_id'] for r in test}:
        raise ValueError('Validation/test candidate identities differ')
    for row in validation:
        if int(row['image_count']) != 700:
            raise ValueError('Unexpected validation sample size')
    for row in test:
        if int(row['image_count']) != 733:
            raise ValueError('Unexpected test sample size')
    if min(validation, key=lambda r: float(r['ap50_95']))['model_id'] != 'efficientdet_lite0_320':
        raise ValueError('Validation ranking no longer matches the frozen finding')
    if max(test, key=lambda r: float(r['ap50_95']))['model_id'] != 'efficientdet_lite0_320':
        raise ValueError('Test ranking no longer matches the frozen finding')

    backend = load('artifacts/experiments/hardware_lab_20260803/derived/backend_comparison_r1/benchmark_analysis.json')
    near(backend['device_results']['sentinel']['summaries_ms']['pipeline_ms']['mean'], 58.151, 0.0005)
    near(backend['device_results']['scout']['summaries_ms']['pipeline_ms']['mean'], 999.431, 0.0005)
    service = load('artifacts/experiments/hardware_full_service_20260929/derived/full_service_summary.json')
    if service['sentinel']['inference_frames'] != 30426:
        raise ValueError('Unexpected endurance frame count')
    for device in ['sentinel', 'scout']:
        if service[device]['resources']['observed_duration_seconds'] < 1800:
            raise ValueError('Endurance window shorter than the stated duration')
    near(service['sentinel']['resources']['swap_growth_mib_first_to_last'], 0.921875)
    network = load('evidence/network/roundtrip_summary.json')
    if network['received_count'] != 1000 or network['requested_count'] != 1000:
        raise ValueError('Loaded-network count contract failed')
    near(network['rtt_ms']['p95'], 7.984, 0.0005)
    if network.get('one_way_latency_claim_permitted') is not False:
        raise ValueError('Round-trip evidence boundary changed')
    return {'status': 'PASS', 'hashed_files': len(manifest['files']), 'models': 6,
            'boundary': 'Bundled-file integrity and selected numerical transcription only; no hardware or inference rerun'}


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
