# Chirp Node Architecture

This document describes the end-to-end architecture of the **Chirp** distributed
mmWave radar network, with the radar **Node** (Jetson Orin Nano + AWR2243 +
DCA1000EVM) as the primary focus. It is written as a prose reference: no math is
included, but every processing pipeline is broken down into explicit steps.

---

## 1. System Overview

Chirp is a time-synchronized distributed radar network that fuses detections
from several spatially separated radar nodes to track objects through multiple
fields of view and around line-of-sight obstructions. A single node cannot see
around clutter, but a network of nodes can, and the system relies on precise
time synchronization and spatial self-calibration to combine each node's
observations into a shared coordinate frame.

The physical system is composed of three roles:

1. **Radar Node(s)** — one Jetson Orin Nano per node, each connected to a TI
   AWR2243 mmWave radar board and a DCA1000EVM data-capture board.
2. **Fusion Center / Server** — a central machine hosting the MQTT broker, a
   PostgreSQL database, a calibration orchestrator, a message bridge, and a
   bird's-eye dashboard.
3. **Operator laptop** — used historically to trigger all nodes simultaneously;
   this role is now mostly absorbed by the server dashboard.

Communication across the network is orchestrated with the **MQTT** protocol. The
server broker is the rendezvous point that every node connects to. Device
addressing is normally done through **Tailscale** DNS names, so nodes do not
need to know each other's IP addresses.

Within this repository, the `Node/` directory contains everything a single node
needs: the real-time radar pipeline, hardware triggering, board setup scripts,
the visualization server, the lifecycle daemon, and the pull-based update
listener.

---

## 2. Hardware and Physical Setup

A single node is built from three pieces of hardware:

- **Jetson Orin Nano** — the compute host that runs the Python pipeline and the
  C trigger worker.
- **TI AWR2243** — the mmWave radar front end. It is a 3-transmit, 4-receive
  MIMO sensor that streams raw ADC samples over LVDS.
- **DCA1000EVM** — the data-capture board that receives the LVDS stream from the
  AWR2243, packetizes the ADC samples, and forwards them to the Jetson over
  Ethernet (UDP) on a fixed static IP.

The AWR2243 is programmed by the `setup_radar` executable (in
`Node/setup_radar/`), which uses TI's mmWaveLink API. The DCA1000 is configured
by the `DCA1000EVM_CLI_Control` utility (in `Node/DCA1000/SourceCode/Release/`).

The Jetson ↔ DCA1000 link is a dedicated Ethernet interface (typically
`enP8p1s0`) with the Jetson at `192.168.33.30/24` and the DCA1000 at
`192.168.33.180`. Because the DCA1000 does not answer ICMP ping, reachability is
checked through the ARP neighbor table rather than ping.

---

## 3. Repository Layout (Node)

The key directories inside `Node/` are:

| Path | Purpose |
| :--- | :--- |
| `src/` | All Python entry points for the pipeline, launcher, logger, and pull listener. |
| `src/radar/` | Radar pipeline, configuration, data acquisition, and calibration logic. |
| `src/radar/processing/` | Individual signal-processing stages (RDM, CFAR, angle, clustering, tracking). |
| `src/data_capture/` | Utilities for capturing and playing back raw radar frames. |
| `src/hardware_trigger/` | Legacy C trigger programs (local and networked GPIO pulse generators). |
| `src/hardware_trigger_mqtt/` | MQTT-driven trigger subsystem (Python client + real-time C worker). |
| `src/ui/` | The aiohttp + Socket.IO visualization server and its HTML template. |
| `scripts/` | Shell scripts and systemd unit files for board setup, radar reset, and services. |
| `setup_radar/` | Source for the AWR2243 board-configuration executable and `mmwaveconfig.txt`. |
| `DCA1000/` | DCA1000 EVM CLI source and configuration (`DCAconfig.json`). |
| `test/` | Interactive test runner and integration/capture/playback tests. |
| `nodeSetup/` | First-time dependency setup for the Jetson. |
| `data/`, `logs/` | Captured frame data and log output. |

---

## 4. The Real-Time Radar Pipeline

The core of the node is a **multi-process pipeline** defined in
`src/main.py` and implemented in `src/radar/pipeline_updated.py`. Four Python
processes are connected by bounded `multiprocessing.Queue` objects, and each
process is pinned to its own CPU core for predictable real-time behavior.

