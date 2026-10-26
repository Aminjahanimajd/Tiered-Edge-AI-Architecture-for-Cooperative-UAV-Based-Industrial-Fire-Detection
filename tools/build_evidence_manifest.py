#!/usr/bin/env python3
"""Create a deterministic SHA-256 manifest without modifying raw evidence."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.rstrip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--label", default="20260804")
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()

    repo = args.repo.resolve()
    output = args.output_directory.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / f"evidence_manifest_{args.label}.csv"
    summary_path = output / f"evidence_freeze_{args.label}.json"

    rows: list[dict[str, object]] = []
    missing: list[str] = []
    for item in args.paths:
        evidence_root = (repo / item).resolve()
        if not evidence_root.exists():
            missing.append(item)
            continue
        candidates = [evidence_root] if evidence_root.is_file() else evidence_root.rglob("*")
        for path in sorted((p for p in candidates if p.is_file()), key=lambda p: p.as_posix()):
            stat = path.stat()
            rows.append(
                {
                    "evidence_root": item.replace("\\", "/"),
                    "relative_path": path.relative_to(repo).as_posix(),
                    "bytes": stat.st_size,
                    "modified_utc": dt.datetime.fromtimestamp(
                        stat.st_mtime, tz=dt.timezone.utc
                    ).isoformat(),
                    "sha256": sha256(path),
                }
            )

    with manifest_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["evidence_root", "relative_path", "bytes", "modified_utc", "sha256"],
        )
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "schema_version": 1,
        "access_class": "NO LAB",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "repository": str(repo),
        "git_branch": git(repo, "branch", "--show-current"),
        "git_head_before_checkpoint": git(repo, "rev-parse", "HEAD"),
        "git_status_before_checkpoint": git(repo, "status", "--short"),
        "evidence_roots": args.paths,
        "missing_roots": missing,
        "file_count": len(rows),
        "total_bytes": sum(int(row["bytes"]) for row in rows),
        "manifest": manifest_path.name,
        "manifest_sha256": sha256(manifest_path),
        "raw_evidence_modified": False,
        "acceptance": {
            "passed": not missing and bool(rows),
            "criterion": "Every file under each declared evidence root is listed with size, UTC mtime, and SHA-256.",
        },
        "limitations": [
            "The manifest proves file identity, not the scientific validity of the file contents.",
            "Large raw artifacts remain outside Git and must be preserved with the project archive.",
        ],
    }
    with summary_path.open("w", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, sort_keys=True)
        stream.write("\n")

    print(json.dumps({
        "manifest": str(manifest_path),
        "summary": str(summary_path),
        "files": len(rows),
        "bytes": summary["total_bytes"],
        "manifest_sha256": summary["manifest_sha256"],
        "passed": summary["acceptance"]["passed"],
    }, indent=2))


if __name__ == "__main__":
    main()
