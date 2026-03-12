import numpy as np
from typing import List, Dict, Tuple
from datetime import datetime, timedelta

from stonesoup.models.transition.linear import CombinedLinearGaussianTransitionModel, ConstantVelocity
from stonesoup.models.measurement.nonlinear import NonLinearGaussianMeasurement
from stonesoup.predictor.kalman import ExtendedKalmanPredictor
from stonesoup.updater.kalman import ExtendedKalmanUpdater
from stonesoup.hypothesiser.probability import PDAHypothesiser
from stonesoup.dataassociator.probability import JPDA
from stonesoup.types.detection import Detection, MissedDetection

from stonesoup.types.state import (
    State, GaussianState, StateVector, CovarianceMatrix
)
from stonesoup.types.track import Track
from stonesoup.types.detection import Detection


class RDANonLinearMeasurementModel(NonLinearGaussianMeasurement):
    """
    State: [x, vx, y, vy] (IMPORTANT for Combined ConstantVelocity model)
    Measurement: [range, doppler, angle]
    """

    @property
    def ndim_meas(self) -> int:
        return 3

    def function(self, state, noise=False, **kwargs) -> np.ndarray:
        state_vec = state.state_vector if hasattr(state, 'state_vector') else state
        x, vx, y, vy = state_vec.flat  # <-- fixed order

        r = np.sqrt(x**2 + y**2)
        d = (x * vx + y * vy) / r if r > 1e-6 else 0.0
        a = np.arctan2(y, x)

        z = np.array([[r], [d], [a]])
        if noise:
            z += np.random.multivariate_normal(np.zeros(3), self.covar()).reshape(-1, 1)
        return z
    
    def jacobian(self, state, **kwargs) -> np.ndarray:
        state_vec = state.state_vector if hasattr(state, 'state_vector') else state
        x, vx, y, vy = state_vec.flat  # <-- fixed order

        r2 = x**2 + y**2
        r = np.sqrt(r2)
        if r < 1e-6:
            return np.zeros((3, 4))

        # Derivatives wrt x and y first
        dd_dx = (vx * r2 - x * (x * vx + y * vy)) / (r * r2)
        dd_dy = (vy * r2 - y * (x * vx + y * vy)) / (r * r2)

        # Columns correspond to [x, vx, y, vy]
        H = np.array([
            [x / r,    0.0, y / r,    0.0],
            [dd_dx,    x / r, dd_dy,  y / r],
            [-y / r2,  0.0, x / r2,   0.0]
        ])
        return H


