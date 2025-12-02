#!/usr/bin/env python3
"""
Real-Time Radar Calibration Processor - Frame-Number-Based Triggering with Kalman Filtering

This service triggers calibration when frame #X has been received from ALL radars,
ensuring perfectly synchronized frames for spatial calibration.

Key Innovation: 
- Frame-number matching for perfect synchronization
- Extended Kalman Filter for polar-to-Cartesian conversion with uncertainty
- Multi-target tracking using DBSCAN clustering and track association
- Per-target trajectory calibration for robust multi-target scenarios
"""

import asyncio
import asyncpg
import os
from collections import defaultdict
import numpy as np
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
from scipy.spatial.distance import mahalanobis
from sklearn.cluster import DBSCAN

# Configuration
PG_HOST = os.getenv("POSTGRES_HOST", "db")
PG_USER = os.getenv("POSTGRES_USER", "user")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "password")
PG_DB = os.getenv("POSTGRES_DB", "mqttdata")
CALIBRATION_WINDOW = int(os.getenv("CALIBRATION_WINDOW", 50))  # Use last N frames
CHECK_INTERVAL = float(os.getenv("CHECK_INTERVAL", 2.0))  # Check every 2 seconds
MIN_RADARS = int(os.getenv("MIN_RADARS", 2))

# Tracking Configuration
SIGMA_RANGE = 0.035  # Range measurement noise (m)
SIGMA_AZIMUTH = np.deg2rad(30)  # Azimuth measurement noise (rad)
PROCESS_NOISE_STD = 0.025  # Process noise for acceleration
DBSCAN_EPS = 0.5  # DBSCAN clustering epsilon (m)
DBSCAN_MIN_SAMPLES = 3  # Minimum samples for DBSCAN cluster
MAHALANOBIS_GATE = 9.0  # Chi-square gate for track association (95% confidence)
MIN_TRACK_LENGTH = 10  # Minimum track length for calibration


# =============================================================================
# Extended Kalman Filter for Polar-to-Cartesian Tracking
# =============================================================================

@dataclass
class KalmanTrack:
    """Kalman filter track in 2D Cartesian space (constant velocity model)"""
    track_id: int
    state: np.ndarray  # [x, vx, y, vy]
    covariance: np.ndarray  # 4x4 covariance matrix
    last_update_frame: int
    measurement_history: List[Tuple[float, float, int]]  # [(x, y, frame_num), ...]
    
    def __init__(self, track_id: int, x: float, y: float, frame_num: int):
        self.track_id = track_id
        # Initialize state: [x, vx, y, vy]
        self.state = np.array([x, 0.0, y, 0.0])
        # Initialize covariance with high velocity uncertainty
        self.covariance = np.diag([SIGMA_RANGE**2, 1.0, SIGMA_RANGE**2, 1.0])
        self.last_update_frame = frame_num
        self.measurement_history = [(x, y, frame_num)]


