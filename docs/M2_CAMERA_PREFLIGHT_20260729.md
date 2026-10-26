# M2 Camera Preflight and Live Encoding Validation

**Validation date:** 29 July 2026  
**Enhanced runtime revisions:** `b3512df`, `850b63b`, and `8129105`  
**Current status:** Scout and Sentinel camera-interface probes passed; full-node
camera-negative integration remains pending

## Objective and safety boundary

I performed this stage to verify both live camera paths before running either
full inference node. Both aircraft remained stationary with their propellers
removed. I did not use a lighter, introduce a hazard, issue a flight command,
save an image, or run an end-to-end detection trial. The probes retained only
device metadata, ROS image metadata, timing observations, and aggregate pixel
statistics.

This stage establishes camera-interface and decoder compatibility only. It
does not establish model accuracy, hazard-detection performance, camera color
accuracy, long-duration frame reliability, or end-to-end system operation.

## Evidence-capture corrections

The initial camera inventory exposed two local evidence-tool defects. One Scout
record contained a successful remote command but a null captured stream after a
Windows Unicode decode failure. A later complete record was written, but the
local console could not print a Unicode status symbol. I retained the incomplete
record and corrected the evidence wrapper to decode remote output as UTF-8 with
replacement and to render unsupported console characters safely. I also
changed the evidence index so a zero-exit record with a null capture is
classified as `INCOMPLETE`, not `PASS`.

PowerShell also rejected several intended remote commands before SSH because
nested pipes, globs, or quotes were interpreted locally. These attempts changed
neither device and produced no raw evidence record. I added a tested Base64
remote-command option to remove this quoting ambiguity. The full host suite
contained 54 passing tests immediately after the camera and evidence-tool
changes; the current repository suite contains 71 passing tests after the
later dataset and annotation-audit additions.

## Scout camera inventory

The active `voxl-camera-server` configuration declares two cameras:

- `hires`: IMX412, 30 fps, 1024 x 768 small video, 4056 x 3040 large video;
- `tracking`: AR0144, 30 fps, 1280 x 800 preview and MISP streams.

The live MPA metadata for `/run/mpa/hires_small_color` initially declared NV12,
1024 x 768, and 30 fps. This pipe-level declaration was not used as the final
ROS encoding claim because the ROS bridge later reported a different concrete
representation.

The camera service was active and reported that it had started both cameras.
Its log also reported a missing `tracking_intrinsics.yml` file and the use of
default tracking-camera lens calibration. That warning is relevant to geometric
or localization work, but it does not invalidate the present pixel-buffer and
decoder checks. No calibrated localization claim is made from this test.

## Scout ROS bridge reconstruction

The base Foxy environment did not expose `voxl_mpa_to_ros2`, which initially
made `/hires_small_color` appear absent. The package was installed in a separate
overlay at `/opt/ros/foxy/mpa_to_ros2/install/setup.bash`. Sourcing both base
Foxy and this overlay exposed the expected
`voxl_mpa_to_ros2_node` executable.

I launched that bridge only in bounded temporary sessions, used isolated ROS
domains, and terminated the exact child PID after each test. One early cleanup
targeted the `ros2 run` launcher rather than the spawned bridge process, leaving
PID 24800 orphaned. I identified its executable and start time, terminated only
that verified process with SIGTERM, and changed subsequent cleanup to target
the actual `voxl_mpa_to_ros2_node` PID. Later cleanup checks found no residual
bridge.

## Scout failure isolation and recovery

Before recovery, the bridge created `/hires_small_color`, but a bounded
subscriber received zero messages. In the same bridge session, the tracking
camera delivered 5/5 valid 1280 x 800 `mono8` frames. This controlled
within-session comparison isolated the failure to the hires stream rather than
Foxy, Cyclone DDS, the bridge executable, or the subscriber implementation.

