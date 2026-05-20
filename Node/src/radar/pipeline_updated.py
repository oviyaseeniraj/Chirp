import json
import logging
import os
import sys
import threading
import time
import numpy as np
import psutil
import socketio
import torch
from datetime import datetime 
from queue import Empty, Full
from supabase import create_client
from dotenv import load_dotenv
from pathlib import Path

import paho.mqtt.client as mqtt_lib

from . import config

from .processing.anirban_jpda_spatial import JPDATracker
#from .processing.anirban_jpda import JPDATracker

#from .processing.anirban_jpda import 

# Hardware acceleration check: Choose between GPU (PyTorch) and optimized CPU (NumPy/OpenCV)
# if torch.cuda.is_available():
if config.USE_CUDA:
    from .processing.rdm import RangeDoppler
    from .processing.cfar import cfar_pytorch as cfar_func
    from .processing.angle import angle_fft as angle_func
    from .processing.clustering import dbscan_process, centroid_process
else:
    from .processing.rdm_updated import RangeDoppler
    from .processing.cfar_cpu import cfar_cpu as cfar_func
    from .processing.angle_cpu import angle_cpu as angle_func
    from .processing.clustering_updated import dbscan_process, centroid_process

node_root_dir = Path(__file__).resolve().parents[2]  # returns path to 'Node' directory
load_dotenv(node_root_dir / ".env", override=False)

def init_supabase_client():
    """
    Initialize Supabase once from env vars.
    Returns (client OR None, db_enabled_bool).
    """
    db_write_enabled = os.getenv("DB_WRITE_ENABLED", "false").strip().lower() == "true"
    if db_write_enabled is False:
        print("[DB] Writing to Supabase is disabled")
        return None, False

    supabase_url = os.getenv("SUPABASE_URL")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not service_role_key:
        print("[DB] Missing Supabase URL or Service Role Key in .env file")
        return None, False

    try:
        client = create_client(supabase_url, service_role_key)
        print("[DB] Supabase client initialized")
        return client, True

    except Exception as e:
        print(f"[DB] Supabase client initialization failed: {e}")
        return None, False

def reconnect_socketio(server_url):
    """Helper to reconnect to the Socket.IO server."""
    sio = socketio.Client()
    try:
        sio.connect(server_url)
        print(f"[SOCKET] Connected to {server_url}")
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


#average_frame_time = 0.1 #estimated frame time
def daq_process(raw_queue, daq_class, **daq_kwargs):
    """
    Generic DAQ process that handles frame capture and pushing to queue.
    Supports both live DataAcquisition and playback PlaybackDAQ.
    """
    try:
        psutil.Process(os.getpid()).cpu_affinity([1])
    except Exception as e:
        print(f"[DAQ] Affinity failed: {e}")
    
    print(f"[DAQ] Started on core 1 using {daq_class.__name__}")

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
                        print(f"[DAQ] FPS: {fps:.2f} | Avg: {avg_interval * 1000:.1f}ms")

                last_frame_time = current_time

                try:
                    raw_queue.put_nowait(frame_data.copy())
                except Full:
                    pass
            except Exception as e:
                # Playback endings often through specialized exceptions
                if "End of playback" in str(e):
                    print("[DAQ] Playback finished")
                    break
                print(f"[DAQ] Error: {e}")
                time.sleep(0.1)


def rd_val_to_bin(range_val,vel_val):
    # 1. Convert range (m) to range bin
    range_bin = int(round(range_val / config.RANGE_RES))
    #range_bin = np.clip(range_bin, 0, config.RANGE_BINS-1)
    
    # 2. Convert velocity (m/s) to Doppler bin
    # The zero-velocity bin is at DOPPLER_BINS / 2 = 32
    doppler_bin = int(round((vel_val / config.DOPPLER_RES) + (config.DOPPLER_BINS / 2)))
    #doppler_bin = np.clip(doppler_bin, 0, config.DOPPLER_BINS-1)

    return range_bin, doppler_bin

def rd_bin_to_val(range_bin,vel_bin):
    vel_val = (vel_bin - config.DOPPLER_BINS/2) * config.DOPPLER_RES
    range_val = range_bin * config.RANGE_RES

    return range_val, vel_val