class StoneSoupJPDATracker:
    def _setup_components(self, kwargs):
        """Initializes transition models and noise parameters."""
        # Noise parameters (defaults matched to your MATLAB/Python config)
        sigma_a = kwargs.get('sigma_a', 0.1)
        sigma_range = kwargs.get('sigma_range', 0.1)
        sigma_doppler = kwargs.get('sigma_doppler', 0.1)
        sigma_angle = kwargs.get('sigma_angle', np.pi / 4.0)

        # Transition model: Combined Constant Velocity in 2D
        # State vector: [x, vx, y, vy]
        self.transition_model = CombinedLinearGaussianTransitionModel([
            ConstantVelocity(sigma_a**2),
            ConstantVelocity(sigma_a**2)
        ])

        # Initialize Stone Soup measurement model
        self.measurement_model = RDANonLinearMeasurementModel(
            ndim_state=4,
            mapping=(0, 1, 2, 3),
            noise_covar=CovarianceMatrix(np.diag([
                sigma_range**2,
                sigma_doppler**2,
                sigma_angle**2
            ]))
        )
        
    def __init__(self, dt=0.1, detection_probability=0.9, clutter_density=0.01, gate_probability=0.99, **kwargs):
        sigma_a = kwargs.get('sigma_a', 0.1)
        sigma_range = kwargs.get('sigma_range', 0.1)
        sigma_doppler = kwargs.get('sigma_doppler', 0.1)
        sigma_angle = kwargs.get('sigma_angle', np.pi / 4.0)

        self.dt = dt
        self.prob_detect = detection_probability
        self.clutter_density = clutter_density
        self.gate_probability = gate_probability
        
        # Standard Stone Soup setup
        self._setup_components(kwargs)
        
        self.next_track_id = 1
        self.tracks: Dict[int, Track] = {}
        self.track_metadata: Dict[int, Dict] = {}

        # Initialize Stone Soup measurement model
        self.measurement_model = RDANonLinearMeasurementModel(
            ndim_state=4,
            mapping=(0, 1, 2, 3),
            noise_covar=CovarianceMatrix(np.diag([
                sigma_range**2,
                sigma_doppler**2,
                sigma_angle**2
            ]))
        )
        
        # Predictor and updater (use Extended Kalman for nonlinear measurement)
        self.predictor = ExtendedKalmanPredictor(self.transition_model)
        self.updater = ExtendedKalmanUpdater(self.measurement_model)
        
        # PDA Hypothesiser for generating track-detection hypotheses
        self.hypothesiser = PDAHypothesiser(
            predictor=self.predictor,
            updater=self.updater,
            clutter_spatial_density=clutter_density,
            prob_detect=detection_probability,
            prob_gate=gate_probability
        )
        
        # JPDA data associator
        self.data_associator = JPDA(hypothesiser=self.hypothesiser)
        
        # Track management
        self.next_track_id = 1
        self.tracks: Dict[int, Track] = {}
        self.track_metadata: Dict[int, Dict] = {}
        
        # Store initial state covariance for new tracks
        self.initial_covar = self._compute_initial_covariance()
    
    def _compute_initial_covariance(self) -> np.ndarray:
        sigma_x = 0.5
        sigma_vx = 1.0
        sigma_y = 0.5
        sigma_vy = 1.0
        # order [x, vx, y, vy]
        return np.diag([sigma_x**2, sigma_vx**2, sigma_y**2, sigma_vy**2])

    def _measurement_to_state(self, z: np.ndarray) -> np.ndarray:
        # z = [range, doppler, angle]
        range_val, doppler, angle = z
        x = range_val * np.cos(angle)
        y = range_val * np.sin(angle)
        vx = doppler * np.cos(angle)
        vy = doppler * np.sin(angle)
        # return in [x, vx, y, vy] order
        return np.array([x, vx, y, vy])

    def _extract_track_results(self) -> Tuple[List, List]:
        confirmed, tentative = [], []
        for track_id, track in self.tracks.items():
            if len(track) == 0:
                continue

            metadata = self.track_metadata[track_id]
            state = track[-1]
            sv = state.state_vector.flatten()  # [x, vx, y, vy]
            x, vx, y, vy = sv[0], sv[1], sv[2], sv[3]

            track_dict = {
                'TrackID': track_id,
                # expose as [x, y, vx, vy] to keep test code unchanged
                'State': np.array([x, y, vx, vy]),
                'StateCovariance': state.covar,
                'Age': len(track),
                'Status': metadata['status'],
                'Hits': metadata['hits'],
                'ConsecutiveMisses': metadata['consecutive_misses']
            }

            if metadata['status'] == 'Confirmed':
                confirmed.append(track_dict)
            else:
                tentative.append(track_dict)
        return confirmed, tentative

    # ...existing code...
    def initialise_new_tracks(self, detections: List[Detection], associations: Dict) -> None:
        """
        Create new tracks from detections that are not strongly claimed by existing tracks.
        Matches MATLAB claim < threshold_init logic.
        """
        # Raised from 0.05 to allow new tracks near existing ones (multi-target)
        threshold_init = 0.3

        for detection in detections:
            # Calculate 'Claim': Max probability any track identifies with this detection
            claim = 0.0
            if associations:
                for multi_hypothesis in associations.values():
                    for hypothesis in multi_hypothesis:
                        if hypothesis.measurement == detection:
                            prob = float(getattr(hypothesis, 'probability', 0.0))
                            if prob > claim:
                                claim = prob

            # If no existing track strongly claims this detection, spawn a new one
            if claim < threshold_init:
                track_id = self.next_track_id
                self.next_track_id += 1
                
                # Create the initial track object
                new_track = self._create_new_track_object(detection, track_id)
                self.tracks[track_id] = new_track
                
                # Initialize metadata with 8-bit history matching MATLAB
                self.track_metadata[track_id] = {
                    'status': 'Tentative',
                    'hits': 1,
                    'consecutive_misses': 0,
                    'bit_vector': [0, 0, 0, 0, 0, 0, 0, 1], # 8-bit history window
                    'prob_history': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
                    'frame_count': 1
                }

    def _create_new_track_object(self, detection: Detection, track_id: int) -> Track:
        """Helper to convert detection to initial state and Track object."""
        z = np.asarray(detection.state_vector).flatten()
        x_init = self._measurement_to_state(z)
        
        initial_state = GaussianState(
            StateVector(x_init),
            CovarianceMatrix(self.initial_covar),
            timestamp=detection.timestamp
        )
        
        return Track([initial_state], id=str(track_id))
    
    def compute_pairwise_mahalanobis_distances(self, tracks_list: List[Dict], position_only: bool = False) -> Dict[Tuple[int, int], float]:
        """
        Compute pairwise Mahalanobis distance between tracks provided as a list of dictionaries.

        Args:
            tracks_list: A list of dictionaries containing 'TrackID', 'State', and 'StateCovariance'.
            position_only: If True, use [x, y] only (indices 0 and 2); 
                           otherwise use full state [x, vx, y, vy].

        Returns:
            A dictionary where keys are tuples of (TrackID_A, TrackID_B) and 
            values are the Mahalanobis distances.
        """
        distances = {}
        n = len(tracks_list)
        if n < 2:
            return distances

        # Indices for state selection: [x, vx, y, vy] -> [0, 2] for position
        # Note: Your dictionary 'State' is flat, usually [x, vx, y, vy]
        idx = [0, 2] if position_only else [0, 1, 2, 3]

        for i in range(n):
            for j in range(i + 1, n):
                track_a = tracks_list[i]
                track_b = tracks_list[j]

                # Extract ID, State Vector, and Covariance Matrix
                id_a = track_a['TrackID']
                id_b = track_b['TrackID']
                
                x_a = np.asarray(track_a['State'], dtype=float).reshape(-1)
                x_b = np.asarray(track_b['State'], dtype=float).reshape(-1)
                P_a = np.asarray(track_a['StateCovariance'], dtype=float)
                P_b = np.asarray(track_b['StateCovariance'], dtype=float)

                # Innovation (difference in state)
                d = x_a[idx] - x_b[idx]
                
                # Associated Covariance (Sum of track uncertainties)
                # Adding a small epsilon for numerical stability during inversion
                S = P_a[np.ix_(idx, idx)] + P_b[np.ix_(idx, idx)] + 1e-9 * np.eye(len(idx))
                
                try:
                    S_inv = np.linalg.pinv(S)
                    dist = float(np.sqrt(d.T @ S_inv @ d))
                    if np.isfinite(dist):
                        distances[(id_a, id_b)] = dist
                except np.linalg.LinAlgError:
                    continue

        return distances

    def average_tentative_mahalanobis_distance(self, position_only: bool = False) -> float:
        """
        Compute average pairwise Mahalanobis distance between tentative tracks.

        Args:
            position_only: If True, use [x, y] only; otherwise use full state [x, vx, y, vy].

        Returns:
            Average distance across unique track pairs.
            Returns 0.0 if fewer than 2 tentative tracks exist.
        """
        tentative_ids = [
            tid for tid, meta in self.track_metadata.items()
            if meta.get('status') == 'Tentative' and tid in self.tracks and len(self.tracks[tid]) > 0
        ]

        if len(tentative_ids) < 2:
            return 0.0

        # Indices for state selection
        idx = [0, 2] if position_only else [0, 1, 2, 3]

        distances = []
        for i in range(len(tentative_ids)):
            for j in range(i + 1, len(tentative_ids)):
                ti = self.tracks[tentative_ids[i]][-1]
                tj = self.tracks[tentative_ids[j]][-1]

                xi = np.asarray(ti.state_vector, dtype=float).reshape(-1)
                xj = np.asarray(tj.state_vector, dtype=float).reshape(-1)
                Pi = np.asarray(ti.covar, dtype=float)
                Pj = np.asarray(tj.covar, dtype=float)

                d = xi[idx] - xj[idx]
                S = Pi[np.ix_(idx, idx)] + Pj[np.ix_(idx, idx)] + 1e-9 * np.eye(len(idx))
                S_inv = np.linalg.pinv(S)

                dist = float(np.sqrt(d.T @ S_inv @ d))
                if np.isfinite(dist):
                    distances.append(dist)

        return float(np.mean(distances)) if distances else 0.0

    def predict(self, timestamp: datetime) -> None:
        """
        Predict all tracks to the given timestamp.
        
        Args:
            timestamp: Target timestamp
        """
        for track_id, track in self.tracks.items():
            if len(track) == 0:
                continue
            
            # Calculate time step
            time_interval = timestamp - track[-1].timestamp
            #print(time_interval)
            # Predict using transition model
            prediction = self.predictor.predict(
                prior=track[-1],
                timestamp=timestamp
            )
            
            track.append(prediction)
    
    def update(self, detections: List[Detection], timestamp: datetime, associations: Dict = None) -> None:
        """Matched to MATLAB: Soft JPDA Weighted Update (correctjpda equivalent)."""
        print(len(detections))
        """if not detections:
            for tid in self.tracks:
                exp_z = self.measurement_model.function(self.tracks[tid][-1])
                self.track_metadata[tid]['last_weighted_meas'] = exp_z.flatten()
                self._register_miss(tid)
            return"""

        #print(associations)
        if associations is None:
            associations = self.data_associator.associate(set(self.tracks.values()), set(detections), timestamp)

        for track_id, track in self.tracks.items():
            print("============================")
            print(f"Associated Track {track_id}")
            multi_hypothesis = associations.get(track)
            
            for h in multi_hypothesis:
                #if isinstance(h.measurement, MissedDetection) and h.probability > 0.8:
                    #self._register_miss(track_id)
                    #print("missed")
                    #print("===============")
                """print("--------")
                print(h.measurement)
                print(h.measurement.state_vector)
                print(f"prob: {h.probability}")
                print("===============")"""
                

            # Calculate Effective Hit Probability (Sum of detection hypotheses)
            prob_hit = sum(float(h.probability) for h in multi_hypothesis if not isinstance(h.measurement, MissedDetection))
            
            # Lowered from 0.3 to 0.15 so JPDA doesn't starve tracks in multi-target scenes
            if prob_hit < 0.15:
                self._register_miss(track_id)
                track.append(multi_hypothesis[0].prediction) 
                continue

            # Soft Update: Moment Matching (True JPDA)
            try:
                # Weighted mean state
                posteriors = []
                weights = []

                weighted_meas = np.zeros((3, 1))

                for h in multi_hypothesis:
                    p = float(h.probability)
                    if p > 0:
                        weights.append(p)
                        # If it is a real detection, update. If MissedDetection, use prediction.
                        if not isinstance(h.measurement, MissedDetection):
                            posteriors.append(self.updater.update(h))
                            weighted_meas += p * h.measurement.state_vector
                        else:
                            posteriors.append(h.prediction)
                            exp_z = self.measurement_model.function(h.prediction)
                            weighted_meas += p * exp_z

                self.track_metadata[track_id]['last_weighted_meas'] = weighted_meas.flatten()


                # Fuse using Mixture of Gaussians (Moment Matching)
                x_fused = sum(w * p.state_vector for w, p in zip(weights, posteriors))
                # Covariance includes spreading term
                P_fused = sum(w * (p.covar + (p.state_vector - x_fused) @ (p.state_vector - x_fused).T) 
                              for w, p in zip(weights, posteriors))

                track.append(GaussianState(x_fused, P_fused, timestamp=timestamp))
                self._register_hit(track_id, prob_hit)
            except Exception:
                self._register_miss(track_id)

    def _register_hit(self, track_id, prob):
        meta = self.track_metadata[track_id]
        meta['hits'] += 1
        meta['consecutive_misses'] = 0
        # Update Bit Vector (MATLAB: update_association_bit_vector)
        meta['bit_vector'] = (meta['bit_vector'][1:] + [1])
        meta['prob_history'] = (meta['prob_history'][1:] + [prob])

    def _register_miss(self, track_id):
        meta = self.track_metadata[track_id]
        meta['consecutive_misses'] += 1
        meta['bit_vector'] = (meta['bit_vector'][1:] + [0])
        meta['prob_history'] = (meta['prob_history'][1:] + [0.0])


    def initialise_track(self, detection: Detection, track_id: int) -> Track:
        # ... existing conversion ...
        self.track_metadata[track_id] = {
            'status': 'Tentative',
            'hits': 1,
            'consecutive_misses': 0,
            'bit_vector': [0, 0, 0, 0, 0, 0, 0, 1], # 8-bit history
            'prob_history': [0, 0, 0, 0, 0, 0, 0, 1.0]
        }
        return track
    
    def manage_tracks(self):
        """Matched to MATLAB: Bit-vector density confirmation."""
        to_delete = []
        for tid, meta in self.track_metadata.items():
            # Confirmation: 5 hits in last 8 frames (nnz of bit vector)
            if meta['status'] == 'Tentative' and sum(meta['bit_vector']) >= 5:
                meta['status'] = 'Confirmed'

            # Deletion: 5 consecutive misses
            if meta['consecutive_misses'] >= 5:
                to_delete.append(tid)

        for tid in to_delete:
            del self.tracks[tid]
            del self.track_metadata[tid]
    
    def process_frame(self,
                     detection_centroids: np.ndarray,
                     timestamp: datetime) -> Tuple[List, List]:
        # ...existing code converting centroids to detections...
        detections = [
            Detection(
                StateVector(centroid.reshape(-1, 1)),
                timestamp=timestamp
            )
            for label, (centroid, num_point) in detection_centroids.items()
        ]
        
        # Step 1: Predict all existing tracks
        if self.tracks:
            self.predict(timestamp)
        
        # Step 2: Global Association (Perform ONLY ONCE)
        associations = {}
        if self.tracks:
            associations = self.data_associator.associate(
                tracks=set(self.tracks.values()),
                detections=set(detections),
                timestamp=timestamp
            )
            # Pass the pre-computed associations to avoid re-calculating inside update
            self.update(detections, timestamp, associations=associations)
        
        # Step 3: Initialize new tracks from same associations
        if detections:
            self.initialise_new_tracks(detections, associations)

        # New Step: Merge similar tracks BEFORE management
        self.remove_duplicates(threshold=30.0)
        
        # Step 4: Manage tracks
        self.manage_tracks()
        
        # Extract results
        return self._extract_track_results()

    def remove_duplicates(self, threshold=7.0):
        """Matched to MATLAB: remove_duplicates using strength."""
        track_ids = list(self.tracks.keys())
        to_delete = set()

        # Strength = 0.5 * avg_prob + 0.5 * is_confirmed
        strengths = {}
        for tid in track_ids:
            meta = self.track_metadata[tid]
            avg_p = np.mean(meta['prob_history'])
            conf = 1.0 if meta['status'] == 'Confirmed' else 0.0
            strengths[tid] = 0.5 * avg_p + 0.5 * conf

        for i, id1 in enumerate(track_ids):
            if id1 in to_delete: continue
            for id2 in track_ids[i+1:]:
                if id2 in to_delete: continue
                
                dist = self._maha_dist(self.tracks[id1][-1], self.tracks[id2][-1])
                if dist < threshold:
                    # Delete the weaker one
                    if strengths[id1] > strengths[id2]:
                        to_delete.add(id2)
                    else:
                        to_delete.add(id1)
                        break

        for tid in to_delete:
            del self.tracks[tid]
            del self.track_metadata[tid]
    def _maha_dist(self, state1, state2):
        """MATLAB: maha2_avg logic."""
        dx = state1.state_vector - state2.state_vector
        P_avg = 0.5 * (state1.covar + state2.covar)
        return np.sqrt(dx.T @ np.linalg.pinv(P_avg) @ dx)

    def _extract_track_results(self) -> Tuple[List, List]:
        """Extract confirmed and tentative tracks."""
        confirmed = []
        tentative = []
        
        for track_id, track in self.tracks.items():
            if len(track) == 0:
                continue
            
            metadata = self.track_metadata[track_id]
            state = track[-1]
            
            track_dict = {
                'TrackID': track_id,
                'State': state.state_vector.flatten(),
                'StateCovariance': state.covar,
                'Age': len(track),
                'Status': metadata['status'],
                'Hits': metadata['hits'],
                'ConsecutiveMisses': metadata['consecutive_misses'],
                'Detection':  metadata.get('last_weighted_meas', np.array([0, 0, 0])) #weighted average of all associated detections
            }
            
            if metadata['status'] == 'Confirmed':
                confirmed.append(track_dict)
            else:
                tentative.append(track_dict)
        
        return confirmed, tentative


# ==================== EXAMPLE USAGE ====================

def test_stone_soup_jpda():
    """Test Stone Soup JPDA tracker with proper PDA hypothesiser."""
    
    tracker = StoneSoupJPDATracker(
        dt=0.1,
        detection_probability=0.9,
        clutter_density=0.01,
        gate_probability=0.99
    )
    
    current_time = datetime.now()
    
    for frame_idx in range(10):
        # Synthetic detections
        detections = np.array([
            [10.0, 1.5, 0.1],
            [15.0, -0.5, 0.3],
        ])
        
        frame_time = current_time + timedelta(seconds=frame_idx * 0.1)
        confirmed, tentative = tracker.process_frame(detections, frame_time)
        
        print(f"\n--- Frame {frame_idx} ---")
        print(f"Confirmed: {len(confirmed)}, Tentative: {len(tentative)}")
        
        for track in confirmed + tentative:
            print(f"  Track {track['TrackID']} ({track['Status']}): "
                  f"State={track['State'][:2]}, Hits={track['Hits']}, "
                  f"Misses={track['ConsecutiveMisses']}")


if __name__ == '__main__':
    test_stone_soup_jpda()