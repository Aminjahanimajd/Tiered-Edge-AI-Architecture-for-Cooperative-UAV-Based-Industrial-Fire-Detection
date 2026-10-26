param(
    [string]$ProjectRoot = "D:\Drones\Drone_Enhanced"
)

$ErrorActionPreference = "Continue"
$experimentRoot = Join-Path $ProjectRoot "artifacts\experiments\model_screening_v1"
$queueLog = Join-Path $experimentRoot "queue_events.jsonl"
$python = Join-Path $ProjectRoot "artifacts\envs\yolo_py312\Scripts\python.exe"
$runner = Join-Path $ProjectRoot "tools\run_yolo_experiment.py"
$matrix = Join-Path $ProjectRoot "config\model_screening_matrix_v1_20260729.json"
$dataset = Join-Path $ProjectRoot "artifacts\training\fire_only_curated_v7\dataset.yaml"
$weights = Join-Path $ProjectRoot "artifacts\models\pretrained"
$firstSummary = Join-Path $experimentRoot "yolov8n_416_screen_seed_20260729_evidence\run_summary.json"

$env:YOLO_CONFIG_DIR = Join-Path $ProjectRoot "artifacts\envs\ultralytics_config"
$env:MPLCONFIGDIR = Join-Path $env:YOLO_CONFIG_DIR "matplotlib"

function Write-QueueEvent([string]$model, [string]$event, [object]$detail) {
    [ordered]@{
        utc_time = [DateTime]::UtcNow.ToString("o")
        model_id = $model
        event = $event
        detail = $detail
    } | ConvertTo-Json -Compress | Add-Content -LiteralPath $queueLog -Encoding utf8
}

Write-QueueEvent "yolov8n_416" "waiting_for_first_run" $firstSummary
while (-not (Test-Path -LiteralPath $firstSummary)) {
    Start-Sleep -Seconds 20
}
$first = Get-Content -LiteralPath $firstSummary -Raw | ConvertFrom-Json
Write-QueueEvent "yolov8n_416" "first_run_finished" $first.status

$jobs = @(
    @{ id = "yolov8s_640"; batch = 4 },
    @{ id = "yolov8n_640"; batch = 4 },
    @{ id = "yolov8s_416"; batch = 8 }
)

foreach ($job in $jobs) {
    $runSummary = Join-Path $experimentRoot ($job.id + "_screen_seed_20260729_evidence\run_summary.json")
    if (Test-Path -LiteralPath $runSummary) {
        Write-QueueEvent $job.id "skipped_existing_summary" $runSummary
        continue
    }
    Write-QueueEvent $job.id "started" @{ batch = $job.batch; seed = 20260729 }
    & $python $runner $job.id --matrix $matrix --dataset-yaml $dataset `
        --weights-directory $weights --output-root $experimentRoot `
        --batch $job.batch --workers 2 --ac-power-confirmed
    $exitCode = $LASTEXITCODE
    Write-QueueEvent $job.id "process_exited" @{ exit_code = $exitCode }
}

Write-QueueEvent "queue" "completed" $null