class ExtendedKalmanFilter:
    """Extended Kalman Filter for polar-to-cartesian tracking"""
    
    def __init__(self, dt: float = 1.0):
        self.dt = dt
        
        # State transition matrix (constant velocity model)
        self.F = np.array([
            [1, dt, 0,  0],
            [0,  1, 0,  0],
            [0,  0, 1, dt],
            [0,  0, 0,  1]
        ])
        
        # Process noise covariance
        q = PROCESS_NOISE_STD ** 2
        self.Q = q * np.array([
            [dt**4/4, dt**3/2, 0,       0      ],
            [dt**3/2, dt**2,   0,       0      ],
            [0,       0,       dt**4/4, dt**3/2],
            [0,       0,       dt**3/2, dt**2  ]
        ])
        
        # Measurement noise covariance (range, azimuth in polar)
        self.R_polar = np.array([
            [SIGMA_RANGE**2,    0],
            [0,                 SIGMA_AZIMUTH**2]
        ])
    
    def predict(self, track: KalmanTrack) -> None:
        """Predict step: propagate state and covariance"""
        track.state = self.F @ track.state
        track.covariance = self.F @ track.covariance @ self.F.T + self.Q
    
    def update(self, track: KalmanTrack, measurement_polar: np.ndarray) -> None:
        """
        Update step: correct prediction with polar measurement
        measurement_polar = [range, azimuth_rad]
        """
        # Predicted state
        x_pred = track.state[0]
        y_pred = track.state[2]
        
        # Convert polar measurement to Cartesian
        r_meas, theta_meas = measurement_polar
        z_cart = np.array([
            r_meas * np.cos(theta_meas),
            r_meas * np.sin(theta_meas)
        ])
        
        # Measurement Jacobian (from state to measurement space)
        # h(x) = [x, y], so H = [[1, 0, 0, 0], [0, 0, 1, 0]]
        H = np.array([
            [1, 0, 0, 0],
            [0, 0, 1, 0]
        ])
        
        # Propagate polar measurement noise to Cartesian
        # Jacobian of polar-to-cartesian conversion
        J_polar_to_cart = np.array([
            [np.cos(theta_meas), -r_meas * np.sin(theta_meas)],
            [np.sin(theta_meas),  r_meas * np.cos(theta_meas)]
        ])
        R_cart = J_polar_to_cart @ self.R_polar @ J_polar_to_cart.T
        
        # Innovation
        z_pred = H @ track.state
        y = z_cart - z_pred
        
        # Innovation covariance
        S = H @ track.covariance @ H.T + R_cart
        
        # Kalman gain
        K = track.covariance @ H.T @ np.linalg.inv(S)
        
        # Update state and covariance
        track.state = track.state + K @ y
        track.covariance = (np.eye(4) - K @ H) @ track.covariance
    
    def mahalanobis_distance(self, track: KalmanTrack, measurement_polar: np.ndarray) -> float:
        """
        Compute Mahalanobis distance between track prediction and measurement
        """
        # Convert polar to Cartesian
        r_meas, theta_meas = measurement_polar
        z_cart = np.array([
            r_meas * np.cos(theta_meas),
            r_meas * np.sin(theta_meas)
        ])
        
        # Predicted measurement
        H = np.array([
            [1, 0, 0, 0],
            [0, 0, 1, 0]
        ])
        z_pred = H @ track.state
        
        # Innovation covariance
        J_polar_to_cart = np.array([
            [np.cos(theta_meas), -r_meas * np.sin(theta_meas)],
            [np.sin(theta_meas),  r_meas * np.cos(theta_meas)]
        ])
        R_cart = J_polar_to_cart @ self.R_polar @ J_polar_to_cart.T
        S = H @ track.covariance @ H.T + R_cart
        
        # Mahalanobis distance
        innovation = z_cart - z_pred
        try:
            S_inv = np.linalg.inv(S)
            dist = np.sqrt(innovation.T @ S_inv @ innovation)
        except np.linalg.LinAlgError:
            dist = np.inf
        
        return dist


# =============================================================================
# Multi-Target Tracker
# =============================================================================