### 4.1 Process Topology

| Process | Function | Core | Input queue | Output queue |
| :--- | :--- | :--- | :--- | :--- |
| `DAQ` | Capture raw frames from the DCA1000. | 1 | — | `raw_queue` |
| `Processing` | RDM → CFAR → angle → 3D mapping. | 2 | `raw_queue` | `dbscan_queue` |
| `PostDBSCAN` | DBSCAN → centroid → JPDA → packing. | 3 | `dbscan_queue` | `processed_queue` |
| `Socket` | Publish to MQTT and push to the UI server. | 4 | `processed_queue` | — |

Queue sizes are small and bounded (`raw_queue` = 5, `dbscan_queue` = 5,
`processed_queue` = 2). Producers use non-blocking `put_nowait`, so if a
downstream stage falls behind, frames are dropped rather than letting memory
grow without bound.

The same topology is reproduced in `test/full_integration_test.py` for manual
testing.

### 4.2 Stage 1 — Data Acquisition (`daq_process` + `DataAcquisition`)

`src/radar/daq_new.py` receives UDP packets from the DCA1000 and reassembles
them into complete radar frames.

Steps:

1. Bind a UDP socket on `config.PORT` with a large receive buffer.
2. Receive packets into a reusable buffer using `recvfrom_into` (zero-copy).
3. Strip the 10-byte DCA header, which contains a 4-byte little-endian packet
   number and a 6-byte little-endian stream byte count.
4. Track packet loss by comparing consecutive packet numbers.
5. Copy payload bytes into a pre-allocated frame buffer using the stream byte
   count to locate each byte's position in the frame.
6. Handle packets that straddle a frame boundary by carrying the leftover bytes
   into the next frame's capture call.
7. When a full frame's worth of bytes has been written, return the frame as a
   one-dimensional signed 16-bit array and push a copy onto `raw_queue`.
8. Discard the first partial frame once, so processing starts on a clean frame
   boundary.

The same `DataAcquisition` class is used by the capture utility; a separate
`PlaybackDAQ` (`src/data_capture/playback.py`) mimics its `capture()` interface
by reading saved `.npy` files, which lets the entire downstream pipeline run
without hardware.

### 4.3 Stage 2 — Range-Doppler Map (`RangeDoppler` / `rdm_v3`)

The first signal-processing stage turns the raw, interleaved ADC frame into a
two-dimensional range-Doppler map. `src/radar/processing/rdm_v3.py` is the
optimized CPU implementation (a CUDA/PyTorch variant also exists and is selected
when `config.USE_CUDA` is true).

Steps:

1. **De-interleave** the flat ADC array into a radar cube with dimensions
   (channels, slow-time, fast-time), where channels span the three transmitters
   times the four receivers. This is done with precomputed index arrays and a
   single scatter operation.
2. **Window** the data along the fast-time (range) and slow-time (Doppler)
   dimensions using a Blackman window to suppress spectral leakage.
3. **FFT** along both the fast-time and slow-time axes using pre-planned
   `pyFFTW` transforms, producing a range-Doppler spectrum per channel.
4. **Shift** the Doppler axis so zero velocity sits at the center bin.
5. **Adaptive background subtraction** removes static clutter: a running
   background estimate (updated with an IIR/recursive filter) is subtracted from
   the current frame so only moving targets remain. The update is gated so
   target cells do not pollute the background estimate.
6. **Average power across channels** into a single slow-time × fast-time power
   map.
7. Convert power to **dB**, and produce a normalized 0–255 **display map** for
   the visualizer.

The clean (clutter-removed) complex cube is retained as input to angle
estimation.

### 4.4 Stage 3 — CFAR Detection (`cfar_cpu`)

`src/radar/processing/cfar_cpu.py` applies a two-dimensional cell-averaging
constant false alarm rate (CA-CFAR) detector to the range-Doppler power map to
find cells that stand out above the local noise floor.

Steps:

1. Define a guard window (cells immediately around the cell under test that are
   excluded) and a training window (surrounding cells used to estimate noise).
2. Pad the map with reflected borders so edge cells can be tested.
3. Compute the sum of the outer (training + guard) window and the inner (guard)
   window using OpenCV box filters, which are SIMD/NEON-accelerated.
