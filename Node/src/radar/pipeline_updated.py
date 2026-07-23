import json
import os
import time
from datetime import datetime
from pathlib import Path
from queue import Empty, Full

import numpy as np
import paho.mqtt.client as mqtt_lib
import psutil
import socketio
import torch
from dotenv import load_dotenv
from . import config
from .processing.anirban_jpda_spatial import JPDATracker

# Debug level: 0 = quiet (only errors), 1 = all prints
DEBUG_LEVEL = 0


def debug_print(*args):
    if DEBUG_LEVEL >= 1:
        print(*args)


def f16(val):
    """Cast a float to half-precision (float16) to reduce MQTT payload size."""
    return float(np.float16(val))


# from .processing.anirban_jpda import JPDATracker

# from .processing.anirban_jpda import

# Hardware acceleration check: Choose between GPU (PyTorch) and optimized CPU (NumPy/OpenCV)
# if torch.cuda.is_available():
if config.USE_CUDA:
    from .processing.angle import angle_fft as angle_func
    from .processing.cfar import cfar_pytorch as cfar_func
    from .processing.clustering import centroid_process, dbscan_process
    from .processing.rdm import RangeDoppler
else:
    from .processing.angle_cpu import angle_cpu as angle_func
    from .processing.cfar_cpu import cfar_cpu as cfar_func
    from .processing.clustering_v3 import centroid_process, dbscan_process
    from .processing.rdm_v3 import RangeDoppler

node_root_dir = Path(__file__).resolve().parents[2]  # returns path to 'Node' directory
load_dotenv(node_root_dir / ".env", override=False)


def reconnect_socketio(server_url):
    """Helper to reconnect to the Socket.IO server."""
    sio = socketio.Client()
    try:
        sio.connect(server_url)
        debug_print(f"[SOCKET] Connected to {server_url}")
        return sio
    except Exception:
        return None


def create_3d_detection_map_spatial(cfar_data, angle_data, rdm_power):
    """
    Create a 3D detection map from 2D CFAR detections and angle estimates.
    Returns [range_m, doppler_mps, angle_deg] and detection power.
    """
    detection_mask = cfar_data > 0
    doppler_indices, range_indices = np.where(detection_mask)

    if len(doppler_indices) == 0:
        return np.array([]).reshape(0, 3), np.array([])

    angle_values = angle_data[doppler_indices, range_indices]

    range_values = range_indices.astype(np.float32) * config.RANGE_RES
    doppler_values = (
        doppler_indices.astype(np.float32) - config.DOPPLER_BINS / 2.0
    ) * config.DOPPLER_RES

    detection_coords = np.column_stack(
        [range_values, doppler_values, angle_values]
    ).astype(np.float32)
    detection_power = rdm_power[doppler_indices, range_indices]

    return detection_coords, detection_power


# average_frame_time = 0.1 #estimated frame time
def daq_process(raw_queue, daq_class, **daq_kwargs):
    """
    Generic DAQ process that handles frame capture and pushing to queue.
    Supports both live DataAcquisition and playback PlaybackDAQ.
    """
    try:
        psutil.Process(os.getpid()).cpu_affinity([1])
    except Exception as e:
        debug_print(f"[DAQ] Affinity failed: {e}")

    debug_print(f"[DAQ] Started on core 1 using {daq_class.__name__}")

    with daq_class(**daq_kwargs) as daq:
        last_frame_time = None
        frame_times = []
        frame_count = 0
        frame_avg = 100
        frame_rpl = 20

        while True:
            try:
                frame_data = daq.capture()

                current_time = time.time()
                if last_frame_time is not None:
                    frame_interval = current_time - last_frame_time
                    frame_times.append(frame_interval)
                    if len(frame_times) > frame_avg:
                        frame_times.pop(0)

                    frame_count += 1
                    if frame_count % frame_rpl == 0:
                        avg_interval = sum(frame_times) / len(frame_times)
                        fps = 1.0 / avg_interval if avg_interval > 0 else 0
                        print(
                            f"[DAQ] FPS: {fps:.2f} | Avg: {avg_interval * 1000:.1f}ms"
                        )

                last_frame_time = current_time

                try:
                    raw_queue.put_nowait(frame_data.copy())
                except Full:
                    pass
            except Exception as e:
                # Playback endings often through specialized exceptions
                if "End of playback" in str(e):
                    debug_print("[DAQ] Playback finished")
                    break
                debug_print(f"[DAQ] Error: {e}")
                time.sleep(0.1)