class MultiTargetTracker:
    """Multi-target tracker using DBSCAN clustering and Kalman filtering"""
    
    def __init__(self):
        self.tracks: Dict[int, KalmanTrack] = {}
        self.next_track_id = 1
        self.ekf = ExtendedKalmanFilter()
    
    def process_frame(self, detections: List[Tuple[float, float]], frame_num: int) -> None:
        """
        Process detections for a single frame
        detections: List of (range, azimuth_deg) tuples
        """
        if not detections:
            return
        
        # Convert to radians and numpy array
        detections_polar = np.array([(r, np.deg2rad(az)) for r, az in detections])
        
        # Convert to Cartesian for clustering
        detections_cart = np.array([
            [r * np.cos(theta), r * np.sin(theta)]
            for r, theta in detections_polar
        ])
        
        # Cluster detections using DBSCAN
        clustered_detections = self._cluster_detections(detections_cart, detections_polar)
        
        # Predict all existing tracks
        for track in self.tracks.values():
            self.ekf.predict(track)
        
        # Associate clustered detections with tracks
        self._associate_and_update(clustered_detections, frame_num)
        
        # Prune old tracks
        self._prune_tracks(frame_num)
    
    def _cluster_detections(self, 
                           detections_cart: np.ndarray, 
                           detections_polar: np.ndarray) -> List[Tuple[np.ndarray, List[int]]]:
        """
        Cluster detections and return centroid measurements
        Returns: List of (polar_measurement, indices) tuples
        """
        if len(detections_cart) == 0:
            return []
        
        # DBSCAN clustering in Cartesian space
        clustering = DBSCAN(eps=DBSCAN_EPS, min_samples=DBSCAN_MIN_SAMPLES).fit(detections_cart)
        labels = clustering.labels_
        
        # Get cluster centroids
        clustered_detections = []
        for label in set(labels):
            if label == -1:  # Skip noise
                continue
            
            cluster_mask = labels == label
            cluster_indices = np.where(cluster_mask)[0].tolist()
            
            # Compute centroid in Cartesian, then convert to polar
            cluster_cart = detections_cart[cluster_mask]
            centroid_cart = np.mean(cluster_cart, axis=0)
            
            # Convert centroid to polar
            x, y = centroid_cart
            r = np.sqrt(x**2 + y**2)
            theta = np.arctan2(y, x)
            
            clustered_detections.append((np.array([r, theta]), cluster_indices))
        
        return clustered_detections
    
    def _associate_and_update(self, 
                             clustered_detections: List[Tuple[np.ndarray, List[int]]], 
                             frame_num: int) -> None:
        """Associate detections with tracks using Mahalanobis distance gating"""
        
        unassigned_detections = list(range(len(clustered_detections)))
        unassigned_tracks = list(self.tracks.keys())
        
        # Compute cost matrix (Mahalanobis distances)
        if len(unassigned_tracks) > 0 and len(unassigned_detections) > 0:
            cost_matrix = np.zeros((len(unassigned_tracks), len(unassigned_detections)))
            
            for i, track_id in enumerate(unassigned_tracks):
                track = self.tracks[track_id]
                for j, (detection_polar, _) in enumerate(clustered_detections):
                    dist = self.ekf.mahalanobis_distance(track, detection_polar)
                    cost_matrix[i, j] = dist if dist < MAHALANOBIS_GATE else np.inf
            
            # Greedy assignment (simple nearest neighbor)
            while True:
                min_cost = np.min(cost_matrix)
                if min_cost == np.inf:
                    break
                
                min_i, min_j = np.unravel_index(np.argmin(cost_matrix), cost_matrix.shape)
                track_id = unassigned_tracks[min_i]
                detection_polar, _ = clustered_detections[min_j]
                
                # Update track
                track = self.tracks[track_id]
                self.ekf.update(track, detection_polar)
                track.last_update_frame = frame_num
                
                # Store measurement in history
                x, y = track.state[0], track.state[2]
                track.measurement_history.append((x, y, frame_num))
                
                # Mark as assigned
                cost_matrix[min_i, :] = np.inf
                cost_matrix[:, min_j] = np.inf
        
        # Create new tracks for unassigned detections
        for detection_idx in unassigned_detections:
            detection_polar, _ = clustered_detections[detection_idx]
            r, theta = detection_polar
            x = r * np.cos(theta)
            y = r * np.sin(theta)
            
            # Check if any existing track is close (avoid duplicates)
            too_close = False
            for track in self.tracks.values():
                if np.sqrt((track.state[0] - x)**2 + (track.state[2] - y)**2) < DBSCAN_EPS:
                    too_close = True
                    break
            
            if not too_close:
                new_track = KalmanTrack(self.next_track_id, x, y, frame_num)
                self.tracks[self.next_track_id] = new_track
                self.next_track_id += 1
    
    def _prune_tracks(self, current_frame: int, max_age: int = 5) -> None:
        """Remove tracks that haven't been updated recently"""
        tracks_to_remove = [
            track_id for track_id, track in self.tracks.items()
            if current_frame - track.last_update_frame > max_age
        ]
        for track_id in tracks_to_remove:
            del self.tracks[track_id]
    
    def get_valid_tracks(self, min_length: int = MIN_TRACK_LENGTH) -> Dict[int, List[complex]]:
        """
        Get tracks with sufficient length as complex trajectories
        Returns: {track_id: [complex(x, y), ...]}
        """
        valid_tracks = {}
        for track_id, track in self.tracks.items():
            if len(track.measurement_history) >= min_length:
                trajectory = [complex(x, y) for x, y, _ in track.measurement_history]
                valid_tracks[track_id] = trajectory
        return valid_tracks


def convert_polar_to_cartesian(angle_deg, range_m):
    """Convert polar coordinates to Cartesian complex number (legacy function)"""
    angle_rad = np.deg2rad(angle_deg)
    x = range_m * np.cos(angle_rad)
    y = range_m * np.sin(angle_rad)
    return complex(x, y)

