[CmdletBinding()]
param(
    [ValidateSet('yolov8n_416','yolov8n_640','yolov8s_416','yolov8s_640','ssd_mobilenet_v2_fpnlite_320','efficientdet_lite0_320')]
    [string[]]$Include = @('yolov8n_416','yolov8n_640','yolov8s_416','yolov8s_640','ssd_mobilenet_v2_fpnlite_320','efficientdet_lite0_320'),
    [ValidatePattern('^$|^_[a-z0-9_]+$')]
    [string]$RetrySuffix = '',
    [switch]$PostprocessOnly,
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $project

$hostPython = Join-Path $project 'artifacts\envs\yolo_py312\Scripts\python.exe'
$annotations = Join-Path $project 'artifacts\training\fire_only_curated_v7_coco\test\labels.json'
$images = Join-Path $project 'artifacts\training\fire_only_curated_v7_coco\test\images'
$records = Join-Path $project 'artifacts\processed\fire_only_curated_manifest_v7\records.jsonl'
$comparison = Join-Path $project 'artifacts\experiments\model_screening_v1\test_comparison_v1'
$freeze = Join-Path $project 'artifacts\experiments\model_screening_v1\validation_comparison_v1\selection_freeze_20260809.json'
$expectedAnnotationsHash = '651e2782db96cbbdf2ba718494f7b57447f96aea6d7719fac350132f1b72a06d'
$expectedFreezeHash = '5e998b2b2e4bb6f0288266fe925a1da17a963e10fbfbad395f4e5b47aaa4be35'
$observedAnnotationsHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $annotations).Hash.ToLowerInvariant()
$observedFreezeHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $freeze).Hash.ToLowerInvariant()
if ($observedAnnotationsHash -ne $expectedAnnotationsHash) {
    throw "Frozen test annotation hash mismatch: $observedAnnotationsHash"
}
if ($observedFreezeHash -ne $expectedFreezeHash) {
    throw "Model-selection freeze hash mismatch: $observedFreezeHash"
}
if ((Get-ChildItem -LiteralPath $images -File).Count -ne 733) {
    throw 'Frozen test image count is not 733.'
}
if (-not (Test-Path -LiteralPath $hostPython)) {
    throw "Missing controlled host Python: $hostPython"
}

$env:PYTHONPATH = "$project;$project\tools;$project\src"
$env:YOLO_CONFIG_DIR = Join-Path $project 'artifacts\envs\ultralytics_config'
New-Item -ItemType Directory -Force -Path $env:YOLO_CONFIG_DIR | Out-Null

$thresholds = @{
    yolov8n_416 = 0.45
    yolov8n_640 = 0.36
    yolov8s_416 = 0.30
    yolov8s_640 = 0.22
    ssd_mobilenet_v2_fpnlite_320 = 0.81
    efficientdet_lite0_320 = 0.41
}

if ($ValidateOnly) {
    Write-Host "Test runner preflight passed; annotations SHA-256: $observedAnnotationsHash"
    Write-Host "Selection freeze SHA-256: $observedFreezeHash"
    return
}

function Assert-GpuIdle {
    $active = @(
        nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader,nounits 2>$null |
            Where-Object {
                $row = $_.Trim()
                if (-not $row) { return $false }
                $fields = @($row -split ',\s*')
                $processName = if ($fields.Count -ge 2) { $fields[1] } else { '' }
                $usedMemory = if ($fields.Count -ge 3) { $fields[-1] } else { '' }
                return (($usedMemory -match '^\d+$' -and [int]$usedMemory -gt 0) -or
                    $processName -match '(?i)(python|pythonw|wsl|bash|tensorflow|pytorch|cuda)')
            }
    )
    if ($active.Count -gt 0) {
        throw "GPU compute process already active: $($active -join '; ')"
    }
}