def rd_val_to_bin(range_val, vel_val):
    # 1. Convert range (m) to range bin
    range_bin = int(round(range_val / config.RANGE_RES))
    # range_bin = np.clip(range_bin, 0, config.RANGE_BINS-1)

    # 2. Convert velocity (m/s) to Doppler bin
    # The zero-velocity bin is at DOPPLER_BINS / 2 = 32
    doppler_bin = int(round((vel_val / config.DOPPLER_RES) + (config.DOPPLER_BINS / 2)))
    # doppler_bin = np.clip(doppler_bin, 0, config.DOPPLER_BINS-1)

    return range_bin, doppler_bin


def rd_bin_to_val(range_bin, vel_bin):
    vel_val = (vel_bin - config.DOPPLER_BINS / 2) * config.DOPPLER_RES
    range_val = range_bin * config.RANGE_RES

    return range_val, vel_val


current_frame_time = datetime.now()
previous_frame_time = datetime.now()


def processing_process(raw_queue, dbscan_queue, node_id, device=None, **cfar_kwargs):
    global current_frame_time, previous_frame_time

    """
    Signal processing pipeline: RDM -> CFAR -> Angle -> 3D Mapping -> DBSCAN.
    Outputs intermediate results to dbscan_queue for post-processing on another core.
    """
    try:
        psutil.Process(os.getpid()).cpu_affinity([2])
    except Exception as e:
        debug_print(f"[PROCESSING] Affinity failed: {e}")

    debug_print("[PROCESSING] Started on core 2")

    rdm = RangeDoppler(window="blackman", alpha=0.1)
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    debug_print(f"[PROCESSING] Using device: {device}")

    last_frame_time = None
    frame_times = []
    frame_count = 0
    frame_avg = 100
    frame_rpl = 20

    m_cfar_data = np.zeros((config.SLOW_TIME, config.FAST_TIME), dtype=np.float32)
    m_dbscan_data = np.zeros((config.SLOW_TIME, config.FAST_TIME), dtype=np.float32)
    m_angle_data = np.zeros((config.SLOW_TIME, config.FAST_TIME), dtype=np.float32)
    m_cluster_data = np.zeros((config.SLOW_TIME, config.FAST_TIME), dtype=np.float32)

    frame_num = 0

    # Default CFAR parameters if not provided
    cfar_params = {
        "guard_cells_doppler": 4,
        "guard_cells_range": 16,
        "training_cells_doppler": 6,
        "training_cells_range": 24,
        "threshold_factor": 10,
        "pad_doppler": 18,
        "pad_range": 50,
    }
    cfar_params.update(cfar_kwargs)

    while True:
        try:
            t0 = time.perf_counter_ns()
            # Non-blocking get with timeout to minimize wait time
            try:
                frame_data = raw_queue.get(timeout=1.0)
                previous_frame_time = current_frame_time
                current_frame_time = datetime.now()

            except Empty:
                time.sleep(0.001)  # Brief sleep if no data
                continue

            # Track frame processing time for FPS calculation
            current_time = time.time()
            if last_frame_time is not None:
                frame_interval = current_time - last_frame_time
                frame_times.append(frame_interval)
                if len(frame_times) > frame_avg:
                    frame_times.pop(0)

            last_frame_time = current_time

            # 1. Range-Doppler Processing
            t1 = time.perf_counter_ns()
            # TODO: why is dtype np.float32, should be np.uint16
            rdm.set_buffer(np.array(frame_data, dtype=np.int16))
            rdm_mag = rdm.process()
            rdm_display = rdm.get_display_map()
            rdm_power_db = rdm.get_power_db_map()
            clean_rdm = rdm.get_clean_rdm()

            t2 = time.perf_counter_ns()
            frame_num += 1

            # 2. CFAR Detection
            cfar_data = cfar_func(rdm_mag, device=device, **cfar_params)
            t3 = time.perf_counter_ns()

            # 3. Angle Estimation
            angle_data = angle_func(
                cfar_detections=cfar_data,
                clean_rdmap=clean_rdm,
                zero_pad_cols=124,
                device=device,
            )
            t4 = time.perf_counter_ns()

            # 4. 3D Detection Mapping
            detection_coords_3d, detection_power = create_3d_detection_map_spatial(
                cfar_data,
                angle_data,
                rdm_power_db,
            )

            # print(detection_coords_3d)

            # 5. Send pre-DBSCAN results to post-DBSCAN process
            # DBSCAN is executed on core 3 alongside centroid processing and JPDA
            dbscan_result = {
                "rdm_display": rdm_display,
                "cfar_data": cfar_data,
                "angle_data": angle_data,
                "detection_coords_3d": detection_coords_3d,
                "detection_power": detection_power,
                "cfar_shape": cfar_data.shape,
                "frame_num": frame_num,
                "current_frame_time": current_frame_time,
                "previous_frame_time": previous_frame_time,
                "node_id": node_id,
            }
            try:
                dbscan_queue.put_nowait(dbscan_result)
            except Full:
                pass

            # Print timing every 10 frames with FPS
            frame_count += 1
            if frame_count % frame_rpl == 0 and len(frame_times) > 0:
                avg_interval = sum(frame_times) / len(frame_times)
                fps = 1.0 / avg_interval if avg_interval > 0 else 0
                print(
                    f"[PROCESSING] FPS: {fps:.2f} | Avg: {avg_interval * 1000:.1f}ms | "
                    f"RDM: {(t2 - t1) // 1_000}us, CFAR: {(t3 - t2) // 1_000}us, "
                    f"ANGLE: {(t4 - t3) // 1_000}us"
                )
                debug_print(f"CFAR Detections: {np.sum(cfar_data > 0)}")

        except Exception as e:
            debug_print(f"[PROCESSING] Error: {e}")
            import traceback

            traceback.print_exc()