def closed_form_calibration(trajectory_estimates):
    """Closed-form calibration solution for pairwise radar calibration"""
    radar_names = list(trajectory_estimates.keys())
    num_radars = len(radar_names)
    
    if num_radars < MIN_RADARS:
        raise ValueError(f"Need at least {MIN_RADARS} radars, got {num_radars}")
    
    num_frames = len(trajectory_estimates[radar_names[0]])
    for radar in radar_names:
        if len(trajectory_estimates[radar]) != num_frames:
            raise ValueError(f"Frame count mismatch for {radar}")
    
    P_optimal = {}
    theta_optimal = {}
    residuals = {}
    
    for i, radar_i in enumerate(radar_names):
        for j, radar_j in enumerate(radar_names):
            if i == j:
                continue
            
            z_i_hat = np.array(trajectory_estimates[radar_i])
            z_j_hat = np.array(trajectory_estimates[radar_j])
            
            z_i_mean = np.mean(z_i_hat)
            z_j_mean = np.mean(z_j_hat)
            
            # Compute cross-correlation
            correlation = 0
            for t in range(len(z_i_hat)):
                correlation += (z_j_hat[t] - z_j_mean) * np.conj(z_i_hat[t] - z_i_mean)
            
            phi = np.arctan2(correlation.imag, correlation.real)
            theta_ij = np.rad2deg(-phi)
            P_ij = z_i_mean - np.exp(-1j * phi) * z_j_mean
            
            # Compute residual
            residual = 0
            for t in range(len(z_i_hat)):
                residual += (np.abs(z_j_hat[t] - z_j_mean)**2 + 
                           np.abs(z_i_hat[t] - z_i_mean)**2)
            residual -= 2 * np.abs(correlation)
            residual = residual / len(z_i_hat)
            
            P_optimal[(radar_i, radar_j)] = P_ij
            theta_optimal[(radar_i, radar_j)] = theta_ij
            residuals[(radar_i, radar_j)] = residual
    
    return P_optimal, theta_optimal, residuals

async def get_frame_status(pool):
    """Get current frame numbers per radar"""
    async with pool.acquire() as conn:
        result = await conn.fetch("""
            SELECT radar_name, MAX(frame_number) as max_frame
            FROM radar_frames
            WHERE processed = FALSE
            GROUP BY radar_name
        """)
    return {row['radar_name']: row['max_frame'] for row in result}

async def fetch_frames_by_number(pool, frame_start, frame_end):
    """Fetch specific frame range for all radars"""
    async with pool.acquire() as conn:
        frames = await conn.fetch("""
            SELECT radar_name, frame_number, angle, range, timestamp_ns
            FROM radar_frames
            WHERE processed = FALSE
              AND frame_number >= $1
              AND frame_number <= $2
            ORDER BY radar_name, frame_number
        """, frame_start, frame_end)
    return frames

async def store_calibration_results(pool, P_optimal, theta_optimal, residuals, num_frames):
    """Store calibration results"""
    async with pool.acquire() as conn:
        for (ref_radar, target_radar), position in P_optimal.items():
            orientation = theta_optimal[(ref_radar, target_radar)]
            residual = residuals[(ref_radar, target_radar)]
            
            await conn.execute("""
                INSERT INTO calibration_results 
                (ref_radar, target_radar, position_x, position_y, 
                 orientation_deg, residual, num_frames)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            ref_radar, target_radar,
            position.real, position.imag,
            orientation, float(residual), num_frames
            )

async def mark_frames_processed(pool, frame_start, frame_end):
    """Mark frame range as processed"""
    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE radar_frames 
            SET processed = TRUE
            WHERE frame_number >= $1
              AND frame_number <= $2
              AND processed = FALSE
        """, frame_start, frame_end)
        return result

