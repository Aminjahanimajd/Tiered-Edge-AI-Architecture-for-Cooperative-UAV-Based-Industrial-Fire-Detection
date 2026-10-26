# Host tests

Run `python -m pytest tests -q` after installing `requirements-dev.txt` and the root package. Pytest collects both `unittest` classes and function-style tests; plain `unittest discover` does not collect all function-style tests.

Five checks explicitly skip when these private inputs are absent:

1. Complete candidate/converted-model artifact integrity in `test_audit_exact_device_screening_readiness.py`.
2. Historical external-data decode record in `test_audit_external_evaluation_readiness.py`.
3. Full archive contract validity in `test_validate_deployment_and_external_contracts.py`.
4. Native model-byte mismatch check in that same module.
5. Native calibration-manifest mismatch check in that same module.

The remaining contract checks, state/protocol tests, image decoding, duplicate/fault handling and synthetic analysis tests run without a drone, dataset or model weights. These skips preserve the original checks rather than weakening production readiness gates or inventing missing evidence. Restoring the private archive re-enables them.

SD-card recovery tests/tools are not part of this research-software release. The original development archive retains them.