def post_dbscan_process(
    dbscan_queue,
    processed_queue,
    node_id,
    visualize_clusters_only=False,
):
    global current_frame_time, previous_frame_time

    """
    Post-DBSCAN processing: Centroid Processing -> JPDA -> Output Packing.
    Runs on core 3.
    """
    try:
        psutil.Process(os.getpid()).cpu_affinity([3])
    except Exception as e:
        debug_print(f"[POST-DBSCAN] Affinity failed: {e}")

    debug_print("[POST-DBSCAN] Started on core 3")

    jpda = JPDATracker(
        dt=0.1,
        detection_probability=config.DETECTION_PROBABILITY,
        clutter_density=config.CLUTTER_DENSITY,
        gating_threshold=config.GATING_THRESHOLD,
        measurement_noise_covariance=config.MEASUREMENT_NOISE,
        sigma_a=config.SIGMA_A,
        max_feasible_events=config.MAX_NUM_FEASIBLE_JOINT_EVENTS,
        threshold_init=config.THRESHOLD_INIT,
        threshold_hit_miss=config.THRESHOLD_HIT_MISS,
        threshold_merge=config.THRESHOLD_MERGE,
    )

    last_frame_time = None
    frame_times = []
    frame_count = 0
    frame_avg = 100
    frame_rpl = 20

    while True:
        try:
            t0 = time.perf_counter_ns()
            try:
                data = dbscan_queue.get(timeout=1.0)
            except Empty:
                time.sleep(0.001)
                continue

            # Unpack intermediate results from processing_process
            rdm_display = data["rdm_display"]
            cfar_data = data["cfar_data"]
            angle_data = data["angle_data"]
            detection_coords_3d = data["detection_coords_3d"]
            detection_power = data["detection_power"]
            cfar_shape = data["cfar_shape"]
            frame_num = data["frame_num"]
            current_frame_time = data["current_frame_time"]
            previous_frame_time = data["previous_frame_time"]
            node_id = data["node_id"]

            # Track frame processing time for FPS calculation
            current_time = time.time()
            if last_frame_time is not None:
                frame_interval = current_time - last_frame_time
                frame_times.append(frame_interval)
                if len(frame_times) > frame_avg:
                    frame_times.pop(0)

            last_frame_time = current_time

            t1 = time.perf_counter_ns()

            # 5. 3D DBSCAN - produce centroids with [range_m, doppler_mps, angle_rad]
            dbscan_data_2d, dbscan_angles, centroids, cluster_labels = dbscan_process(
                detection_coords_3d,
                cfar_shape,
                detection_power,
            )

            debug_print(centroids)

            # 6. Centroid Processing
            centroids_map, centroids_angles = centroid_process(centroids, cfar_shape)

            # Group raw detections by their DBSCAN cluster label
            # detection_coords_3d: [range_m, doppler_mps, angle_deg] of each CFAR detection
            # cluster_labels: per-detection label from DBSCAN (-1 = noise)
            detections_by_cluster: dict = {}
            if len(detection_coords_3d) > 0 and len(cluster_labels) > 0:
                for i, label in enumerate(cluster_labels):
                    if label < 0:  # skip noise points
                        continue
                    label = int(label)
                    if label not in detections_by_cluster:
                        detections_by_cluster[label] = []
                    coord = detection_coords_3d[i]
                    detections_by_cluster[label].append(
                        [f16(coord[0]), f16(coord[1]), f16(coord[2])]
                    )

            rda_centroids = {}
            for label, cdata in centroids.items():
                meas = cdata[0]

                # Centroids are already physical values:
                # [range_m, doppler_mps, angle_rad]
                range_val = meas[0]
                vel_val = meas[1]
                angle = meas[2]
                num_points = cdata[1]

                # Zero-Doppler removal in physical velocity units.
                if True:
                    # if abs(float(vel_val)) > config.DOPPLER_RES:
                    rda_centroids[label] = (
                        torch.tensor([range_val, vel_val, angle]),
                        num_points,
                    )
            filtered_centroids_map = np.zeros_like(centroids_map)
            filtered_centroids_angles = np.zeros_like(centroids_angles)
            for label, (tensor, num_points) in rda_centroids.items():
                range_val, vel_val, angle_rad = tensor.cpu().numpy()

                try:
                    range_bin, doppler_bin = rd_val_to_bin(range_val, vel_val)
                except TypeError:
                    debug_print(
                        "TYPE ERROR OCCURRED ====================================="
                    )
                    debug_print(range_val)

                # 3. Populate the visualization maps
                if (
                    0 <= range_bin < config.RANGE_BINS
                    and 0 <= doppler_bin < config.DOPPLER_BINS
                ):
                    filtered_centroids_map[doppler_bin, range_bin] = (
                        1.0  # Mark the spot
                    )
                    filtered_centroids_angles[doppler_bin, range_bin] = np.rad2deg(
                        angle_rad
                    )

            t2 = time.perf_counter_ns()

            # 7. JPDA Multi-Target Tracking
            confirmed_tracks, tentative_tracks = jpda.process(
                rda_centroids, current_frame_time
            )

            t3 = time.perf_counter_ns()

            # Create visualization maps for confirmed tracks

            all_tracks = (confirmed_tracks or []) + (tentative_tracks or [])

            debug_print(
                "Frame Time Difference:", current_frame_time - previous_frame_time
            )
            debug_print(
                f"Time: {current_frame_time} Confirmed: {len(confirmed_tracks)} | Tentative: {len(tentative_tracks)}"
            )

            def get_tracks_map(tracks):
                tracks_map = np.zeros_like(rdm_display, dtype=np.float32)
                tracks_angles = np.zeros_like(rdm_display, dtype=np.float32)

                for track in tracks:
                    tid = track["TrackID"]
                    state = track["State"]
                    misses = track["ConsecutiveMisses"]
                    detection = track["Detection"]
                    confirmed = track["Status"]

                    implied_detection = jpda.measurement_model.measurement_function(
                        state
                    ).flatten()

                    # range_val, vel_val, angle_rad = implied_detection

                    # range_bin, doppler_bin = rd_val_to_bin(range_val, vel_val)

                    # if (
                    #    0 <= range_bin < config.RANGE_BINS
                    #    and 0 <= doppler_bin < config.DOPPLER_BINS
                    # ):
                    #    tracks_map[doppler_bin, range_bin] = 1.0
                    #    tracks_angles[doppler_bin, range_bin] = np.rad2deg(
                    #        angle_rad
                    #    )

                    model = jpda.measurement_model
                    H = model.jacobian(state)

                    track_dict = jpda.tracks
                    gauss_state = track_dict[tid][-1]
                    state_covar = getattr(gauss_state, "covariance", None) or getattr(
                        gauss_state, "covar", None
                    )
                    if state_covar is None:
                        debug_print(
                            f"Warning: Could not get covariance from state of type {type(gauss_state)}"
                        )
                        continue
                    S = model.noise_covar + H @ state_covar @ H.T
                    debug_print(
                        f"Track {tid} {confirmed} at x={state[0]:.2f}, y={state[3]:.2f}, misses={misses}, avg det={detection}, implied det after correction = {implied_detection}, Distance: {jpda.detection_maha_sq_distance(detection, implied_detection, S)}"
                    )

                return tracks_map, tracks_angles

            confirmed_tracks_map, confirmed_tracks_angles = get_tracks_map(
                confirmed_tracks
            )
            tentative_tracks_map, tentative_tracks_angles = get_tracks_map(
                tentative_tracks
            )

            t4 = time.perf_counter_ns()

            # 8. Output Packing
            final_array = (
                filtered_centroids_map if visualize_clusters_only else rdm_display
            )
            final_cfar = (
                filtered_centroids_map if visualize_clusters_only else cfar_data
            )
            final_angles = (
                filtered_centroids_angles if visualize_clusters_only else angle_data
            )

            # Prepare cluster metadata for the visualizer
            clusters_meta = []
            if rda_centroids:
                for label, (centroid_vec, mass) in rda_centroids.items():
                    c = centroid_vec.cpu().numpy()

                    range_meters = float(c[0])
                    doppler_meters_per_sec = float(c[1])
                    angle_rad = float(c[2])

                    range_idx = range_meters / config.RANGE_RES
                    doppler_idx = (doppler_meters_per_sec / config.DOPPLER_RES) + (
                        config.DOPPLER_BINS / 2.0
                    )

                    cluster_label = int(label)
                    clusters_meta.append(
                        {
                            "id": cluster_label,
                            "range_idx": f16(range_idx),
                            "doppler_idx": f16(doppler_idx),
                            "range_m": f16(range_meters),
                            "doppler_mps": f16(doppler_meters_per_sec),
                            "angle_rad": f16(angle_rad),
                            "angle_deg": f16(float(np.rad2deg(angle_rad))),
                            "mass": int(mass),
                            "detections": detections_by_cluster.get(
                                cluster_label, []
                            ),
                        }
                    )

            # Format confirmed tracks for JSON serialization
            serialized_confirmed_tracks = []
            serialized_tentative_tracks = []

            def serialize_track(t):
                state = t["State"]
                implied_detection = jpda.measurement_model.measurement_function(
                    state
                ).flatten()

                track_json = {
                    "TrackID": int(t["TrackID"]),
                    "State": np.array(t["State"]).flatten().tolist(),
                    "StateCovariance": np.array(t["StateCovariance"]).tolist(),
                    "Age": int(t["Age"]),
                    "Status": str(t["Status"]),
                    "Hits": int(t["Hits"]),
                    "ConsecutiveMisses": int(t["ConsecutiveMisses"]),
                    "Last Detection": np.array(t["Detection"]).flatten().tolist()
                    if t["Detection"] is not None
                    else [],
                    "Implied Detection": np.array(implied_detection).flatten().tolist(),
                }

                return track_json

            if confirmed_tracks:
                for t in confirmed_tracks:
                    serialized_confirmed_tracks.append(serialize_track(t))

            for t in tentative_tracks:
                serialized_tentative_tracks.append(serialize_track(t))

            debug_print("tentative:", len(serialized_tentative_tracks))

            frame_timestamp_ms = int(time.time() * 1000)

            output_data = {
                "node_id": node_id,
                "timestamp": frame_timestamp_ms,
                "centroids": detection_coords_3d.astype(np.float32).tobytes()
                if len(detection_coords_3d) > 0
                else b"",
                "array": final_array.astype(np.float32).tobytes(),
                "angles": final_angles.astype(np.float32).tobytes()
                if final_angles is not None
                else b"",
                "cfar": final_cfar.astype(np.float32).tobytes()
                if final_cfar is not None
                else b"",
                "cluster_count": len(rda_centroids) if rda_centroids else 0,
                "clusters": clusters_meta,
                "rdm_centroids": centroids_map,
                "dbscan_2d": dbscan_data_2d,
                "confirmed_tracks": serialized_confirmed_tracks,
                "tentative_tracks": serialized_tentative_tracks,
            }

            # print(len(output_data["tentative_tracks"]))

            try:
                processed_queue.put_nowait(output_data)
            except Full:
                pass

            t5 = time.perf_counter_ns()

            # Print timing every 10 frames with FPS
            frame_count += 1
            if frame_count % frame_rpl == 0 and len(frame_times) > 0:
                avg_interval = sum(frame_times) / len(frame_times)
                fps = 1.0 / avg_interval if avg_interval > 0 else 0
                print(
                    f"[POST-DBSCAN] FPS: {fps:.2f} | Avg: {avg_interval * 1000:.1f}ms | "
                    f"Total: {(t5 - t0) // 1_000}us, CENTROID: {(t2 - t1) // 1_000}us, "
                    f"JPDA: {(t3 - t2) // 1_000}us, PACK: {(t5 - t4) // 1_000}us"
                )

        except Exception as e:
            debug_print(f"[POST-DBSCAN] Error: {e}")
            import traceback

            traceback.print_exc()


