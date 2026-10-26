# M3 Iterative Source-Family Regrouping

**Work date:** 29 July 2026  
**Status:** substantial leakage reduction; version 9 is the current grouping
checkpoint, version 10 is its annotation-adjudicated derivative, and the
refreshed 97-pair version-9 visual queue remains unlabelled

## Objective and evidence policy

I used the confirmed same-scene relationships from the perceptual audit to
improve the provisional fire-only split without changing raw images, labels, or
record identity. Every revision was written to a new processed directory. I
repeated the complete exact/dHash audit after each reassignment and did not
select a version only because it had a smaller dHash count.

Difference-hash pairs are candidates, not duplicate labels. Visual-review
decisions were stored in source-controlled manifests tied to the exact queue
SHA-256. Whole groups were reassigned with seed `20260729`; individual images
were never moved independently of their assigned group.

## Root-cause finding

The first filename rule was simultaneously over- and under-conservative. It
placed 9,276 records beginning with a simple `IMG...` pattern into one group,
but left other `IMG...` variants and families such as `HouseFour`,
`HouseFive`, `fireNframe`, and repeated weather scenes in separate groups.
Consequently, visibly related images could still cross provisional splits.

I introduced a conservative source-family rule for base images:

1. remove the Roboflow augmentation hash from the filename;
2. place all source IDs beginning with `IMG_` or `IMG-` into one capture-family
   group; and
3. for other base images, replace every digit run with `#`, so numbered frames
   sharing the same textual signature stay together.

For negative images, I retained the existing provenance/hash groups and added
only manually reviewed must-link edges. This avoids assuming that every image
from one weather category is the same scene.

The broad `IMG` rule is deliberately conservative. It may group independent
scenes and therefore reduce effective source diversity. It is safer against
leakage than treating unknown sequential captures as independent, but original
capture-session provenance is still preferable.

## Iterative results

All versions contain the same 23,220 record IDs. Every complete audit decoded
all images, found 250 exact duplicate sets, and found zero exact cross-split
sets.

| Version | Grouping intervention | Groups | Cross-group dHash pairs | Cross-split dHash pairs | Completed visual queue |
|---|---|---:|---:|---:|---|
| v1 | Initial filename groups | 5,117 | 5,649 | 1,701 | 69 same, 28 not visibly same, 1 uncertain (98 total) |
| v2 | v1 reviewed must-links only | 5,050 | 5,265 | 1,468 | 69 same, 29 not visibly same, 1 uncertain (99 total) |
| v3 | Digit-normalized source families, unified `IMG`, v1-v2 links | 2,693 | 1,330 | 884 | 49 same, 47 not visibly same (96 total) |
| v4 | v3 plus reviewed v3 links | 2,669 | 1,269 | 810 | 23 same, 75 not visibly same (98 total) |
| v5 | v4 plus reviewed v4 links | 2,652 | 1,242 | 816 | 4 same, 94 not visibly same (98 total) |
| v6 | v5 plus reviewed v5 links | 2,648 | 1,238 | 801 | 8 same, 90 not visibly same (98 total) |
| v7 | v6 plus reviewed v6 links | 2,640 | 1,230 | 813 | 6 same, 92 not visibly same (98 total) |
| v8 | v7 plus reviewed v7 links | 2,634 | 1,218 | 714 | 3 same, 94 not visibly same (97 total) |
| v9 | v8 plus reviewed v8 links | 2,631 | 1,214 | 704 | **Not complete** (97 queued) |

From v1 to v9, cross-group dHash candidates decreased by 78.5%, and
cross-split candidates decreased by 58.6%. Versions 5 and 7 temporarily had
more cross-split candidates than their predecessors because whole-component
reassignment changes which low-texture false matches cross a boundary. This
non-monotonic result confirms that the dHash count must not be treated as an
optimization objective or a confirmed-leakage count.

The completed, deliberately enriched visual queues found 69, 69, 49, 23, 4,
8, 6, and 3 same-scene pairs in versions 1 through 8. These counts are not
prevalence estimates because each queue contains the 60 highest scores plus
stratified quantiles. The increase from four to eight in version 6 is not a
regression measure: reassignment changes which candidate pairs enter the
enriched queue.

## Version-9 checkpoint

Version 9 contains:

- 16,151 training records: 14,303 fire-positive and 1,848 background;
- 3,537 validation records: 3,143 fire-positive and 394 background; and
- 3,532 test records: 3,138 fire-positive and 394 background.

Its record-manifest SHA-256 is
`62de12ee1cecf0f2477651c0bb43259485b64e8c137a42c9d605e8bd52291e86`.
Its complete dHash report SHA-256 is
`86b08ea5fcb3293f3eaf000e0cefed3327c0e032a9c9e04be189a3ad9ca6335a`.
Its stronger-metric report SHA-256 is
`baf22bf5f192e9c2d856bdd08c0a0445bafb4cd7f1f3e48b7aeb1100216ce4e3`.
Its unlabelled 97-pair queue SHA-256 is
`b163c976472f2c33c5876220450acd521b2394d0f8f0c062ab8eb8b55ec30fd2`.