current_frame_time = datetime.now()
previous_frame_time = datetime.now()
def processing_process(raw_queue, processed_queue, node_id, calib_queue=None, device=None, save_calibration=True, visualize_clusters_only=False, **cfar_kwargs):
    global current_frame_time, previous_frame_time
    
    """
    Signal processing pipeline: RDM -> CFAR -> Angle -> 3D Mapping -> DBSCAN -> Centroids.
    """
    try:
        psutil.Process(os.getpid()).cpu_affinity([2])
    except Exception as e:
        print(f"[PROCESSING] Affinity failed: {e}")
        
    print("[PROCESSING] Started on core 2")

    rdm = RangeDoppler(window="blackman", alpha=0.1)
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[PROCESSING] Using device: {device}")

    #assume sampling at 15 HZ
    jpda = JPDATracker(
    dt=0.1,                          # 10Hz sampling #unused
    detection_probability=config.DETECTION_PROBABILITY,       # MATLAB Pd
    clutter_density=config.CLUTTER_DENSITY,            # Clutter model
    gating_threshold=config.GATING_THRESHOLD,           # Gating
    measurement_noise_covariance=config.MEASUREMENT_NOISE, #measurement noise covariance matrix (range, doppler, angle noise)
    sigma_a=config.SIGMA_A,                     # Process noise #variance of human acceleration
    max_feasible_events=config.MAX_NUM_FEASIBLE_JOINT_EVENTS,
    #multi-track parameters
    threshold_init = config.THRESHOLD_INIT,
    threshold_hit_miss = config.THRESHOLD_HIT_MISS,
    threshold_merge = config.THRESHOLD_MERGE,
    #process_noise = config.PROCESS_NOISE
    )

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
        'guard_cells_doppler': 4,
        'guard_cells_range': 16,
        'training_cells_doppler': 6,
        'training_cells_range': 24,
        'threshold_factor': 10,
        'pad_doppler': 18,
        'pad_range': 50
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

            #print(detection_coords_3d)

            # 5. 3D DBSCAN - produce centroids with [range_m, doppler_mps, angle_rad]
            dbscan_data_2d, dbscan_angles, centroids = dbscan_process(
                detection_coords_3d,
                cfar_data.shape,
                detection_power,
            )
            t5 = time.perf_counter_ns()

            # 6. Centroid Processing
            centroids_map, centroids_angles = centroid_process(centroids, cfar_data.shape)
                        
            rda_centroids = {}
            for label, data in centroids.items():
                meas = data[0]

                # Centroids are already physical values:
                # [range_m, doppler_mps, angle_rad]
                range_val = meas[0]
                vel_val = meas[1]
                angle = meas[2]
                num_points = data[1]

                # Zero-Doppler removal in physical velocity units.
                if True:
                # if abs(float(vel_val)) > config.DOPPLER_RES:
                    rda_centroids[label] = (
                        torch.tensor([range_val, vel_val, angle]),
                        num_points,
                    )
            filtered_centroids_map = np.zeros_like(centroids_map)
            filtered_centroids_angles = np.zeros_like(centroids_angles)
            for label, (tensor,num_points) in rda_centroids.items():
                range_val, vel_val, angle_rad = tensor.cpu().numpy()
                
                try:
                    range_bin, doppler_bin = rd_val_to_bin(range_val, vel_val)
                except TypeError:
                    print("TYPE ERROR OCCURRED =====================================")
                    print(range_val)

                # 3. Populate the visualization maps
                if 0 <= range_bin < config.RANGE_BINS and 0 <= doppler_bin < config.DOPPLER_BINS:
                    filtered_centroids_map[doppler_bin, range_bin] = 1.0  # Mark the spot
                    filtered_centroids_angles[doppler_bin, range_bin] = np.rad2deg(angle_rad)
                    
            t6 = time.perf_counter_ns()

            #6. =============================== JPDA Multi-Target Tracking ===========================================
            #current_timestamp = datetime.now()
            #print(f"# of prefiltered detections: {len(rda_centroids)}")
            confirmed_tracks, tentative_tracks = jpda.process(rda_centroids, current_frame_time)

            t7 = time.perf_counter_ns()

            # Create visualization maps for confirmed tracks
            confirmed_tracks_map = np.zeros_like(rdm_display, dtype=np.float32)
            confirmed_tracks_angles = np.zeros_like(rdm_display, dtype=np.float32)

            #jpda.print_tracker_status()

            all_tracks = (confirmed_tracks or []) + (tentative_tracks or [])

            # print("Frame Time Difference:", current_frame_time - previous_frame_time)
            # print(f"Time: {current_frame_time} Confirmed: {len(confirmed_tracks)} | Tentative: {len(tentative_tracks)}")
            
            for track in all_tracks:
                tid = track['TrackID']
                state = track['State'] # [x, vx, y, vy]
                misses = track['ConsecutiveMisses']
                detection = track['Detection'] # [range (m), velocity (m/s), angle (rad)]
                confirmed = track['Status']

                #TODO: Convert the state to the 
                implied_detection = jpda.measurement_model.measurement_function(state).flatten()

                #print(implied_detection)
                #print(detection)

                # --- Convert physical units back to RDM bins ---
                range_val, vel_val, angle_rad = implied_detection

                #print("Difference")
                #print(maha_distance(np.array([range_val, vel_val, angle_rad]), detection, jpda.measurement_model.noise_covar))

                #try: 
                range_bin, doppler_bin = rd_val_to_bin(range_val, vel_val)
                #print(range_bin)
                #print(doppler_bin)
                #except TypeError:
                #    print("TYPE ERROR OCCURRED =====================================")
                #    print(range_val)
                #    print(implied_detection)

                # 3. Populate the visualization maps
                if 0 <= range_bin < config.RANGE_BINS and 0 <= doppler_bin < config.DOPPLER_BINS:
                    confirmed_tracks_map[doppler_bin, range_bin] = 1.0  # Mark the spot
                    confirmed_tracks_angles[doppler_bin, range_bin] = np.rad2deg(angle_rad)
                    #print("marked")
                    # Measurement Jacobian

                model = jpda.measurement_model
                H = model.jacobian(state)
                
                # Get covariance - handle both GaussianState (.covariance) and GaussianStatePrediction (.covar)
                track_dict = jpda.tracks
                gauss_state = track_dict[tid][-1]
                state_covar = getattr(gauss_state, 'covariance', None) or getattr(gauss_state, 'covar', None)
                if state_covar is None:
                    print(f"Warning: Could not get covariance from state of type {type(gauss_state)}")
                    continue
                # Innovation covariance
                S = model.noise_covar + H @ state_covar @ H.T

                # print(f"Track {tid} {confirmed} at x={state[0]:.2f}, y={state[3]:.2f}, misses={misses}, avg det={detection}, implied det after correction = {implied_detection}, Distance: {jpda.detection_maha_sq_distance(detection, implied_detection,S)}")

            t8 = time.perf_counter_ns()
            #print(np.sum(confirmed_tracks_map))
            #print(np.sum(confirmed_tracks_angles))

            # ====================================================

            # Calibration Hook
            # if save_calibration and centroids and len(centroids) > 0:
            #     centroid_values = [v[0].cpu().numpy() for v in centroids.values()]
            #     calibration_data_dict[frame_num] = np.array(centroid_values)

            #     if frame_num % save_interval == 0:
            #         try:
            #             with open(calibration_save_file, 'wb') as f:
            #                 pickle.dump(calibration_data_dict, f)
            #         except Exception as e:
            #             print(f"[PROCESSING] Save failed: {e}")

            # Pack output
            # If visualize_clusters_only is True, we overwrite regular RDM and CFAR 
            # with the centroids data to match the shim's visualization style.
            final_array = filtered_centroids_map if visualize_clusters_only else rdm_display
            final_cfar = filtered_centroids_map if visualize_clusters_only else cfar_data
            final_angles = filtered_centroids_angles if visualize_clusters_only else angle_data

            # Prepare cluster metadata for the visualizer
            clusters_meta = []
            if rda_centroids:
                for label, (centroid_vec, mass) in rda_centroids.items():
                    c = centroid_vec.cpu().numpy()

                    # rda_centroids contains physical values [range_m, doppler_mps, angle_rad]
                    range_meters = float(c[0])
                    doppler_meters_per_sec = float(c[1])
                    angle_rad = float(c[2])

                    # Calculate idx from physical values
                    range_idx = range_meters / config.RANGE_RES
                    doppler_idx = (
                        doppler_meters_per_sec / config.DOPPLER_RES
                    ) + (config.DOPPLER_BINS / 2.0)

                    clusters_meta.append({
                        "id": int(label),
                        "range_idx": float(range_idx),
                        "doppler_idx": float(doppler_idx),

                        "range_m": float(range_meters),
                        "doppler_mps": float(doppler_meters_per_sec),

                        "angle_rad": angle_rad,
                        "angle_deg": float(np.rad2deg(angle_rad)),
                        "mass": int(mass)

                        #TODO: add track data to output
                        #
                        #x,y,vx,vy 
                        #
                        #is_track_or_no
                    })

            # Format confirmed tracks for JSON serialization
            serialized_tracks = []
            tracks_for_calibration = []
            if confirmed_tracks:
                for t in confirmed_tracks:
                    implied_detection = jpda.measurement_model.measurement_function(state).flatten()

                    #convert back to 
                    serialized_tracks.append({
                        'TrackID': int(t['TrackID']),
                        'State': np.array(t['State']).flatten().tolist(),
                        'StateCovariance': np.array(t['StateCovariance']).tolist(),
                        'Age': int(t['Age']),
                        'Status': str(t['Status']),
                        'Hits': int(t['Hits']),
                        'ConsecutiveMisses': int(t['ConsecutiveMisses']),
                        # Detection might be None if missed, handle safely
                        'Last Detection': np.array(t['Detection']).flatten().tolist() if t['Detection'] is not None else [],
                        'Implied Detection': np.array(implied_detection).flatten().tolist()
                    })

                    tracks_for_calibration.append(np.array(implied_detection).flatten().tolist())
                    

            # Calibration Hook — use DBSCAN centroids instead of raw CFAR detections.
            # Raw detections include heavy static clutter and can bias spatial
            # calibration away from the true target overlap between nodes.
            frame_timestamp_ms = int(time.time() * 1000)
            if calib_queue is not None and clusters_meta:
                try:
                    calib_queue.put_nowait({
                        "frame_num": frame_num,
                        "timestamp_ms": frame_timestamp_ms,
                        "detections": [
                            [
                                float(c["range_m"]),
                                # float(c["doppler_idx"]), # we believe doppler_idx is bin number, not the actual value
                                float(c["doppler_mps"]),
                                float(c["angle_rad"]),
                            ]
                            for c in clusters_meta
                        ],
                        "tracks": tracks_for_calibration
                    })
                except Full:
                    pass

            #print(serialized_tracks)
            output_data = {
                "node_id": node_id,
                "timestamp": frame_timestamp_ms,
                "centroids": detection_coords_3d.astype(np.float32).tobytes() if len(detection_coords_3d) > 0 else b"",
                "array": final_array.astype(np.float32).tobytes(),
                "angles": final_angles.astype(np.float32).tobytes() if final_angles is not None else b"",
                "cfar": final_cfar.astype(np.float32).tobytes() if final_cfar is not None else b"",
                "cluster_count": len(rda_centroids) if rda_centroids else 0,
                "clusters": clusters_meta,
                # Additional keys for internal tracking or alternative consumers
                "rdm_centroids": centroids_map,
                "dbscan_2d": dbscan_data_2d,
                "confirmed_tracks": serialized_tracks,
                "confirmed_tracks_rd": confirmed_tracks_map.astype(np.float32).tobytes() if confirmed_tracks_map is not None else b"",
                "confirmed_tracks_angles": confirmed_tracks_angles.astype(np.float32).tobytes() if confirmed_tracks_angles is not None else b""
            }

            try:
                processed_queue.put_nowait(output_data)
            except Full:
                pass

            t9 = time.perf_counter_ns()

            # Print timing every 10 frames with FPS
            frame_count += 1
            if frame_count % frame_rpl == 0 and len(frame_times) > 0:
                avg_interval = sum(frame_times) / len(frame_times)
                fps = 1.0 / avg_interval if avg_interval > 0 else 0
                print(
                    f"[PROCESSING] FPS: {fps:.2f} | Avg: {avg_interval * 1000:.1f}ms | "
                    f"Total: {(t6 - t0) // 1_000}us, RDM: {(t2 - t1) // 1_000}us, CFAR: {(t3 - t2) // 1_000}us, "
                    f"ANGLE: {(t4 - t3) // 1_000}us, DBSCAN3D: {(t5 - t4) // 1_000}us, CENTROID: {(t6 - t5) // 1_000}us, "
                    f"JPDA: {(t7 - t6) // 1_000}us"
                )
                print(
                    f"CFAR Detections: {np.sum(cfar_data > 0)} | 3D Clusters: {len(centroids) if centroids else 0}"
                )

        except Exception as e:
            print(f"[PROCESSING] Error: {e}")
            import traceback
            traceback.print_exc()