function Test-CompletedCandidate([string]$runDirectory) {
    foreach ($required in @('predictions.json','predictions_evaluable.json','prediction_sanitization.json','latency_ms.csv','run_summary.json','metrics.json','latency_summary.json','grouped_bootstrap.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $runDirectory $required))) { return $false }
    }
    return ((Get-Content -Raw -LiteralPath (Join-Path $runDirectory 'run_summary.json') | ConvertFrom-Json).status -eq 'completed')
}

function Invoke-Postprocess([string]$modelId, [string]$runDirectory) {
    $evaluable = Join-Path $runDirectory 'predictions_evaluable.json'
    $sanitization = Join-Path $runDirectory 'prediction_sanitization.json'
    if ((Test-Path -LiteralPath $evaluable) -and (Test-Path -LiteralPath $sanitization)) {
        Write-Host "REUSE completed prediction sanitization: $modelId"
    } elseif ((Test-Path -LiteralPath $evaluable) -or (Test-Path -LiteralPath $sanitization)) {
        throw "Partial sanitization evidence exists for $modelId; preserve and diagnose it."
    } else {
        & $hostPython tools\sanitize_coco_predictions.py `
            --input (Join-Path $runDirectory 'predictions.json') `
            --output $evaluable `
            --summary $sanitization
        if ($LASTEXITCODE -ne 0) { throw "Prediction sanitization failed for $modelId" }
    }
    $threshold = [double]$thresholds[$modelId]
    $wslRun = ($runDirectory -replace '^D:\\','/mnt/d/' -replace '\\','/')
    $metrics = Join-Path $runDirectory 'metrics.json'
    if (Test-Path -LiteralPath $metrics) {
        Write-Host "REUSE completed frozen-threshold metrics: $modelId"
    } else {
        $evalCommand = "export PYTHONPATH=/mnt/d/Drones/Drone_Enhanced/tools; /home/sefroyek/.venvs/drone_enhanced_effdet_py39/bin/python /mnt/d/Drones/Drone_Enhanced/tools/evaluate_coco_predictions.py --annotations /mnt/d/Drones/Drone_Enhanced/artifacts/training/fire_only_curated_v7_coco/test/labels.json --predictions $wslRun/predictions_evaluable.json --output $wslRun/metrics.json --model-id $modelId --split test --threshold $threshold"
        & wsl.exe bash -lc $evalCommand
        if ($LASTEXITCODE -ne 0) { throw "Frozen-threshold test evaluation failed for $modelId" }
    }
    $latencySummary = Join-Path $runDirectory 'latency_summary.json'
    if (Test-Path -LiteralPath $latencySummary) {
        Write-Host "REUSE completed latency summary: $modelId"
    } else {
        & $hostPython tools\summarize_latency.py `
            --latency-csv (Join-Path $runDirectory 'latency_ms.csv') `
            --model-id $modelId `
            --output $latencySummary
        if ($LASTEXITCODE -ne 0) { throw "Latency summary failed for $modelId" }
    }
    $bootstrap = Join-Path $runDirectory 'grouped_bootstrap.json'
    if (Test-Path -LiteralPath $bootstrap) {
        Write-Host "REUSE completed grouped bootstrap: $modelId"
    } else {
        & $hostPython tools\grouped_bootstrap_detection.py `
            --annotations $annotations `
            --predictions $evaluable `
            --records-jsonl $records `
            --split test `
            --threshold $threshold `
            --model-id $modelId `
            --resamples 2000 `
            --seed 20260729 `
            --output $bootstrap
        if ($LASTEXITCODE -ne 0) { throw "Grouped test bootstrap failed for $modelId" }
    }
}

function Invoke-FrozenCandidate([string]$modelId, [scriptblock]$predictionCommand) {
    $evidenceId = "$modelId$RetrySuffix"
    $runDirectory = Join-Path $comparison "runs\$evidenceId"
    if (Test-CompletedCandidate $runDirectory) {
        Write-Host "SKIP completed test candidate: $modelId"
        return
    }
    if ($PostprocessOnly) {
        foreach ($required in @('predictions.json','predictions_evaluable.json','prediction_sanitization.json','latency_ms.csv','run_summary.json')) {
            if (-not (Test-Path -LiteralPath (Join-Path $runDirectory $required))) {
                throw "Postprocess-only recovery lacks $required for $modelId"
            }
        }
        Invoke-Postprocess $modelId $runDirectory
        return
    }
    if (Test-Path -LiteralPath $runDirectory) {
        throw "Incomplete test evidence exists for $modelId; preserve it and use an explicit retry suffix."
    }
    Assert-GpuIdle
    & $predictionCommand $runDirectory
    if ($LASTEXITCODE -ne 0) { throw "Test prediction failed for $modelId" }
    Invoke-Postprocess $modelId $runDirectory
}

New-Item -ItemType Directory -Force -Path $comparison | Out-Null
$openingRecord = Join-Path $comparison 'test_opening_record.json'
if (-not (Test-Path -LiteralPath $openingRecord)) {
    $record = [ordered]@{
        schema_version = 1
        access_class = 'NO LAB'
        status = 'test_opened_for_one_frozen_pass'
        opened_utc = [DateTime]::UtcNow.ToString('o')
        selection_freeze_sha256 = $observedFreezeHash
        test_annotations_sha256 = $observedAnnotationsHash
        test_image_count = 733
        thresholds = $thresholds
        commitments = @(
            'no threshold tuning after test inspection',
            'no checkpoint reselection after test inspection',
            'no test-driven retraining',
            'preserve original output if an evaluator defect is corrected'
        )
    }
    $record | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $openingRecord -Encoding utf8
}

$yolo = @{
    yolov8n_416 = @{ checkpoint = 'artifacts\experiments\model_screening_v1\yolov8n_416_screen_seed_20260729\weights\best.pt'; size = 416 }
    yolov8n_640 = @{ checkpoint = 'artifacts\experiments\model_screening_v1\yolov8n_640_screen_seed_20260729\weights\best.pt'; size = 640 }
    yolov8s_416 = @{ checkpoint = 'artifacts\experiments\model_screening_v1\yolov8s_416_screen_seed_20260729\weights\best.pt'; size = 416 }
    yolov8s_640 = @{ checkpoint = 'artifacts\experiments\model_screening_v1\yolov8s_640_screen_seed_20260729\weights\best.pt'; size = 640 }
}
foreach ($modelId in @('yolov8n_416','yolov8n_640','yolov8s_416','yolov8s_640')) {
    if ($modelId -notin $Include) { continue }
    $entry = $yolo[$modelId]
    Invoke-FrozenCandidate $modelId {
        param($runDirectory)
        & $hostPython tools\predict_yolo_coco.py `
            --model-id $modelId `
            --checkpoint $entry.checkpoint `
            --annotations $annotations `
            --image-directory $images `
            --output-directory $runDirectory `
            --input-size $entry.size `
            --batch 1 `
            --device 0 `
            --score-floor 0.001 `
            --warmup 10
    }
}

if ('ssd_mobilenet_v2_fpnlite_320' -in $Include) {
    $modelId = 'ssd_mobilenet_v2_fpnlite_320'
    Invoke-FrozenCandidate $modelId {
        param($runDirectory)
        $wslOutput = ($runDirectory -replace '^D:\\','/mnt/d/' -replace '\\','/')
        $tfodCommand = "export PYTHONPATH=/home/sefroyek/.local/share/drone_enhanced/tensorflow_models_r2.15.0/research:/home/sefroyek/.local/share/drone_enhanced/tensorflow_models_r2.15.0/research/slim; /home/sefroyek/.venvs/drone_enhanced_tf_py311/bin/python /mnt/d/Drones/Drone_Enhanced/tools/predict_tfod_coco.py --model-id $modelId --pipeline-config /mnt/d/Drones/Drone_Enhanced/config/ssd_mobilenet_v2_fpnlite_320_screen_batch8_v1.config --checkpoint-directory /mnt/d/Drones/Drone_Enhanced/artifacts/experiments/model_screening_v1/ssd_mobilenet_v2_screen_seed_20260729 --annotations /mnt/d/Drones/Drone_Enhanced/artifacts/training/fire_only_curated_v7_coco/test/labels.json --image-directory /mnt/d/Drones/Drone_Enhanced/artifacts/training/fire_only_curated_v7_coco/test/images --output-directory $wslOutput --score-floor 0.001 --warmup 10"
        & wsl.exe bash -lc $tfodCommand
    }
}

if ('efficientdet_lite0_320' -in $Include) {
    $modelId = 'efficientdet_lite0_320'
    Invoke-FrozenCandidate $modelId {
        param($runDirectory)
        $wslOutput = ($runDirectory -replace '^D:\\','/mnt/d/' -replace '\\','/')
        $tfliteCommand = "/home/sefroyek/.venvs/drone_enhanced_effdet_py39/bin/python /mnt/d/Drones/Drone_Enhanced/tools/predict_tflite_coco.py --model-id $modelId --model /mnt/d/Drones/Drone_Enhanced/artifacts/experiments/model_screening_v1/efficientdet_lite0_screen_seed_20260729_retry10_resume_ckpt90/export_retry3_cpu/efficientdet_lite0.tflite --annotations /mnt/d/Drones/Drone_Enhanced/artifacts/training/fire_only_curated_v7_coco/test/labels.json --image-directory /mnt/d/Drones/Drone_Enhanced/artifacts/training/fire_only_curated_v7_coco/test/images --output-directory $wslOutput --boxes-tensor-index 598 --classes-tensor-index 599 --scores-tensor-index 600 --count-tensor-index 601 --class-id-offset 1 --integer-input-mode raw_pixels --score-floor 0.001 --warmup 10"
        & wsl.exe bash -lc $tfliteCommand
    }
}

if (-not $PostprocessOnly) {
    $completion = [ordered]@{
        schema_version = 1
        access_class = 'NO LAB'
        status = 'requested_candidates_completed'
        completed_utc = [DateTime]::UtcNow.ToString('o')
        selection_freeze_sha256 = $observedFreezeHash
        test_annotations_sha256 = $observedAnnotationsHash
        included_candidates = $Include
        retry_suffix = $RetrySuffix
        thresholds_unchanged = $thresholds
    }
    $completionPath = Join-Path $comparison ("completion$RetrySuffix.json")
    if (-not (Test-Path -LiteralPath $completionPath)) {
        $completion | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $completionPath -Encoding utf8
    }
}
Write-Host 'Frozen one-time test evaluation completed for the requested candidates; thresholds were not tuned.'