4. Subtract the inner sum from the outer sum and divide by the training-cell
   count to obtain the local noise estimate.
5. Multiply the noise estimate by the threshold factor to get a per-cell
   threshold.
6. Mark every cell whose power exceeds its threshold as a detection, producing a
   binary detection map.

### 4.5 Stage 4 — Angle Estimation (`angle_cpu`)

`src/radar/processing/angle_cpu.py` estimates the angle-of-arrival of each CFAR
detection using FFT beamforming.

Steps:

1. Find the slow-time / fast-time coordinates of every CFAR detection.
2. Gather the complex values across the receive antennas at each detection
   location.
3. Place the antenna samples into a zero-padded vector and take an FFT along the
   antenna dimension (256 bins).
4. Shift the spectrum so the bore-sight (zero angle) sits in the middle.
5. Find the peak bin of the spectrum.
6. Map the peak bin to a sine-of-angle value, clip it to the valid range, and
   convert to degrees.
7. Scatter the resulting angle back into a matrix aligned with the CFAR
   detections.

### 4.6 Stage 5 — 3D Detection Mapping

`create_3d_detection_map_spatial()` converts the 2D CFAR detection map and the
angle matrix into a list of physical 3D detection points.

Steps:

1. Take the binary CFAR mask and extract the (Doppler, range) indices of every
   detection.
2. Convert each range index to meters using the range resolution.
3. Convert each Doppler index to meters per second, accounting for the
   zero-velocity center bin.
4. Look up the angle value at each detection location.
5. Stack the results into an array of `[range, Doppler, angle]` triplets, plus a
   per-detection power value.

These pre-clustering detections are packaged into a dictionary and sent to the
`PostDBSCAN` process through `dbscan_queue`.

### 4.7 Stage 6 — 3D DBSCAN Clustering (`dbscan_process` / `DBSCAN3D`)

`src/radar/processing/clustering_v3.py` groups the 3D detections into clusters
that represent individual objects.

Steps:

1. Run density-based clustering (DBSCAN) over the `[range, Doppler, angle]`
   points using a Mahalanobis distance metric, with the measurement-noise
   standard deviations used to weight each axis.
2. Set the clustering radius and minimum samples per cluster from configuration
   (`eps` = 3.0, `MIN_SAMPLES` = 5).
3. Optionally discard clusters whose maximum power exceeds a threshold (a
   heuristic for filtering very strong returns).
4. Compute a representative **centroid** for each cluster, again in
   `[range, Doppler, angle]` space.
5. Scatter cluster labels and angles back into 2D maps for visualization.
6. Zero out the zero-Doppler row so stationary returns are excluded.

### 4.8 Stage 7 — Centroid Processing (`centroid_process`)

Steps:

1. Filter the DBSCAN centroids to keep only clusters with non-zero mass.
2. Convert each centroid's physical `[range, Doppler, angle]` back to integer
   bin indices.
3. Populate a centroid map (for visualization) and an angle map at those bin
   locations.
4. Zero out the zero-Doppler row again for consistency.

The resulting centroids (as tensors plus point counts) are handed to the
tracker.

### 4.9 Stage 8 — JPDA Multi-Target Tracking (`JPDATracker`)

`src/radar/processing/anirban_jpda_spatial.py` implements multi-target tracking
on top of the Stone Soup tracking library.

Details:

- The **motion model** is a constant-velocity model with a state vector ordered
  as `[x, velocity-x, y, velocity-y]`.
- The **measurement model** is nonlinear and maps that state to
  `[range, Doppler, angle]`. Because the mapping is nonlinear, an Extended
  Kalman Filter (EKF) predictor and updater are used.
- Data association is performed with **JPDA** (Joint Probabilistic Data
  Association), which probabilistically assigns detections to tracks rather than
  committing to a single hard match.
- The tracker is configured with detection probability, clutter density, a
  gating threshold, a measurement-noise covariance, and an acceleration-noise
  term.

Steps per frame:

1. Feed the current set of centroids (and their timestamps) into the tracker.
2. The tracker predicts each existing track forward in time.
3. Candidate detections are gated against each track using a Mahalanobis
   distance.