def calibration_mqtt_process(
    calib_queue,
    node_id,
    group_id,
    mqtt_host,
    mqtt_port,
    mqtt_user,
    mqtt_pass,
    schema_version=1,
):
    """
    Subscribes to capture/start and, when calibration mode is requested,
    drains calib_queue and streams per-frame centroid data to the MQTT broker.

    Publishes to:
      chirp/v1/group/<groupId>/calibration/frame/<nodeId>  — one message per frame
      chirp/v1/group/<groupId>/calibration/done/<nodeId>   — when collection is complete
    """
    try:
        psutil.Process(os.getpid()).cpu_affinity([0])
    except Exception:
        pass

    # Keep a per-run log file for this subprocess so calibration MQTT
    # activity is preserved across executions.
    logs_dir = node_root_dir / "logs" / "calibration_mqtt"
    logs_dir.mkdir(parents=True, exist_ok=True)
    run_stamp = time.strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"calib_mqtt_{node_id}_{run_stamp}.log"
    log_file = open(log_path, "a", buffering=1, encoding="utf-8")
    sys.stdout = log_file
    sys.stderr = log_file

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)
    log_handler = logging.StreamHandler(log_file)
    log_handler.setFormatter(logging.Formatter("%(asctime)s [CALIB] %(message)s"))
    root_logger.addHandler(log_handler)
    logging.info("Calibration MQTT logs redirected to %s", log_path)

    topic_prefix = "chirp/v1"
    start_topic = f"{topic_prefix}/group/{group_id}/capture/start"
    frame_pub_topic = f"{topic_prefix}/group/{group_id}/calibration/frame/{node_id}"
    done_pub_topic = f"{topic_prefix}/group/{group_id}/calibration/done/{node_id}"

    # Shared state between MQTT callback thread and main collection loop
    calibration_event = threading.Event()
    active_command: dict = {"id": None, "max_frames": 50, "start_epoch_ms": None}

    def _on_connect(client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            logging.error("Calibration MQTT connect failed reason_code=%s", reason_code)
            return
        client.subscribe(start_topic, qos=1)
        logging.info("Calibration publisher connected, subscribed to %s", start_topic)

    def _on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode()) if msg.payload else {}
        except json.JSONDecodeError:
            return

        capture_cfg = payload.get("captureConfig", {}) or {}
        if not capture_cfg.get("calibration", False):
            return

        target_ids = payload.get("targetNodeIds")
        if target_ids and node_id not in [str(t) for t in target_ids]:
            return

        active_command["id"] = payload.get("commandId")
        active_command["max_frames"] = int(capture_cfg.get("calibrationFrames", 50))
        active_command["start_epoch_ms"] = payload.get("startEpochMs")
        calibration_event.set()
        logging.info(
            "Calibration mode activated commandId=%s frames=%d",
            active_command["id"],
            active_command["max_frames"],
        )

    client = mqtt_lib.Client(
        mqtt_lib.CallbackAPIVersion.VERSION2,
        client_id=f"calib-{node_id}",
        clean_session=True,
    )
    if mqtt_user:
        client.username_pw_set(mqtt_user, mqtt_pass)
    client.on_connect = _on_connect
    client.on_message = _on_message

    try:
        client.connect(mqtt_host, mqtt_port, keepalive=30)
    except Exception as exc:
        logging.error("Calibration MQTT initial connect failed: %s", exc)

    client.loop_start()

    while True:
        calibration_event.wait()
        calibration_event.clear()

        cmd_id = active_command["id"]
        max_frames = active_command["max_frames"]
        start_epoch_ms = active_command["start_epoch_ms"]

        # Drain stale items from before the trigger fired
        if start_epoch_ms is not None:
            now_ms = int(time.time() * 1000)
            if start_epoch_ms > now_ms:
                wait_s = (start_epoch_ms - now_ms) / 1000.0
                logging.info("Waiting %.2fs for capture start epoch", wait_s)
                time.sleep(wait_s)
            # Discard frames that accumulated before the start epoch
            while True:
                try:
                    calib_queue.get_nowait()
                except Exception:
                    break

        frame_count = 0
        logging.info("Collecting %d frames for commandId=%s", max_frames, cmd_id)

        while frame_count < max_frames:
            try:
                item = calib_queue.get(timeout=10.0)
            except Exception:
                logging.warning(
                    "Timeout waiting for calibration frame %d/%d commandId=%s",
                    frame_count,
                    max_frames,
                    cmd_id,
                )
                break

            frame_payload = {
                "schemaVersion": schema_version,
                "timestampMs": int(item.get("timestamp_ms", int(time.time() * 1000))),
                "nodeId": node_id,
                "groupId": group_id,
                "commandId": cmd_id,
                # Relative index within this calibration session (0, 1, 2, ...) so that
                # all nodes share the same key for the same physical frame, regardless of
                # the small (<3 ms) wall-clock differences between nodes.
                "frameNum": frame_count,
                "detections": item["detections"],
                "tracks": item.get("tracks", [])
            }
            client.publish(frame_pub_topic, payload=json.dumps(frame_payload), qos=1, retain=False)
            logging.info(
                "Published calibration frame topic=%s payload=%s",
                frame_pub_topic,
                json.dumps(frame_payload, separators=(",", ":")),
            )
            frame_count += 1

        done_payload = {
            "schemaVersion": schema_version,
            "timestampMs": int(time.time() * 1000),
            "nodeId": node_id,
            "groupId": group_id,
            "commandId": cmd_id,
            "totalFrames": frame_count,
        }
        client.publish(done_pub_topic, payload=json.dumps(done_payload), qos=1, retain=False)
        logging.info(
            "Published calibration done topic=%s payload=%s",
            done_pub_topic,
            json.dumps(done_payload, separators=(",", ":")),
        )
        logging.info(
            "Calibration done: published %d frames for commandId=%s", frame_count, cmd_id
        )


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
        psutil.Process(os.getpid()).cpu_affinity([3])
    except Exception:
        pass

    print(f"[SOCKET] Started on core 3, target: {server_url}")
    sio = None
    db_client, db_enabled = init_supabase_client()

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
            print(f"[SOCKET] MQTT frame publisher connected → {frame_topic}")
        except Exception as exc:
            print(f"[SOCKET] MQTT connect failed: {exc}; frame publishing disabled")
            mqtt_client = None

    while True:
        # Non-blocking get with brief sleep fallback
        try:
            data = processed_queue.get_nowait()
        except Empty:
            time.sleep(0.001)
            continue

        if sio is None or not sio.connected:
            sio = reconnect_socketio(server_url)
            if sio is None:
                time.sleep(1)
                continue

        try:
            # Emit data payload combining base requirements and shim enhancements
            sio.emit("send_frame", {
                "node_id": node_id,
                "timestamp_ms": data.get("timestamp", int(time.time() * 1000)),
                "array": data.get("array", b""),
                "angles": data.get("angles", b""),
                "cfar": data.get("cfar", b""),
                "cluster_count": data.get("cluster_count", 0),
                "clusters": data.get("clusters", b""),
                "confirmed_tracks": data.get("confirmed_tracks",b""),
                "confirmed_tracks_rd": data.get("confirmed_tracks_rd",b""),
                "confirmed_tracks_angles": data.get("confirmed_tracks_angles",b"")
            })
        except Exception as e:
            print(f"[SOCKET] Send error: {e}")
            sio = None
        
        if db_enabled and db_client is not None:
            try:
                db_row = {
                    "node_id": node_id,
                    "timestamp_ms": data.get("timestamp", int(time.time() * 1000)),
                    "cluster_count": data.get("cluster_count", 0),
                    "clusters": data.get("clusters", []),
                }
                db_client.table("radar_frame_summary").insert(db_row).execute()
            except Exception as e:
                print(f"[DB] Insert row failed: {e}")

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
                            "range_m": c.get("range_m", 0.0),
                            "angle_rad": c.get("angle_rad", 0.0),
                            "angle_deg": c.get("angle_deg", 0.0),
                            "doppler_mps": c.get("doppler_mps", 0.0),
                            "mass": c.get("mass", 1),
                        }
                        for c in clusters
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
                    print(f"[SOCKET] MQTT publish failed: {exc}")