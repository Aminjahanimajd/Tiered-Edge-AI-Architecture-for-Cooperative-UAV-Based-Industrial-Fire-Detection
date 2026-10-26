param(
    [string]$ProjectRoot = "D:\Drones\Drone_Enhanced"
)

$ErrorActionPreference = "Continue"
$experimentRoot = Join-Path $ProjectRoot "artifacts\experiments\model_screening_v1"
$queueLog = Join-Path $experimentRoot "queue_events.jsonl"
$nonYoloLog = Join-Path $experimentRoot "non_yolo_queue_events.jsonl"
$logs = Join-Path $experimentRoot "queue_logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

function Write-QueueEvent([string]$model, [string]$event, [object]$detail) {
    [ordered]@{
        utc_time = [DateTime]::UtcNow.ToString("o")
        model_id = $model
        event = $event
        detail = $detail
    } | ConvertTo-Json -Compress | Add-Content -LiteralPath $nonYoloLog -Encoding utf8
}

Write-QueueEvent "non_yolo_queue" "waiting_for_yolo_queue" $queueLog
do {
    Start-Sleep -Seconds 20
    $yoloFinished = (Test-Path -LiteralPath $queueLog) -and
        (Select-String -LiteralPath $queueLog -SimpleMatch '"model_id":"queue","event":"completed"' -Quiet)
} until ($yoloFinished)
Write-QueueEvent "non_yolo_queue" "yolo_queue_finished" $null

$ssdBase = "source /home/sefroyek/.venvs/drone_enhanced_tf_py311/bin/activate && " +
    "export PYTHONPATH=/home/sefroyek/.local/share/drone_enhanced/tensorflow_models_r2.15.0/research:" +
    "/home/sefroyek/.local/share/drone_enhanced/tensorflow_models_r2.15.0/research/slim && "
$ssdConfig = "/mnt/d/Drones/Drone_Enhanced/config/ssd_mobilenet_v2_fpnlite_320_screen_batch8_v1.config"
$ssdRunner = "/mnt/d/Drones/Drone_Enhanced/tools/run_ssd_model_main.py"
$ssdSanityDir = "/mnt/d/Drones/Drone_Enhanced/artifacts/experiments/model_screening_v1/ssd_mobilenet_v2_sanity_retry4"
$ssdFullDir = "/mnt/d/Drones/Drone_Enhanced/artifacts/experiments/model_screening_v1/ssd_mobilenet_v2_screen_seed_20260729"

Write-QueueEvent "ssd_mobilenet_v2" "sanity_started" @{ steps = 1; batch = 8 }
& wsl.exe bash -lc ($ssdBase + "python $ssdRunner --pipeline_config_path=$ssdConfig --model_dir=$ssdSanityDir --num_train_steps=1 --alsologtostderr") `
    *> (Join-Path $logs "ssd_mobilenet_v2_sanity.log")
$ssdSanityExit = $LASTEXITCODE
Write-QueueEvent "ssd_mobilenet_v2" "sanity_exited" @{ exit_code = $ssdSanityExit }

$effdetBase = "source /home/sefroyek/.venvs/drone_enhanced_effdet_py39/bin/activate && " +
    "export PYTHONPATH=/mnt/d/Drones/Drone_Enhanced/tools && " +
    "export TFHUB_CACHE_DIR=/mnt/d/Drones/Drone_Enhanced/artifacts/models/tfhub_cache && " +
    "export LD_LIBRARY_PATH=`$(find /home/sefroyek/.venvs/drone_enhanced_effdet_py39/lib/python3.9/site-packages/nvidia -type d -name lib | paste -sd:):`$LD_LIBRARY_PATH && "
$effdetRunner = "/mnt/d/Drones/Drone_Enhanced/tools/run_effdet_experiment.py"
$effdetInputs = "--train-records '/mnt/d/Drones/Drone_Enhanced/artifacts/training/fire_only_curated_v7_tfrecord/coco_train.record-*' " +
    "--train-annotations /mnt/d/Drones/Drone_Enhanced/artifacts/training/fire_only_curated_v7_coco/train/labels.json " +
    "--validation-records '/mnt/d/Drones/Drone_Enhanced/artifacts/training/fire_only_curated_v7_tfrecord/coco_val.record-*' " +
    "--validation-annotations /mnt/d/Drones/Drone_Enhanced/artifacts/training/fire_only_curated_v7_coco/valid/labels.json " +
    "--batch-size 4 "
$effdetSanityDir = "/mnt/d/Drones/Drone_Enhanced/artifacts/experiments/model_screening_v1/efficientdet_lite0_sanity"
$effdetFullDir = "/mnt/d/Drones/Drone_Enhanced/artifacts/experiments/model_screening_v1/efficientdet_lite0_screen_seed_20260729"

Write-QueueEvent "efficientdet_lite0" "sanity_started" @{ epochs = 1; examples = 8; batch = 4 }
& wsl.exe bash -lc ($effdetBase + "python $effdetRunner $effdetInputs --output-directory $effdetSanityDir --sanity") `
    *> (Join-Path $logs "efficientdet_lite0_sanity.log")
$effdetSanityExit = $LASTEXITCODE
Write-QueueEvent "efficientdet_lite0" "sanity_exited" @{ exit_code = $effdetSanityExit }

if ($ssdSanityExit -eq 0) {
    Write-QueueEvent "ssd_mobilenet_v2" "training_started" @{ steps = 44500; batch = 8; seed = 20260729 }
    & wsl.exe bash -lc ($ssdBase + "python $ssdRunner --pipeline_config_path=$ssdConfig --model_dir=$ssdFullDir --num_train_steps=44500 --alsologtostderr") `
        *> (Join-Path $logs "ssd_mobilenet_v2_training.log")
    Write-QueueEvent "ssd_mobilenet_v2" "training_exited" @{ exit_code = $LASTEXITCODE }
} else {
    Write-QueueEvent "ssd_mobilenet_v2" "training_not_admitted" @{ sanity_exit_code = $ssdSanityExit }
}

if ($effdetSanityExit -eq 0) {
    Write-QueueEvent "efficientdet_lite0" "training_started" @{ epochs = 100; batch = 4; seed = 20260729 }
    & wsl.exe bash -lc ($effdetBase + "python $effdetRunner $effdetInputs --output-directory $effdetFullDir") `
        *> (Join-Path $logs "efficientdet_lite0_training.log")
    Write-QueueEvent "efficientdet_lite0" "training_exited" @{ exit_code = $LASTEXITCODE }
} else {
    Write-QueueEvent "efficientdet_lite0" "training_not_admitted" @{ sanity_exit_code = $effdetSanityExit }
}

Write-QueueEvent "non_yolo_queue" "completed" $null