async def run_calibration_on_frames(pool, frame_start, frame_end):
    """Run calibration on specific frame range with multi-target tracking"""
    # Fetch frames
    frames = await fetch_frames_by_number(pool, frame_start, frame_end)
    
    if not frames:
        return False
    
    # Group raw detections by radar and frame number
    radar_detections = defaultdict(lambda: defaultdict(list))
    for frame in frames:
        radar_name = frame['radar_name']
        frame_num = frame['frame_number']
        # Store as (range, angle) tuples
        radar_detections[radar_name][frame_num].append((frame['range'], frame['angle']))
    
    # Check all radars have all frames
    radar_names = list(radar_detections.keys())
    if len(radar_names) < MIN_RADARS:
        return False
    
    expected_frames = set(range(frame_start, frame_end + 1))
    for radar_name in radar_names:
        if set(radar_detections[radar_name].keys()) != expected_frames:
            print(f"  ✗ {radar_name} missing frames in range {frame_start}-{frame_end}")
            return False
    
    print(f"  Running Kalman filtering for multi-target tracking...")
    
    # Initialize trackers for each radar
    radar_trackers = {}
    for radar_name in radar_names:
        tracker = MultiTargetTracker()
        
        # Process all frames sequentially
        for frame_num in range(frame_start, frame_end + 1):
            detections = radar_detections[radar_name][frame_num]
            tracker.process_frame(detections, frame_num)
        
        radar_trackers[radar_name] = tracker
        
        # Get valid tracks
        valid_tracks = tracker.get_valid_tracks(min_length=MIN_TRACK_LENGTH)
        print(f"    {radar_name}: {len(valid_tracks)} valid tracks detected")
    
    # Get all valid tracks from each radar
    all_radar_tracks = {}
    for radar_name, tracker in radar_trackers.items():
        valid_tracks = tracker.get_valid_tracks(min_length=MIN_TRACK_LENGTH)
        if valid_tracks:
            all_radar_tracks[radar_name] = valid_tracks
    
    # Check if we have enough tracks
    if len(all_radar_tracks) < MIN_RADARS:
        print(f"  ✗ Insufficient radars with valid tracks")
        return False
    
    # Run calibration on each track combination for ALL radar pairs
    print(f"\n  Running multi-target calibration...")
    all_calibrations = []
    
    # Get all radar pairs (i, j) where i != j
    radar_list = list(all_radar_tracks.keys())
    radar_pairs = [(radar_list[i], radar_list[j]) 
                   for i in range(len(radar_list)) 
                   for j in range(len(radar_list)) 
                   if i != j]
    
    print(f"  Calibrating {len(radar_pairs)} radar pairs: {radar_pairs}")
    
    for radar_i, radar_j in radar_pairs:
        tracks_i = all_radar_tracks[radar_i]
        tracks_j = all_radar_tracks[radar_j]
        
        # Try all track combinations for this pair
        for track_id_i, trajectory_i in tracks_i.items():
            for track_id_j, trajectory_j in tracks_j.items():
                # Ensure same length (truncate to shorter)
                min_len = min(len(trajectory_i), len(trajectory_j))
                traj_i = trajectory_i[:min_len]
                traj_j = trajectory_j[:min_len]
                
                if min_len < MIN_TRACK_LENGTH:
                    continue
                
                # Run calibration on this track pair
                try:
                    trajectories = {radar_i: traj_i, radar_j: traj_j}
                    P_opt, theta_opt, resid = closed_form_calibration(trajectories)
                    
                    # Extract pairwise result
                    pair_key = (radar_i, radar_j)
                    if pair_key in P_opt:
                        all_calibrations.append({
                            'ref_radar': radar_i,
                            'target_radar': radar_j,
                            'track_i': track_id_i,
                            'track_j': track_id_j,
                            'position': P_opt[pair_key],
                            'orientation': theta_opt[pair_key],
                            'residual': resid[pair_key],
                            'num_frames': min_len
                        })
                except Exception as e:
                    print(f"    Warning: Calibration failed for {radar_i}-{radar_j}, "
                          f"tracks {track_id_i}-{track_id_j}: {e}")
                    continue
    
    if not all_calibrations:
        print(f"  ✗ No successful calibrations")
        return False
    
    # Group by radar pair and select best calibration for each pair
    from collections import defaultdict
    best_per_pair = defaultdict(lambda: {'residual': float('inf')})
    
    for calib in all_calibrations:
        pair_key = (calib['ref_radar'], calib['target_radar'])
        if calib['residual'] < best_per_pair[pair_key]['residual']:
            best_per_pair[pair_key] = calib
    
    print(f"\n  ✓ Multi-target calibration complete!")
    print(f"  Total track combinations tested: {len(all_calibrations)}")
    print(f"  Best calibration for each radar pair:\n")
    
    # Store all best pairwise calibrations
    for pair_key, calib in best_per_pair.items():
        ref_radar = calib['ref_radar']
        target_radar = calib['target_radar']
        position = calib['position']
        orientation = calib['orientation']
        residual = calib['residual']
        num_frames = calib['num_frames']
        
        print(f"    {ref_radar} → {target_radar}: "
              f"P=({position.real:.2f}, {position.imag:.2f})m, "
              f"θ={orientation:.1f}°, residual={residual:.3f}")
        print(f"      Using tracks: {calib['track_i']} ↔ {calib['track_j']} ({num_frames} frames)")
        
        # Store each pairwise calibration
        P_optimal = {pair_key: position}
        theta_optimal = {pair_key: orientation}
        residuals = {pair_key: residual}
        await store_calibration_results(pool, P_optimal, theta_optimal, residuals, num_frames)
    
    # Print summary
    num_pairs = len(best_per_pair)
    num_radars = len(all_radar_tracks)
    expected_pairs = num_radars * (num_radars - 1)  # Directed pairs
    print(f"\n  Summary: Calibrated {num_pairs}/{expected_pairs} radar pairs")
    print(f"  Mean residual: {np.mean([c['residual'] for c in best_per_pair.values()]):.3f}")
    
    # Mark processed
    await mark_frames_processed(pool, frame_start, frame_end)
    
    return True

