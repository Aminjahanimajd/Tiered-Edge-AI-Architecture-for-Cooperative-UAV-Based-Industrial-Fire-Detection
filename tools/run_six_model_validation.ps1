[CmdletBinding()]
param(
    [ValidateSet('yolov8n_416','yolov8n_640','yolov8s_416','yolov8s_640','ssd_mobilenet_v2_fpnlite_320','efficientdet_lite0_320')]
    [string[]]$Include = @('yolov8n_416','yolov8n_640','yolov8s_416','yolov8s_640','ssd_mobilenet_v2_fpnlite_320','efficientdet_lite0_320'),
    [int]$EffdetBoxesTensorIndex = -1,
    [int]$EffdetClassesTensorIndex = -1,
    [int]$EffdetScoresTensorIndex = -1,
    [int]$EffdetCountTensorIndex = -1,
    [ValidatePattern('^$|^_[a-z0-9_]+$')]
    [string]$RetrySuffix = '',
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $project

$hostPython = Join-Path $project 'artifacts\envs\yolo_py312\Scripts\python.exe'
$annotations = Join-Path $project 'artifacts\training\fire_only_curated_v7_coco\valid\labels.json'
$images = Join-Path $project 'artifacts\training\fire_only_curated_v7_coco\valid\images'
$records = Join-Path $project 'artifacts\processed\fire_only_curated_manifest_v7\records.jsonl'
$comparison = Join-Path $project 'artifacts\experiments\model_screening_v1\validation_comparison_v1'
$expectedAnnotationsHash = '1a93f800d63bf355bb586039da245cd612cbdd7052102cbfd6da1409312ab7c6'
$observedAnnotationsHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $annotations).Hash.ToLowerInvariant()
if ($observedAnnotationsHash -ne $expectedAnnotationsHash) {
    throw "Frozen validation annotation hash mismatch: $observedAnnotationsHash"
}
if (-not (Test-Path -LiteralPath $hostPython)) {
    throw "Missing controlled host Python: $hostPython"
}
if (-not (Test-Path -LiteralPath $images)) {
    throw "Missing frozen validation image directory: $images"
}

$env:PYTHONPATH = "$project;$project\tools;$project\src"
$env:YOLO_CONFIG_DIR = Join-Path $project 'artifacts\envs\ultralytics_config'
New-Item -ItemType Directory -Force -Path $env:YOLO_CONFIG_DIR | Out-Null
if ($ValidateOnly) {
    Write-Host "Validation runner preflight passed; frozen annotation SHA-256: $observedAnnotationsHash"
    return
}

function Assert-GpuIdle {
    # Under Windows WDDM, nvidia-smi lists ordinary desktop clients in the
    # compute-app table with an unavailable ("[N/A]") memory value.  Treating
    # every such row as a competing experiment prevents reproducible runs on
    # an otherwise idle laptop.  Retain rows with measurable device memory or
    # an explicit Python/WSL compute-process name; ignore WDDM GUI clients.
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
        throw "GPU compute process already active. Validation requires an otherwise idle GPU: $($active -join '; ')"
    }
}