4. Joint association probabilities are computed and used to update each track.
5. Tracks are classified as **tentative** or **confirmed** based on hit/miss
   history, initialization thresholds, and merge thresholds.
6. The confirmed and tentative track sets (state, covariance, age, hits, misses,
   last detection) are returned.

A track's implied measurement (the measurement that would be produced by its
current state) is computed and included in the output for downstream
diagnostics.

### 4.10 Stage 9 — Output Packing and Publishing (`socket_process`)

The final process serializes the results and sends them out over two independent
channels.

Steps:

1. Pull a processed frame from `processed_queue`.
2. **MQTT publish** (never gated on the UI server being up): build a frame
   payload containing the cluster list (range, angle, Doppler, mass, detections)
   and the confirmed tracks (track ID, position, velocity), all cast to
   half-precision to reduce payload size, and publish it to
   `chirp/v1/group/<groupId>/frames/<nodeId>`.
3. **Socket.IO emit** (best-effort): connect or reconnect to the visualization
   server at `SERVER_URL`, then emit a `send_frame` event carrying the display
   array, angle map, CFAR map, cluster metadata, and confirmed/tentative tracks.
4. If either channel fails, log and retry on the next frame.

This separation means frame data reaches the Fusion Center dashboard over MQTT
independently of whether a local browser is watching the node visualizer.

---

## 5. Data Structures and Flow

The pipeline moves two kinds of objects through its queues:

1. **Raw frames** (`raw_queue`): a flat signed 16-bit NumPy array of ADC
   samples, one frame per item.
2. **Intermediate results** (`dbscan_queue`): a dictionary carrying the display
   map, CFAR map, angle map, 3D detection coordinates, detection powers, frame
   number, timestamps, and node ID.
3. **Final output** (`processed_queue`): a dictionary with serialized bytes for
   the display array, angles, and CFAR map, plus JSON-ready cluster and track
   lists.

End-to-end flow through a single frame:

1. DCA1000 → UDP packets → `DataAcquisition.capture()` → raw frame.
2. `DAQ` process → `raw_queue`.
3. `Processing` process → range-Doppler map → CFAR detections → angle estimates
   → 3D detections → `dbscan_queue`.
4. `PostDBSCAN` process → DBSCAN clusters → centroids → JPDA tracks → packed
   output → `processed_queue`.
5. `Socket` process → MQTT topic + Socket.IO event.

---

## 6. Radar Configuration

`src/radar/config.py` centralizes all radar and pipeline parameters.

Key dimension parameters:

- `FAST_TIME` = 512 — the number of ADC samples per chirp, which also equals the
  number of range bins.
- `SLOW_TIME` = 64 — the number of chirps per frame, which also equals the number
  of Doppler bins.
- `RX` = 4, `TX` = 3 — the MIMO antenna counts.
- `IQ` = 2 and 2 bytes per sample — the ADC output format.

Key physical parameters:

- Sampling rate of 10 MHz, carrier frequency of 76 GHz, and a chirp slope of
  83 terahertz per second.
- The chirp ramp duration, frame period, and idle time feed into derived
  quantities such as the range resolution, Doppler resolution, maximum
  unambiguous range, and maximum unambiguous velocity.

Key processing parameters:

- Measurement-noise standard deviations for range, Doppler, and azimuth, which
  feed both the DBSCAN weighting and the JPDA measurement-noise covariance.
- DBSCAN minimum samples.
- JPDA detection probability, clutter density, gating threshold, and the maximum
  number of feasible joint events.
- Track management thresholds for initialization, hit/miss, and merging.

The board-level configuration is separate: `setup_radar/mmwaveconfig.txt` holds
the AWR2243 profile, chirp, and frame settings (start frequency, ADC samples,
dig output rate, chirp slope, transmit enable patterns, frame periodicity, and
the hardware-trigger selection). It is consumed by the `setup_radar` executable
at boot.

---

## 7. Hardware Triggering

Radar frames must be captured at the same instant on every node. Chirp achieves
this with a hardware trigger that pulses a GPIO line at a fixed period, aligned
to a network-agreed absolute epoch.

### 7.1 Legacy Triggers (`src/hardware_trigger/`)

Two C programs predate the MQTT trigger:

- `local_trigger` — emits GPIO pulses locally at a fixed period.
- `networked_trigger` — an earlier attempt at distributed triggering.

