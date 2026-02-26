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

def create_3d_detection_map_spatial(cfar_data, angle_data, rdm_power):
    """
    Create a 3D detection map from 2D CFAR detections and angle estimates.
    Returns [range_bin, doppler_bin, angle]
    """
    detection_mask = cfar_data > 0
    range_indices, doppler_indices = np.where(detection_mask)

    if len(range_indices) == 0:
        return np.array([]).reshape(0, 3), np.array([])

    angle_values = angle_data[range_indices, doppler_indices]

    detection_coords = np.column_stack(
        [range_indices, doppler_indices, angle_values]
    ).astype(np.float32)

    detection_power = rdm_power[range_indices, doppler_indices]

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

def processing_process(raw_queue, processed_queue, node_id, device=None, save_calibration=True, **cfar_kwargs):
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
            try:
                frame_data = raw_queue.get(timeout=1.0)
            except Empty:
                continue

            t0 = time.perf_counter_ns()
            frame_num += 1

            # 1. Range-Doppler Processing
            rdm.set_buffer(frame_data)
            rdm_mag = rdm.process().reshape(config.SLOW_TIME, config.FAST_TIME)
            clean_rdm = rdm.get_clean_rdm()

            # 2. CFAR Detection
            cfar_data = cfar_pytorch(rdm_mag, device=device, **cfar_params)

            # 3. Angle Estimation
            angle_data = angle_fft(
                cfar_detections=cfar_data,
                clean_rdmap=clean_rdm,
                zero_pad_cols=124,
                device=device,
            )

            # 4. 3D Detection Mapping
            detection_coords_3d, _ = create_3d_detection_map_spatial(
                cfar_data, angle_data, rdm_mag
            )

            # 5. 3D DBSCAN and Centroids
            _, _, centroids = dbscan_process(detection_coords_3d, cfar_data.shape)

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
            output_data = {
                "node_id": node_id,
                "timestamp": int(time.time() * 1000),
                "centroids": detection_coords_3d.astype(np.float32).tobytes() if len(detection_coords_3d) > 0 else b"",
                "array": rdm_mag.astype(np.float32).tobytes(),
                "angles": angle_data.astype(np.float32).tobytes() if angle_data is not None else b"",
                "cfar": cfar_data.astype(np.float32).tobytes() if cfar_data is not None else b""
            }

            try:
                processed_queue.put_nowait(output_data)
            except Full:
                pass

            # Performance tracking
            current_time = time.time()
            if last_frame_time is not None:
                frame_times.append(current_time - last_frame_time)
                if len(frame_times) > frame_avg:
                    frame_times.pop(0)
                
                frame_count += 1
                if frame_count % frame_rpl == 0:
                    fps = 1.0 / (sum(frame_times) / len(frame_times))
                    print(f"[PROCESSING] FPS: {fps:.2f} | Detections: {len(detection_coords_3d)} | Clusters: {len(centroids) if centroids else 0}")

            last_frame_time = current_time

        except Exception as e:
            print(f"[PROCESSING] Error: {e}")
            import traceback
            traceback.print_exc()

def socket_process(processed_queue, server_url, node_id):
    """
    Process that sends processed data to the visualization server.
    """
    print(f"[SOCKET] Started, connecting to {server_url}")
    sio = socketio.Client()
    connected = False

    while True:
        try:
            if not connected:
                try:
                    sio.connect(server_url)
                    print(f"[SOCKET] Connected to {server_url}")
                    connected = True
                except Exception:
                    time.sleep(1)
                    continue

            try:
                data = processed_queue.get(timeout=1.0)
            except Empty:
                continue

            try:
                sio.emit("send_frame", {
                    "node_id": node_id,
                    "frame_num": data["timestamp"],
                    "centroids": data["centroids"],
                    "array": data["array"],
                    "angles": data["angles"],
                    "cfar": data["cfar"]
                })
            except Exception as e:
                print(f"[SOCKET] Send error: {e}")
                connected = False

        except Exception as e:
            print(f"[SOCKET] Loop error: {e}")
            connected = False
            time.sleep(1)