I issued one logged restart of `voxl-camera-server`. The service acknowledged
SIGTERM but did not exit. Systemd remained in `stop-sigterm` for 90 seconds,
then killed PID 1502 with SIGKILL and started PID 9372. I therefore classify
this as a forced recovery, not a graceful or routine restart procedure.

After recovery, the same bounded test received 10/10 frames from both streams:

| Stream | Samples | ROS encoding | Geometry | Step | Payload bytes | Result |
|---|---:|---|---|---:|---:|---|
| `/tracking` | 10 | `mono8` | 1280 x 800 | 1280 | 1,024,000 | pass |
| `/hires_small_color` | 10 | `yuv422` | 1024 x 768 | 2048 | 1,572,864 | pass |

The hires payload equals `1024 x 768 x 2` bytes and is consistent with packed
YUV 4:2:2. The live ROS representation is therefore `yuv422`, not NV12, even
though the MPA `info` file described the pipe as NV12.

## Scout enhanced-decoder validation

I replaced size-only color inference with an explicit decoder that validates
encoding, dimensions, payload length, and row step. It maps ROS `yuv422`/UYVY
to OpenCV's UYVY conversion and separately supports YUYV/YUY2, NV12, NV21,
RGB8, and BGR8 layouts.

I transferred the exact committed helper and probe to a revision-named
isolated `/tmp` stage. The local and remote SHA-256 hashes matched. The first
run replaced Foxy's `PYTHONPATH` and could not import `rclpy`; it changed no
runtime package and the temporary bridge was cleaned up. The corrected run
prepended the staged sources while preserving Foxy's path.

That corrected run decoded 3/3 live hires frames with no errors:

- source: 1024 x 768, `yuv422`, step 2048, 1,572,864 bytes;
- decoder path: explicit UYVY;
- output: 1024 x 768 x 3, unsigned 8-bit BGR;
- observed BGR channel means ranged approximately from 138.2 to 150.2;
- observed channel population standard deviations ranged approximately from
  69.5 to 78.2;
- observed pixel range was 0 to 255; and
- no image or pixel array was persisted.

These statistics show that the conversion produced a non-constant,
three-channel image with valid numeric range. They do not prove perceptual color
accuracy. A recorded or visually inspected reference frame remains necessary
for a formal color-fidelity claim.

The key passed live-decoder record SHA-256 is
`735dfb55de3c50d36b4921ccaf689659b088ed6cccb0b186454b41a8d5e7e7bf`.

## Sentinel camera inventory and detected conflict

All three V4L2 nodes belong to the Intel RealSense D435i. FFmpeg format
enumeration found:

- `/dev/video1`: grayscale and UYVY modes including 640 x 480;
- `/dev/video2`: YUYV modes including 640 x 480; and
- `/dev/video0`: no format output within the bounded inventory command.

The stable by-ID `video-index0` link and the historical runtime both select
`/dev/video2`. The enhanced node originally used
`VideoCapture(2, CAP_V4L2)`. Live probing showed that this OpenCV 3.2 build
rejects the incoming YUYV representation with an unsupported-pixel-format
error. I replaced that invalid default with the historically demonstrated
GStreamer path:

```text
v4l2src device=/dev/video2 !
video/x-raw, format=YUY2, width=640, height=480, framerate=30/1 !
videoconvert ! video/x-raw, format=BGR !
appsink drop=true max-buffers=1 sync=false
```

The enhanced session manifest now records the camera backend, device, width,
height, frame-rate request, and full pipeline. The pipeline builder and probe
are covered by host tests.

The live GStreamer probe then reported the camera busy. A process audit found
that enabled systemd unit `camera-stream.service` has held `/dev/video2` since
26 June 2026. It sends an H.264 RTP/UDP stream to `10.42.0.246:5600`. This
exclusive consumer is the current reason a second Sentinel process cannot open
the camera. No Docker container or other user process held the device.