async def calibration_loop(pool):
    """Main loop: check for complete frame sets and trigger calibration"""
    last_calibrated_frame = 0
    
    while True:
        try:
            # Get current frame status
            frame_status = await get_frame_status(pool)
            
            if not frame_status:
                await asyncio.sleep(CHECK_INTERVAL)
                continue
            
            # Find minimum frame number across all radars
            min_frame = min(frame_status.values())
            num_radars = len(frame_status)
            
            # Check if we have enough frames to calibrate
            if min_frame >= last_calibrated_frame + CALIBRATION_WINDOW:
                frame_start = last_calibrated_frame + 1
                frame_end = min_frame
                
                # Ensure we have at least CALIBRATION_WINDOW frames
                if frame_end - frame_start + 1 < CALIBRATION_WINDOW:
                    await asyncio.sleep(CHECK_INTERVAL)
                    continue
                
                # Use exactly CALIBRATION_WINDOW frames
                frame_start = frame_end - CALIBRATION_WINDOW + 1
                
                print(f"\n{'='*60}")
                print(f"TRIGGER: All {num_radars} radars have reached frame #{min_frame}")
                print(f"{'='*60}")
                print(f"  Radar status:")
                for radar_name, frame_num in sorted(frame_status.items()):
                    print(f"    {radar_name}: frame #{frame_num}")
                
                # Run calibration
                success = await run_calibration_on_frames(pool, frame_start, frame_end)
                
                if success:
                    last_calibrated_frame = frame_end
                    print(f"\n  Next calibration will trigger when all radars reach frame #{last_calibrated_frame + CALIBRATION_WINDOW}")
                else:
                    print(f"\n  ✗ Calibration failed - missing frames")
            
        except Exception as e:
            print(f"Error in calibration loop: {e}")
            import traceback
            traceback.print_exc()
        
        await asyncio.sleep(CHECK_INTERVAL)

async def init_db(pool):
    """Initialize database tables"""
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS calibration_results (
                id SERIAL PRIMARY KEY,
                ref_radar VARCHAR(32) NOT NULL,
                target_radar VARCHAR(32) NOT NULL,
                position_x FLOAT NOT NULL,
                position_y FLOAT NOT NULL,
                orientation_deg FLOAT NOT NULL,
                residual FLOAT,
                num_frames INT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

async def wait_for_db():
    """Wait for database"""
    while True:
        try:
            conn = await asyncpg.connect(
                host=PG_HOST, user=PG_USER,
                password=PG_PASSWORD, database=PG_DB
            )
            await conn.close()
            break
        except Exception:
            print("Database not ready, retrying in 1s...")
            await asyncio.sleep(1)

async def main():
    """Main entry point"""
    print("="*60)
    print("Real-Time Radar Calibration Processor")
    print("Frame-Number-Based Triggering")
    print("="*60)
    print(f"Database: {PG_HOST}:{PG_DB}")
    print(f"Calibration window: {CALIBRATION_WINDOW} frames")
    print(f"Check interval: {CHECK_INTERVAL}s")
    print(f"Minimum radars: {MIN_RADARS}")
    print("="*60)
    
    await wait_for_db()
    print("✓ Database connection established")
    
    pool = await asyncpg.create_pool(
        host=PG_HOST, user=PG_USER,
        password=PG_PASSWORD, database=PG_DB,
        min_size=1, max_size=5
    )
    
    await init_db(pool)
    print("✓ Database initialized")
    
    print("\nWaiting for radar data...")
    print(f"Calibration will trigger when all radars have {CALIBRATION_WINDOW}+ frames\n")
    
    await calibration_loop(pool)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nShutting down...")
