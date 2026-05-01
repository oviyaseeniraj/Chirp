import os
import time
import pickle
import numpy as np
import psutil
import socketio
import torch
from queue import Empty, Full

 
from datetime import datetime

from . import config
from .processing.rdm import RangeDoppler

from .processing.anirban_jpda import JPDATracker
#from .processing.anirban_jpda import 

# Hardware acceleration check: Choose between GPU (PyTorch) and optimized CPU (NumPy/OpenCV)
# if torch.cuda.is_available():
if config.USE_CUDA:
    from .processing.cfar import cfar_pytorch as cfar_func
    from .processing.angle import angle_fft as angle_func
    from .processing.clustering import dbscan_process, centroid_process
else:
    from .processing.cfar_cpu import cfar_cpu as cfar_func
    from .processing.angle_cpu import angle_cpu as angle_func
    from .processing.clustering_cpu import dbscan_process, centroid_process

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
    Returns [range_bin, doppler_bin, angle]
    """
    detection_mask = cfar_data > 0
    doppler_indices, range_indices = np.where(detection_mask)

    if len(doppler_indices) == 0:
        return np.array([]).reshape(0, 3), np.array([])

    angle_values = angle_data[doppler_indices, range_indices]

    detection_coords = np.column_stack(
        [range_indices, doppler_indices, angle_values]
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
def processing_process(raw_queue, processed_queue, node_id, device=None, save_calibration=True, visualize_clusters_only=False, **cfar_kwargs):
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
    sigma_a=0.1,                     # Process noise #variance of human acceleration
    max_feasible_events=config.MAX_NUM_FEASIBLE_JOINT_EVENTS,
    #multi-track parameters
    threshold_init = config.THRESHOLD_INIT,
    threshold_hit_miss = config.THRESHOLD_HIT_MISS,
    threshold_merge = config.THRESHOLD_MERGE
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

    calibration_save_file = f"calibration_data_{node_id}.pkl"
    calibration_data_dict = {}
    save_interval = 10
    frame_num = 0

    # Default CFAR parameters if not provided
    cfar_params = {
        'guard_cells_doppler': 4,
        'guard_cells_range': 16,
        'training_cells_doppler': 6,
        'training_cells_range': 24,
        'threshold_factor': 2,
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

            # 1. ============================== Range-Doppler Processing ========================
            t1 = time.perf_counter_ns()
            # TODO: why is dtype np.float32, should be np.uint16
            rdm.set_buffer(np.array(frame_data, dtype=np.int16))
            rdm_mag = rdm.process().reshape(config.SLOW_TIME, config.FAST_TIME)
            clean_rdm = rdm.get_clean_rdm()
            frame_num += 1

            t2 = time.perf_counter_ns()

            # 2. =============================== CFAR Detection ===============================
            cfar_data = cfar_func(rdm_mag, device=device, **cfar_params)
            t3 = time.perf_counter_ns()

            # 3. =============================== Angle Estimation ===============================
            angle_data = angle_func(
                cfar_detections=cfar_data,
                clean_rdmap=clean_rdm,
                zero_pad_cols=124,
                device=device,
            )
            t4 = time.perf_counter_ns()

            # 4. ================================== 3D DBSCAN ===============================
            detection_coords_3d, _ = create_3d_detection_map_spatial(
                cfar_data, angle_data, rdm_mag
            )

            #print(detection_coords_3d)

            dbscan_data_2d, dbscan_angles, centroids = dbscan_process(detection_coords_3d, cfar_data.shape)
            t5 = time.perf_counter_ns()

            # 5. =============================== Centroid Processing ===============================
            centroids_map, centroids_angles = centroid_process(centroids, cfar_data.shape)
            
            rda_centroids = {}
            #print('measurements bin:', " ")
            for label,data in centroids.items():
                meas = data[0]
                range_bin, vel_bin = meas[0], meas[1]
                #print(meas[0], meas[1])
                #print(range_bin,vel_bin)
                angle = meas[2]

                range_val, vel_val = rd_bin_to_val(range_bin, vel_bin)

                #print(range_val,vel_val)
                num_points = data[1]

                rda_centroids[label] = (torch.tensor([range_val, vel_val, angle]), num_points)
            print("")
            print("")

            print("centroids:",rda_centroids)
            #print( [detection[1] for (detection,p) in rda_centroids.values()])
            """
            #Zero bin removal for centroids
            eps = 0.2
            rda_centroids = {}
            for label,data in centroids.items():
                meas = data[0]
                vel_bin, range_bin = meas[0], meas[1]

                #get rid of reflections
                #if (range_bin > 256):
                #    continue
                angle = meas[2]
                num_points = data[1]

                range_val, vel_val = rd_bin_to_val(range_bin, vel_bin)
                
                if abs(vel_bin - 32) > eps: #keep moving targets
                    rda_centroids[label] = (torch.tensor([range_val, vel_val, angle]), num_points)
                else:
                    pass
                    #print("filtrum")
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
        """
                    
            t6 = time.perf_counter_ns()

            #6. =============================== JPDA Multi-Target Tracking ===========================================
            #current_timestamp = datetime.now()
            #print(f"# of prefiltered detections: {len(rda_centroids)}")
            confirmed_tracks, tentative_tracks = jpda.process(rda_centroids, current_frame_time)

            t7 = time.perf_counter_ns()

            # Create visualization maps for confirmed tracks
            confirmed_tracks_map = np.zeros_like(rdm_mag, dtype=np.float32)
            confirmed_tracks_angles = np.zeros_like(rdm_mag, dtype=np.float32)

            #jpda.print_tracker_status()

            all_tracks = (confirmed_tracks or []) + (tentative_tracks or [])

            print(f"Time: {current_frame_time} Confirmed: {len(confirmed_tracks)} | Tentative: {len(tentative_tracks)}")
            for track in all_tracks:
                tid = track['TrackID']
                state = track['State'] # [x, vx, y, vy]
                misses = track['ConsecutiveMisses']
                detection = track['Detection'] # [range (m), velocity (m/s), angle (rad)]
                confirmed = track['Status']



                #TODO: Convert the state to the 
                expected_detection = jpda.measurement_model.function(state).flatten()

                #print(expected_detection)
                #print(detection)

                # --- Convert physical units back to RDM bins ---
                range_val, vel_val, angle_rad = expected_detection

                #print("Difference")
                #print(maha_distance(np.array([range_val, vel_val, angle_rad]), detection, jpda.measurement_model.noise_covar))

                #try: 
                range_bin, doppler_bin = rd_val_to_bin(range_val, vel_val)
                #print(range_bin)
                #print(doppler_bin)
                #except TypeError:
                #    print("TYPE ERROR OCCURRED =====================================")
                #    print(range_val)
                #    print(expected_detection)

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

                print(f"Track {tid} {confirmed} at x={state[0]:.2f}, y={state[3]:.2f}, misses={misses}, avg det={detection}, expected det = {expected_detection}, Distance: {jpda.detection_maha_sq_distance(detection, expected_detection,S)}")

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
            final_array = centroids_map if visualize_clusters_only else rdm_mag
            final_cfar = centroids_map if visualize_clusters_only else cfar_data
            final_angles = centroids_angles if visualize_clusters_only else angle_data

            # Prepare cluster metadata for the visualizer
            clusters_meta = []
            if centroids:
                for label, (centroid_vec, mass) in centroids.items():
                    c = centroid_vec.cpu().numpy()
                    clusters_meta.append({
                        "id": int(label),
                        "range_idx": float(c[0]),
                        "doppler_idx": float(c[1]),
                        "angle_rad": float(c[2]),
                        "angle_deg": float(np.rad2deg(c[2])),
                        "mass": int(mass)

                        #TODO: add track data to output
                        #
                        #x,y,vx,vy 
                        #
                        #is_track_or_no
                    })


            # Format confirmed tracks for JSON serialization
            serialized_tracks = []
            if confirmed_tracks:
                for t in confirmed_tracks:
                    expected_detection = jpda.measurement_model.function(state).flatten()

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
                        'Predicted Detection': np.array(expected_detection).flatten().tolist()

                    })

            output_data = {
                "node_id": node_id,
                "timestamp": int(time.time() * 1000),
                "centroids": detection_coords_3d.astype(np.float32).tobytes() if len(detection_coords_3d) > 0 else b"",
                "array": final_array.astype(np.float32).tobytes(),
                "angles": final_angles.astype(np.float32).tobytes() if final_angles is not None else b"",
                "cfar": final_cfar.astype(np.float32).tobytes() if final_cfar is not None else b"",
                "cluster_count": len(centroids) if centroids else 0,
                "clusters": clusters_meta,
                # Additional keys for internal tracking or alternative consumers
                "rdm_centroids": centroids_map,
                "dbscan_2d": dbscan_data_2d,
                "confirmed_tracks": serialized_tracks,
                "confirmed_tracks_rd": confirmed_tracks_map.astype(np.float32).tobytes() if confirmed_tracks_map is not None else b"",
                "confirmed_tracks_angles": confirmed_tracks_angles.astype(np.float32).tobytes() if confirmed_tracks_angles is not None else b""
            }

            #print(output_data["confirmed_tracks_rd"])

            try:
                processed_queue.put_nowait(output_data)
            except Full:
                pass

            # Print timing every 10 frames with FPS
            frame_count += 1
            if frame_count % frame_rpl == 0 and len(frame_times) > 0:
                avg_interval = sum(frame_times) / len(frame_times)
                fps = 1.0 / avg_interval if avg_interval > 0 else 0
                print(
                    f"[PROCESSING] FPS: {fps:.2f} | Avg: {avg_interval * 1000:.1f}ms | "
                    f"Total: {(t7 - t0) // 1_000}us, RDM: {(t2 - t1) // 1_000}us," 
                    f"CFAR: {(t3 - t2) // 1_000}us, "
                    f"ANGLE: {(t4 - t3) // 1_000}us, "
                    f"3D DBSCAN: {(t5 - t4) // 1_000}us, "
                    f"CENTROID: {(t6 - t5) // 1_000}us, "
                    f"JPDA: {(t7 - t6) // 1_000}us"

                )
                print(
                    f"CFAR Detections: {np.sum(cfar_data > 0)} | 3D Clusters: {len(centroids) if centroids else 0}"
                )

        except Exception as e:
            print(f"[PROCESSING] Error: {e}")
            import traceback
            traceback.print_exc()

            
def socket_process(processed_queue, server_url, node_id):
    
    #Process that sends processed data to the visualization server.
    
    # Pin to CPU core 2
    try:
        psutil.Process(os.getpid()).cpu_affinity([3])
    except Exception:
        pass
        
    print(f"[SOCKET] Started on core 3, target: {server_url}")
    sio = None

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
                "frame_num": data.get("timestamp", int(time.time() * 1000)),
                "array": data.get("array", b""),
                "angles": data.get("angles", b""),
                "cfar": data.get("cfar", b""),
                "cluster_count": data.get("cluster_count", 0),
                "clusters": data.get("clusters", b""),
                "confirmed_tracks": data.get("confirmed_tracks",b""),
                "confirmed_tracks_rd": data.get("confirmed_tracks_rd",b""),
                "confirmed_tracks_angles": data.get("confirmed_tracks_angles",b"")
            })

            #print(data.get("confirmed_tracks_rd"))
        except Exception as e:
            print(f"[SOCKET] Send error: {e}")
            sio = None