Both are retained for compatibility and are built on demand by the test runner.

### 7.2 MQTT Trigger Subsystem (`src/hardware_trigger_mqtt/`)

This is the current distributed triggering approach. It is explicitly decoupled
so that **time synchronization** (periodic ticks) and **calibration**
(on-demand solver runs) operate independently.

Components:

- `trigger_worker` (C) — a real-time GPIO pulse generator. It uses `SCHED_FIFO`
  scheduling, locks memory, and pins itself to a CPU core. It sleeps with an
  absolute real-time clock until a target epoch, then toggles a GPIO pin at a
  configurable period (default 50 ms), either for a fixed pulse count or
  forever. It emits `STATUS:` lines on stdout (ARMED, STARTED, PULSE, DONE) that
  the parent process parses.
- `mqtt_trigger_client.py` (Python) — subscribes to MQTT commands, launches and
  supervises the worker, publishes presence/state/ack messages, and applies
  calibration results.
- `command_cache.py` — a TTL-based cache that deduplicates command IDs to
  protect against MQTT command replay.

Time sync vs. calibration:

| Concern | Publisher | Topic | Frequency |
| :--- | :--- | :--- | :--- |
| Time sync | `chirp-timesync` service | `chirp/v1/group/<gid>/capture/start` | every 10 s |
| Calibration | `chirp-calibration` service | `chirp/v1/group/<gid>/capture/start` | on demand |

The node distinguishes the two by inspecting `captureConfig.calibration`:
`false` means a time-sync tick, `true` means a calibration run.

Trigger state machine:

1. **IDLE** — initial state, no pulses being emitted.
2. **LIVE CAPTURE** — entered on the first time-sync tick; pulses are emitted
   continuously.
3. **CALIBRATION BURST** — entered on a calibration `capture/start`; a fixed
   burst of frames is captured for the calibration solver.
4. Return to **LIVE** after publishing `calibration/done`, or to **IDLE** on an
   error or explicit stop.

New-node join flow:

1. Publish presence (`online`).
2. Publish state (`idle`).
3. Receive a time-sync `capture/start` within about 10 seconds.
4. Begin hardware frame collection immediately (no calibration required; an
   identity calibration is applied until a real result arrives).
5. Optionally participate in a later calibration run and apply the returned
   calibration matrix.

---

## 8. Radar Board Setup and Recovery

The AWR2243 and DCA1000 must be initialized before frames can be captured.

### 8.1 `setup_radar`

`setup_radar/` builds a C executable that programs the AWR2243 through the
mmWaveLink API using `mmwaveconfig.txt`. `start_radar.sh` runs it first to
configure the front end.

### 8.2 DCA1000 CLI

The DCA1000 is configured with `DCA1000EVM_CLI_Control` using `DCAconfig.json`.
The command sequence is:

1. Configure the FPGA: `DCA1000EVM_CLI_Control fpga DCAconfig.json`.
2. Configure record mode: `DCA1000EVM_CLI_Control record DCAconfig.json`.
3. Begin recording: `DCA1000EVM_CLI_Control start_record DCAconfig.json -q`.

### 8.3 Helper Scripts

- `scripts/start_radar.sh` — brings up the Ethernet interface, sets large socket
  buffers, registers the RF library path, runs `setup_radar`, and configures and
  starts the DCA1000.
- `scripts/reset_radar.sh` — kills `setup_radar`, resets the DCA1000 FPGA, and
  re-runs the reset command (the first option to try when nothing works).
- `scripts/recover_dca_link.sh` — recovers the Jetson ↔ DCA1000 Ethernet link
  without a physical replug by resetting the NIC, re-applying the static IP,
  flushing the neighbor cache, reconnecting via NetworkManager, and disabling
  Energy-Efficient Ethernet.

---

## 9. Node Lifecycle Management

### 9.1 `node_launcher.py`

`src/node_launcher.py` is a persistent daemon that listens for MQTT lifecycle
commands and manages the radar pipeline and FPGA. It does not run the pipeline
directly; instead it starts/stops the pipeline subprocess and the UI server.

MQTT topics:

- **Subscribed** — `chirp/v1/group/<group>/node/<node>/command`, with actions
  `start_pipeline`, `stop_pipeline`, `start_radar`, `reset_radar`,
  `start_trigger`, `stop_trigger`, and `status`.
- **Published** — `chirp/v1/presence/<node>` (online/offline, retained) and
  `chirp/v1/group/<group>/node/<node>/status` (pipeline state + uptime).

The `PipelineManager` class wraps a `subprocess.Popen` for the pipeline and
shell-script invocations for the FPGA. A background status loop publishes status
once per second, and a last-will message marks the node offline if it
disconnects unexpectedly.

### 9.2 systemd Services

Two services run the node automatically at boot:

- `chirp-launcher.service` — runs `node_launcher.py` as root, restarts on
  failure, and uses `systemd` sandboxing (read-only home, writable paths limited
  to logs, src, scripts, setup_radar, and DCA1000).
- `chirp_pull_listener.service` — runs the pull listener (see below).

### 9.3 Pull Listener (`pull_listener.py`)

`src/pull_listener.py` is a small HTTP service (default port 5055) that lets the
Fusion Center trigger a `git`-based redeploy of the node.

Deploy steps (on a `POST /pull`):

1. Mark the repo as a safe directory for git.
2. Stop the launcher service.
3. Fetch the latest code from the configured branch (using a GitHub token).
4. Hard-reset the working tree to the remote branch.
5. Clean untracked files.
6. Restart the launcher service.
7. Report the service's active state back to the caller.

The endpoint requires a bearer token when configured, and a deploy lock prevents
concurrent deploys.

### 9.4 Logger (`logger.py`)

`src/logger.py` is a tiny HTTP server (default port 5003) that streams
`journalctl` output for the `chirp-launcher` and `chirp_pull_listener` services
to a web page using server-sent events, so operators can watch node logs in a
browser without SSH.

---

## 10. Visualization Server (`src/ui/server.py`)

The node also runs a local visualization server (default port 5001) built on
`aiohttp` and `socketio`. It receives `send_frame` events from the pipeline and
renders them in a browser.

Processing steps per frame:

1. Parse the byte payload into the display array, angle map, and CFAR map.
2. Extract detections (positions, velocities, angles) from the CFAR and angle
   maps.
3. Convert the range-Doppler display array into a color-mapped image (normalize,
   resize, rotate, apply a colormap).
4. Overlay confirmed tracks if the optional track maps are present.
5. Package track data (confirmed and tentative) for the frontend.
6. Encode the image as base64 JPEG and emit a `radar_plot` event to the browser.

Heavy CPU work is offloaded to a thread via `asyncio.to_thread` so the event
loop stays responsive.

---

## 11. Data Capture, Playback, and Testing

`test/run_tests.sh` is an interactive CLI (run as root) with six options:

1. **Full Integration Test** — initialize the radar and run the live pipeline
   with the UI.
2. **Data Capture** — capture raw and processed frames to disk
   (`test/data/raw`, `test/data/rdm`).
3. **Playback Test** — replay saved raw frames through the pipeline.
4. **Convert Playback Data to `.mat`** — convert saved `.npy` frames into a
   MATLAB `.mat` file.
5. **Reset Radar** — run `reset_radar.sh` and clear the initialization lock.
6. **Exit**.

Supporting modules:

- `test/capture_data.py` — CLI for capturing frames and converting to `.mat`.
- `test/playback_test.py` — runs the pipeline against `PlaybackDAQ`.
- `test/full_integration_test.py` — mirrors `main.py`'s four-process topology.
- `src/data_capture/capture.py` — `CaptureSession`, which captures frames and
  optionally saves raw and RDM data.
- `src/data_capture/playback.py` — `PlaybackDAQ`, which mimics the live DAQ
  interface from disk.

The test runner also builds the radar setup executable, the legacy triggers, and
the MQTT trigger stack on demand.

---

## 12. Distributed System Context

The node does not operate in isolation. It connects to a central server stack
(defined in `Server/docker-compose.yml`) through MQTT.

### 12.1 Server Services

| Service | Role |
| :--- | :--- |
| `nanomq` | The MQTT broker (port 1883), with per-node authentication. |
| `postgres` | PostgreSQL database that persists messages. |
| `bridge` | Subscribes to MQTT topics and inserts messages into Postgres. |
| `calibration` | Orchestrates multi-node self-calibration and publishes results. |
| `dashboard` | Bird's-eye x-y plot of fused targets (port 5002). |

