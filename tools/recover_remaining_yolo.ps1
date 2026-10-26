param([string]$ProjectRoot = "D:\Drones\Drone_Enhanced")

$ErrorActionPreference = "Continue"
$root = Join-Path $ProjectRoot "artifacts\experiments\model_screening_v1"
$events = Join-Path $root "recovery_queue_events.jsonl"
$python = Join-Path $ProjectRoot "artifacts\envs\yolo_py312\Scripts\python.exe"
$env:YOLO_CONFIG_DIR = Join-Path $ProjectRoot "artifacts\envs\ultralytics_config"
$env:MPLCONFIGDIR = Join-Path $env:YOLO_CONFIG_DIR "matplotlib"

function Event([string]$model, [string]$event, [object]$detail) {
    [ordered]@{utc_time=[DateTime]::UtcNow.ToString("o");model_id=$model;event=$event;detail=$detail} |
        ConvertTo-Json -Compress | Add-Content -LiteralPath $events -Encoding utf8
}
function Wait-CoolGpu {
    do {
        $temperature = [int](nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits)
        if ($temperature -ge 65) { Start-Sleep -Seconds 20 }
    } while ($temperature -ge 65)
}

Wait-CoolGpu
$partial = Join-Path $root "yolov8n_640_screen_seed_20260729"
$resumeEvidence = Join-Path $root "yolov8n_640_screen_seed_20260729_resume1_evidence"
Event "yolov8n_640" "resume_started" @{ checkpoint = (Join-Path $partial "weights\last.pt") }
& $python (Join-Path $ProjectRoot "tools\resume_yolo_experiment.py") `
    --run-directory $partial --evidence-directory $resumeEvidence --ac-power-confirmed
$resumeExit = $LASTEXITCODE
Event "yolov8n_640" "resume_exited" @{ exit_code = $resumeExit }

if ($resumeExit -eq 0) {
    Wait-CoolGpu
    Event "yolov8s_416" "training_started" @{ batch = 8; seed = 20260729 }
    & $python (Join-Path $ProjectRoot "tools\run_yolo_experiment.py") yolov8s_416 `
        --matrix (Join-Path $ProjectRoot "config\model_screening_matrix_v1_20260729.json") `
        --dataset-yaml (Join-Path $ProjectRoot "artifacts\training\fire_only_curated_v7\dataset.yaml") `
        --weights-directory (Join-Path $ProjectRoot "artifacts\models\pretrained") `
        --output-root $root --batch 8 --workers 2 --ac-power-confirmed
    Event "yolov8s_416" "training_exited" @{ exit_code = $LASTEXITCODE }
} else {
    Event "yolov8s_416" "not_started_after_failed_resume" @{ resume_exit_code = $resumeExit }
}
Event "recovery_queue" "completed" $null
