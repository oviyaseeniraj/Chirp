import os
import time
import pickle
import numpy as np
import psutil
import socketio
import torch
from queue import Empty, Full

from . import config
from .processing.angle import angle_fft
from .processing.cfar import cfar_pytorch
from .processing.rdm import RangeDoppler
from .processing.clustering import dbscan_process, centroid_process

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

def daq_process(raw_queue, daq_class, **daq_kwargs):
    """
    Generic DAQ process that handles frame capture and pushing to queue.
    Supports both live DataAcquisition and playback PlaybackDAQ.
    """
    try:
        psutil.Process(os.getpid()).cpu_affinity([0])
    except Exception as e:
        print(f"[DAQ] Affinity failed: {e}")
    
    print(f"[DAQ] Started on core 0 using {daq_class.__name__}")

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

def processing_process(raw_queue, processed_queue, node_id, device=None, save_calibration=True, visualize_clusters_only=False, **cfar_kwargs):
    """
    Signal processing pipeline: RDM -> CFAR -> Angle -> 3D Mapping -> DBSCAN -> Centroids.
    """
    try:
        psutil.Process(os.getpid()).cpu_affinity([1])
    except Exception as e:
        print(f"[PROCESSING] Affinity failed: {e}")
        
    print("[PROCESSING] Started on core 1")

    rdm = RangeDoppler(window="blackman", alpha=0.1)
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[PROCESSING] Using device: {device}")

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
            rdm.set_buffer(np.array(frame_data, dtype=np.float32))
            rdm_mag = rdm.process().reshape(config.SLOW_TIME, config.FAST_TIME)
            clean_rdm = rdm.get_clean_rdm()
            t2 = time.perf_counter_ns()
            frame_num += 1

            # 2. CFAR Detection
            cfar_data = cfar_pytorch(rdm_mag, device=device, **cfar_params)
            t3 = time.perf_counter_ns()

            # 3. Angle Estimation
            angle_data = angle_fft(
                cfar_detections=cfar_data,
                clean_rdmap=clean_rdm,
                zero_pad_cols=124,
                device=device,
            )
            t4 = time.perf_counter_ns()

            # 4. 3D Detection Mapping
            detection_coords_3d, _ = create_3d_detection_map_spatial(
                cfar_data, angle_data, rdm_mag
            )
            t4b = time.perf_counter_ns()

            # 5. 3D DBSCAN
            dbscan_data_2d, dbscan_angles, centroids = dbscan_process(detection_coords_3d, cfar_data.shape)
            t4c = time.perf_counter_ns()

            # 6. Centroid Processing
            centroids_map, centroids_angles = centroid_process(centroids, cfar_data.shape)
            t5 = time.perf_counter_ns()

            # Calibration Hook
            if save_calibration and centroids and len(centroids) > 0:
                centroid_values = [v[0].cpu().numpy() for v in centroids.values()]
                calibration_data_dict[frame_num] = np.array(centroid_values)

                if frame_num % save_interval == 0:
                    try:
                        with open(calibration_save_file, 'wb') as f:
                            pickle.dump(calibration_data_dict, f)
                    except Exception as e:
                        print(f"[PROCESSING] Save failed: {e}")

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
                "dbscan_2d": dbscan_data_2d
            }

            try:
                processed_queue.put_nowait(output_data)
            except Full:
                pass

            t6 = time.perf_counter_ns()

            # Print timing every 10 frames with FPS
            frame_count += 1
            if frame_count % frame_rpl == 0 and len(frame_times) > 0:
                avg_interval = sum(frame_times) / len(frame_times)
                fps = 1.0 / avg_interval if avg_interval > 0 else 0
                print(
                    f"[PROCESSING] FPS: {fps:.2f} | Avg: {avg_interval * 1000:.1f}ms | "
                    f"Total: {(t5 - t0) // 1_000}us, RDM: {(t2 - t1) // 1_000}us, CFAR: {(t3 - t2) // 1_000}us, "
                    f"ANGLE: {(t4 - t3) // 1_000}us, 3D_MAP: {(t4b - t4) // 1_000}us, DBSCAN3D: {(t4c - t4b) // 1_000}us, CENTROID: {(t5 - t4c) // 1_000}us"
                )
                print(
                    f"CFAR Detections: {np.sum(cfar_data > 0)} | 3D Clusters: {len(centroids) if centroids else 0}"
                )

        except Exception as e:
            print(f"[PROCESSING] Error: {e}")
            import traceback
            traceback.print_exc()

def socket_process(processed_queue, server_url, node_id):
    """
    Process that sends processed data to the visualization server.
    """
    # Pin to CPU core 2
    try:
        psutil.Process(os.getpid()).cpu_affinity([2])
    except Exception:
        pass
        
    print(f"[SOCKET] Started on core 2, target: {server_url}")
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
                "clusters": data.get("clusters", []),
            })
        except Exception as e:
            print(f"[SOCKET] Send error: {e}")
            sio = None