### 12.2 MQTT Topic Map

The bridge consumes and persists these topics:

- `chirp/v1/group/+/capture/start` → capture commands.
- `chirp/v1/group/+/calibration/frame/+` → per-node calibration frames.
- `chirp/v1/group/+/calibration/done/+` → calibration-complete signals.
- `chirp/v1/group/+/frames/+` → live per-frame clusters and tracks.
- `chirp/v1/group/+/node/+/status` → node status (to record node IPs).

The node-side producers and consumers were described in Sections 4.10, 7.2, and
9.1.

### 12.3 Time Synchronization (`Time-Synchronization/`)

All nodes must share a common clock so frames captured "simultaneously" are
aligned in time. Chirp uses **Chrony NTP** with one master Jetson and multiple
slave Jetsons.

Steps:

1. Run `CHRONY_SETUP.sh` on the master and select the master/server role.
2. Run it on each slave and select the client role, pointing at the master's IP.
3. Verify with `chronyc tracking` and `chronyc sources -v`.
4. Optionally collect and analyze clock offsets with the provided Python
   scripts to quantify worst-case inter-device offset.

The MQTT trigger subsystem uses the resulting synchronized clock to agree on an
absolute epoch (in milliseconds) at which every node fires its first GPIO pulse.

---

## 13. End-to-End Life of a Frame

Putting it all together, the full path of a single radar frame across the
network is:

1. **Clock alignment** — Chrony keeps all nodes on a common clock; the timesync
   service publishes a `capture/start` tick with a future epoch.
2. **Simultaneous trigger** — each node's `trigger_worker` waits for that epoch,
   then pulses the AWR2243's hardware trigger line at the agreed period.
3. **Capture** — each AWR2243 streams ADC samples over LVDS to its DCA1000,
   which packetizes them and sends them over UDP to the Jetson.
4. **Board streaming** — `DataAcquisition.capture()` reassembles UDP packets
   into a complete raw frame.
5. **Signal processing** — the `Processing` process computes a range-Doppler
   map, runs CFAR, estimates angles, and forms 3D detections.
6. **Detection-to-object** — the `PostDBSCAN` process clusters detections into
   centroids and tracks them with JPDA.
7. **Publish** — the `Socket` process publishes clusters and tracks to MQTT and
   emits the frame to the local visualizer.
8. **Persistence** — the server `bridge` subscribes to the frame topic and
   writes it to PostgreSQL.
9. **Fusion** — the `dashboard` reads frames from all nodes, applies each node's
   calibration transform, and renders fused targets on a shared bird's-eye plot.
10. **Calibration loop** — periodically, the `calibration` service triggers a
    burst capture on all nodes, collects their matched detections of a common
    target, solves for the relative pose between nodes, and publishes the
    calibration result that each node applies to its live frames.

---

## 14. Calibration and Fusion (Algorithmic Summary)

The multi-node fusion and calibration logic is adapted from the MATLAB reference
pipeline and described conceptually in the project `README.md`. In prose, the
stages are:

1. **Range-Doppler-Angle processing** — raw ADC is transformed into
   range-Doppler-angle point clouds per frame using FFTs, static-clutter
   removal, and a two-dimensional OS-CFAR detector.
2. **Tracking** — DBSCAN clusters the point clouds into centroids, and an
   Extended Kalman Filter tracks them over time. A DBSCAN variant is tuned so
   that, for human targets within roughly 10 meters, the cluster center
   represents the torso rather than the limbs, keeping the downstream point
   target model valid.
3. **Self-calibration** — each node observes a common target, and the
   observations are matched to estimate the relative rotation and translation
   between nodes.
4. **One-shot fusion** — centroids from multiple perspectives are matched with
   the Hungarian algorithm, then combined with a regularized non-linear
   least-squares optimization (using human-motion priors) into a single fused
   state and covariance estimate.

Within this repository, the node-side pieces of this are
`src/radar/calibration.py` (a `CalibrationManager` that collects per-node
detections across common frames, plus a `closed_form_calibration` routine), the
server-side `Server/calibration/` orchestrator, and the `Server/dashboard/`
fusion display.