function Test-CompletedCandidate([string]$runDirectory) {
    $summaryPath = Join-Path $runDirectory 'run_summary.json'
    foreach ($required in @('predictions.json','predictions_evaluable.json','prediction_sanitization.json','latency_ms.csv','run_summary.json','metrics.json','latency_summary.json','grouped_bootstrap.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $runDirectory $required))) { return $false }
    }
    return ((Get-Content -Raw -LiteralPath $summaryPath | ConvertFrom-Json).status -eq 'completed')
}

function Invoke-Postprocess([string]$modelId, [string]$runDirectory) {
    $evaluable = Join-Path $runDirectory 'predictions_evaluable.json'
    & $hostPython tools\sanitize_coco_predictions.py `
        --input (Join-Path $runDirectory 'predictions.json') `
        --output $evaluable `
        --summary (Join-Path $runDirectory 'prediction_sanitization.json')
    if ($LASTEXITCODE -ne 0) { throw "Prediction sanitization failed for $modelId" }
    $metrics = Join-Path $runDirectory 'metrics.json'
    $latencySummary = Join-Path $runDirectory 'latency_summary.json'
    $bootstrap = Join-Path $runDirectory 'grouped_bootstrap.json'
    $wslRun = ($runDirectory -replace '^D:\\','/mnt/d/' -replace '\\','/')
    $evalCommand = "export PYTHONPATH=/mnt/d/Drones/Drone_Enhanced/tools; /home/sefroyek/.venvs/drone_enhanced_effdet_py39/bin/python /mnt/d/Drones/Drone_Enhanced/tools/evaluate_coco_predictions.py --annotations /mnt/d/Drones/Drone_Enhanced/artifacts/training/fire_only_curated_v7_coco/valid/labels.json --predictions $wslRun/predictions_evaluable.json --output $wslRun/metrics.json --model-id $modelId --split validation"
    & wsl.exe bash -lc $evalCommand
    if ($LASTEXITCODE -ne 0) { throw "Metric evaluation failed for $modelId" }
    & $hostPython tools\summarize_latency.py `
        --latency-csv (Join-Path $runDirectory 'latency_ms.csv') `
        --model-id $modelId `
        --output $latencySummary
    if ($LASTEXITCODE -ne 0) { throw "Latency summary failed for $modelId" }
    $threshold = [double]((Get-Content -Raw -LiteralPath $metrics | ConvertFrom-Json).thresholded_iou50.threshold)
    & $hostPython tools\grouped_bootstrap_detection.py `
        --annotations $annotations `
        --predictions $evaluable `
        --records-jsonl $records `
        --split validation `
        --threshold $threshold `
        --model-id $modelId `
        --resamples 2000 `
        --seed 20260729 `
        --output $bootstrap
    if ($LASTEXITCODE -ne 0) { throw "Grouped bootstrap failed for $modelId" }
}

function Invoke-GuardedCandidate([string]$modelId, [scriptblock]$predictionCommand) {
    $evidenceId = "$modelId$RetrySuffix"
    $runDirectory = Join-Path $comparison "runs\$evidenceId"
    $resourceDirectory = Join-Path $comparison "resources\$evidenceId"
    if (Test-CompletedCandidate $runDirectory) {
        Write-Host "SKIP completed candidate: $modelId"
        return
    }
    if ((Test-Path -LiteralPath $runDirectory) -or (Test-Path -LiteralPath $resourceDirectory)) {
        throw "Incomplete evidence exists for $modelId. Preserve it and choose a new explicit retry directory; refusing overwrite."
    }
    Assert-GpuIdle
    & $predictionCommand $runDirectory $resourceDirectory
    if ($LASTEXITCODE -ne 0) { throw "Prediction/resource run failed for $modelId" }
    Invoke-Postprocess $modelId $runDirectory
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
    Invoke-GuardedCandidate $modelId {
        param($runDirectory, $resourceDirectory)
        & $hostPython tools\run_with_resource_sampling.py `
            --model-id $modelId `
            --output-directory $resourceDirectory `
            --interval-seconds 0.5 `
            -- $hostPython tools\predict_yolo_coco.py `
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
    Invoke-GuardedCandidate $modelId {
        param($runDirectory, $resourceDirectory)
        $wslOutput = ($runDirectory -replace '^D:\\','/mnt/d/' -replace '\\','/')
        $tfodCommand = "export PYTHONPATH=/home/sefroyek/.local/share/drone_enhanced/tensorflow_models_r2.15.0/research:/home/sefroyek/.local/share/drone_enhanced/tensorflow_models_r2.15.0/research/slim; /home/sefroyek/.venvs/drone_enhanced_tf_py311/bin/python /mnt/d/Drones/Drone_Enhanced/tools/predict_tfod_coco.py --model-id $modelId --pipeline-config /mnt/d/Drones/Drone_Enhanced/config/ssd_mobilenet_v2_fpnlite_320_screen_batch8_v1.config --checkpoint-directory /mnt/d/Drones/Drone_Enhanced/artifacts/experiments/model_screening_v1/ssd_mobilenet_v2_screen_seed_20260729 --annotations /mnt/d/Drones/Drone_Enhanced/artifacts/training/fire_only_curated_v7_coco/valid/labels.json --image-directory /mnt/d/Drones/Drone_Enhanced/artifacts/training/fire_only_curated_v7_coco/valid/images --output-directory $wslOutput --score-floor 0.001 --warmup 10"
        & $hostPython tools\run_with_resource_sampling.py `
            --model-id $modelId `
            --output-directory $resourceDirectory `
            --interval-seconds 0.5 `
            -- wsl.exe bash -lc $tfodCommand
    }
}

if ('efficientdet_lite0_320' -in $Include) {
    foreach ($value in @($EffdetBoxesTensorIndex,$EffdetClassesTensorIndex,$EffdetScoresTensorIndex,$EffdetCountTensorIndex)) {
        if ($value -lt 0) { throw 'All four EfficientDet tensor indices must come from inspect_tflite_interface.py evidence.' }
    }
    $modelId = 'efficientdet_lite0_320'
    Invoke-GuardedCandidate $modelId {
        param($runDirectory, $resourceDirectory)
        $wslOutput = ($runDirectory -replace '^D:\\','/mnt/d/' -replace '\\','/')
        $tfliteCommand = "/home/sefroyek/.venvs/drone_enhanced_effdet_py39/bin/python /mnt/d/Drones/Drone_Enhanced/tools/predict_tflite_coco.py --model-id $modelId --model /mnt/d/Drones/Drone_Enhanced/artifacts/experiments/model_screening_v1/efficientdet_lite0_screen_seed_20260729_retry10_resume_ckpt90/export_retry3_cpu/efficientdet_lite0.tflite --annotations /mnt/d/Drones/Drone_Enhanced/artifacts/training/fire_only_curated_v7_coco/valid/labels.json --image-directory /mnt/d/Drones/Drone_Enhanced/artifacts/training/fire_only_curated_v7_coco/valid/images --output-directory $wslOutput --boxes-tensor-index $EffdetBoxesTensorIndex --classes-tensor-index $EffdetClassesTensorIndex --scores-tensor-index $EffdetScoresTensorIndex --count-tensor-index $EffdetCountTensorIndex --class-id-offset 1 --integer-input-mode raw_pixels --score-floor 0.001 --warmup 10"
        & $hostPython tools\run_with_resource_sampling.py `
            --model-id $modelId `
            --output-directory $resourceDirectory `
            --interval-seconds 0.5 `
            -- wsl.exe bash -lc $tfliteCommand
    }
}

Write-Host 'Requested validation candidates completed. The untouched test split was not accessed.'