The SSH key does not have passwordless sudo authority, so I did not stop the
root-owned service. The operator must stop it interactively before the pending
10-frame GStreamer probe. The service must then be restored and its new PID and
active timestamp recorded.

At 13:28 UTC on 29 July 2026, I repeated a read-only service check. The unit was
still `active`, with the same main PID 3959 and active-enter timestamp of
26 June 2026 at 17:22:31 CEST. The evidence-record SHA-256 is
`3ea517c9aa87393d3276877a2c05254d19f0430ebb14a0c05806d385ce07b000`.
I made no device change during this check.

After the operator explicitly authorized pausing the QGC video stream, I first
attempted a passwordless stop. Sudo rejected it, and the service remained on
PID 3959. The operator then stopped the unit interactively. A recorded precheck
confirmed `inactive` state and no reported holder of `/dev/video2`; its evidence
SHA-256 is
`b50863b4f94ce0fbf728485f1c288dda0f132639860ae5bf9121ec344ce22f74`.

I then ran the enhanced probe in a disposable, network-disabled Docker
container against `/dev/video2`. It opened the explicit YUY2-to-BGR GStreamer
pipeline and received 10/10 requested frames with zero failed reads. Every
frame had shape 480 x 640 x 3, unsigned 8-bit data, and observed pixel range
0 to 255. The nine arrival intervals had mean 53.945 ms, median 52.939 ms,
minimum 52.664 ms, maximum 58.129 ms, and population standard deviation
1.819 ms. This short diagnostic interval is not a sustained-FPS benchmark.
No pixel content was saved. The passing evidence-record SHA-256 is
`99180b4095af620e975760d8ddc46bd696429601ae37a358a3e1039bf735f0c9`.

The container printed NVIDIA Argus socket warnings and two OpenCV GStreamer
property warnings. The D435i probe uses V4L2 rather than Argus, opened
successfully, and returned all requested frames, so I retain the warnings as
diagnostic context rather than treating them as frame-capture failures.

The operator restored `camera-stream.service` immediately after the probe. A
recorded verification found the unit `active` on new PID 15891, with active-
enter timestamp 29 July 2026 at 15:36:07 CEST. The restoration evidence-record
SHA-256 is
`04651ca1e241ccb194dc02fac0d9f32d98df3be05aaca41d70c570107881471a`.

## Current acceptance decision

I classify the following as passed:

- Scout camera-server and ROS bridge reconstruction;
- live tracking-camera metadata;
- post-recovery live hires metadata;
- exact `yuv422` payload geometry;
- 3/3 live frames through the enhanced UYVY decoder;
- Sentinel D435i node and pixel-format inventory;
- identification and correction of the enhanced Sentinel capture backend; and
- identification of the root-owned camera-stream resource conflict;
- 10/10 live Sentinel frames through the explicit GStreamer pipeline; and
- restoration of the paused QGC camera stream with a new active PID.

I classify camera-interface preflight as complete for both platforms. I do not
yet classify M2 full-node readiness as complete. Both updated ROS packages must
be rebuilt in isolated device workspaces and run in a camera-negative full-node
session. Any later full Sentinel node run will again require a controlled pause
and restoration of `camera-stream.service` because it exclusively owns the same
camera device.

## Claim boundary and thesis placement

- **Methodology:** exact camera services, bridge overlays, stream encodings,
  bounded probes, forced-recovery procedure, and exclusive-resource checks.
- **Results:** only the passed sample counts, geometries, encodings, payload
  consistency, and decoder statistics reported above.
- **Discussion:** the MPA-versus-ROS encoding difference, stale hires stream,
  90-second forced recovery, native OpenCV incompatibility, competing systemd
  camera consumer, and retained nonfatal container warnings.
- **Limitations:** small diagnostic samples, no saved reference frame, no color
  fidelity comparison, no inference, no lighter, and no long-duration capture.
- **Appendix:** immutable raw evidence, exact commands, hashes, service logs,
  and the final evidence index after Sentinel completion.