def socket_process(
    processed_queue,
    server_url,
    node_id,
    group_id="default",
    mqtt_host=None,
    mqtt_port=1883,
    mqtt_user=None,
    mqtt_pass=None,
):
    """
    Process that sends processed data to the visualization server and,
    when MQTT params are provided, also publishes per-frame cluster data
    to chirp/v1/group/<groupId>/frames/<nodeId> for the bird's-eye dashboard.
    """
    try:
        psutil.Process(os.getpid()).cpu_affinity([4])
    except Exception:
        pass

    debug_print(f"[SOCKET] Started on core 4, target: {server_url}")
    sio = None

    # MQTT frame publisher (optional)
    frame_topic = f"chirp/v1/group/{group_id}/frames/{node_id}"
    mqtt_client = None
    if mqtt_host:
        mqtt_client = mqtt_lib.Client(
            mqtt_lib.CallbackAPIVersion.VERSION2,
            client_id=f"frames-{node_id}",
            clean_session=True,
        )
        if mqtt_user:
            mqtt_client.username_pw_set(mqtt_user, mqtt_pass)
        try:
            mqtt_client.connect(mqtt_host, mqtt_port, keepalive=30)
            mqtt_client.loop_start()
            debug_print(f"[SOCKET] MQTT frame publisher connected → {frame_topic}")
        except Exception as exc:
            debug_print(
                f"[SOCKET] MQTT connect failed: {exc}; frame publishing disabled"
            )
            mqtt_client = None

    while True:
        # Non-blocking get with brief sleep fallback
        try:
            data = processed_queue.get_nowait()
        except Empty:
            time.sleep(0.001)
            continue

        # --- MQTT frame publish (never gated on SocketIO) ------------
        if mqtt_client is not None:
            clusters = data.get("clusters", [])
            if clusters:
                frame_payload = {
                    "schemaVersion": 1,
                    "timestampMs": data.get("timestamp", int(time.time() * 1000)),
                    "nodeId": node_id,
                    "groupId": group_id,
                    "clusters": [
                        {
                            "range_m": f16(c.get("range_m", 0.0)),
                            "angle_rad": f16(c.get("angle_rad", 0.0)),
                            "angle_deg": f16(c.get("angle_deg", 0.0)),
                            "doppler_mps": f16(c.get("doppler_mps", 0.0)),
                            "mass": c.get("mass", 1),
                            "detections": c.get("detections", []),
                        }
                        for c in clusters
                    ],
                    "tracks": [
                        {
                            "track_id": t["TrackID"],
                            "x": f16(t["State"][0]),
                            "y": f16(t["State"][2]),
                            "vx": f16(t["State"][1]),
                            "vy": f16(t["State"][3]),
                        }
                        for t in data.get("confirmed_tracks", [])
                    ],
                }
                try:
                    mqtt_client.publish(
                        frame_topic,
                        payload=json.dumps(frame_payload),
                        qos=0,
                        retain=False,
                    )
                except Exception as exc:
                    debug_print(f"[SOCKET] MQTT publish failed: {exc}")

        # --- SocketIO (best-effort; may fail if UI server is down) -----
        if sio is None or not sio.connected:
            sio = reconnect_socketio(server_url)
        if sio is not None:
            try:
                sio.emit(
                    "send_frame",
                    {
                        "node_id": node_id,
                        "timestamp_ms": data.get("timestamp", int(time.time() * 1000)),
                        "array": data.get("array", b""),
                        "angles": data.get("angles", b""),
                        "cfar": data.get("cfar", b""),
                        "cluster_count": data.get("cluster_count", 0),
                        "clusters": data.get("clusters", b""),
                        "confirmed_tracks": data.get("confirmed_tracks", b""),
                        "tentative_tracks": data.get("tentative_tracks", b""),
                        "confirmed_tracks_rd": data.get("confirmed_tracks_rd", b""),
                        "confirmed_tracks_angles": data.get(
                            "confirmed_tracks_angles", b""
                        ),
                    },
                )
            except Exception as e:
                debug_print(f"[SOCKET] Send error: {e}")
                sio = None