I generated the version-9 contact sheets, but I did not inspect and save labels
for all 97 rows. Version 9 therefore remains
provisional and must not be used for final training or described as
leakage-free.

The complete version-9 audit decoded all 23,220 images, found no corrupt or
unreadable files, found 250 exact duplicate sets, and found zero exact
cross-split duplicate sets. It screened 1,214 cross-group pairs at mirror-
invariant dHash distance at most two, of which 704 cross a split. Stronger
continuous metrics found no normalized pixel-identical cross-split pair. These
are screening results, not proof that all 704 pairs have independent source
provenance.

The annotation audit subsequently created version 10 by excluding six reviewed
records and filtering boxes in four records. It preserved the version-9 group
assignments and reduced the manifest to 23,214 records. A complete repeated
duplicate scan reproduced 1,214 cross-group and 704 cross-split dHash
candidates, zero corrupt images, and zero exact cross-split duplicate sets. The
version-10 manifest SHA-256 is
`fd14d2b42d82181ba8d093e26e8df7b51e52a92a4366349cc3b6950691d06292`.
This annotation-only revision does not satisfy the unfinished version-9 visual
queue gate.

During version-7 auditing, I first exported no near-pair examples by passing
`--maximum-examples 0`; the stronger-metric tool correctly rejected that report
as truncated. A corrected rerun then correctly refused to overwrite the first
derived file because outputs use exclusive creation. I preserved both and
wrote the complete 1,230-row export as `duplicate_audit_complete.json`. These
recoverable command errors changed neither the manifest nor raw data.

## Reproduction pattern

The source-family revisions are regenerated from immutable v1 records and the
accumulated reviewed decision CSVs. For version 9, the command pattern is:

```powershell
<python> tools/build_source_family_manifest.py artifacts/processed/fire_only_grouped_manifest_v1/records.jsonl --review-decisions artifacts/processed/fire_only_grouped_manifest_v1/manual_review_decisions.csv --review-decisions artifacts/processed/fire_only_grouped_manifest_v2/manual_review_decisions.csv --review-decisions artifacts/processed/fire_only_source_family_manifest_v3/manual_review_decisions.csv --review-decisions artifacts/processed/fire_only_source_family_manifest_v4/manual_review_decisions.csv --review-decisions artifacts/processed/fire_only_source_family_manifest_v5/manual_review_decisions.csv --review-decisions artifacts/processed/fire_only_source_family_manifest_v6/manual_review_decisions.csv --review-decisions artifacts/processed/fire_only_source_family_manifest_v7/manual_review_decisions.csv --review-decisions artifacts/processed/fire_only_source_family_manifest_v8/manual_review_decisions.csv --output-directory artifacts/processed/fire_only_source_family_manifest_v9 --dataset-id fire_only_source_family_manifest_v9 --seed 20260729
```

The same complete `audit_manifest_duplicates.py` and
`refine_perceptual_duplicates.py` commands documented for version 1 are then
run against the new `records.jsonl`. All derived directories use exclusive
creation.

## Required next decision

Before any controlled YOLOv8n/YOLOv8s training comparison, I must:

1. complete and hash all 97 version-9 visual decisions;
2. merge any remaining visibly same-scene or uncertain edges conservatively;
3. repeat the complete exact, dHash, stronger-metric, and visual audits;
4. resolve or formally accept the effective-diversity cost of the 12,842-record
   broad `IMG` family;
5. perform the separate annotation-format and label-quality audit; and
6. freeze the test split only after these gates pass.

## Claim boundary and thesis placement

- **Methodology:** iterative source-family inference, reviewed must-links,
  whole-group reassignment, immutable versioning, and repeated auditing.
- **Results:** the version table, record counts, hashes, and descriptive
  reductions above.
- **Discussion:** source filenames were insufficient provenance; conservative
  grouping substantially reduced reviewed leakage but has not established
  independent provenance for every remaining candidate.
- **Limitations:** digit-normalized families can overgroup; visual review is
  single-reviewer and enriched; dHash has many low-texture false matches;
  version 9 is incomplete.
- **Appendix:** source-family crosswalks, manifests, audit reports, contact
  sheets, decisions, commands, and hashes.

## Superseding curated-dataset decision

The open version-9 queue described above no longer gates training because I did
not promote the 23,214-record source-family manifest to the controlled
comparison. Instead, I derived and froze the substantially smaller
`fire_only_curated_manifest_v7`. Its curation removed the three dominant
mega-groups, capped retained groups, completed iterative visual duplicate
adjudication, stabilized split-preserving regrouping, and recorded a final
zero-link decision for the 108-pair high-risk queue.

The complete current decision, composition, hashes, and remaining claim limits
are in `docs/M3_CURATED_RESEARCH_DATASET_20260729.md`. This section supersedes
the earlier "Required next decision" for model training; it does not erase the
version-9 history or its limitations.
