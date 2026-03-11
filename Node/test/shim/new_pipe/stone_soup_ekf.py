import numpy as np
from typing import List, Dict, Tuple
from datetime import datetime, timedelta

from stonesoup.models.transition.linear import CombinedLinearGaussianTransitionModel, ConstantVelocity
from stonesoup.models.measurement.nonlinear import NonLinearGaussianMeasurement
from stonesoup.predictor.kalman import ExtendedKalmanPredictor
from stonesoup.updater.kalman import ExtendedKalmanUpdater
from stonesoup.hypothesiser.probability import PDAHypothesiser
from stonesoup.dataassociator.probability import JPDA
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
    """
    Multi-target JPDA tracker using Stone Soup framework.
    
    Uses PDAHypothesiser and JPDA data associator for proper JPDA implementation.
    """
    
    def __init__(self, 
                 dt: float = 0.1,
                 detection_probability: float = 0.9,
                 clutter_density: float = 0.01,
                 gate_probability: float = 0.99,
                 sigma_a: float = 0.1,
                 sigma_range: float = 0.035,
                 sigma_doppler: float = 0.0767,
                 sigma_angle: float = np.pi / 4.0):
        """
        Initialize JPDA tracker.
        
        Args:
            dt: Expected time step between frames (seconds)
            detection_probability: P(detection | target exists)
            clutter_density: False alarm density (per unit volume)
            gate_probability: Gating probability (e.g., 0.99 for chi-squared gating)
            sigma_a: Process noise (acceleration std dev, m/s²)
            sigma_range: Range measurement noise (meters)
            sigma_doppler: Doppler measurement noise (m/s)
            sigma_angle: Angle measurement noise (radians)
        """
        self.dt = dt
        self.detection_probability = detection_probability
        self.clutter_density = clutter_density
        self.gate_probability = gate_probability
        
        # Initialize Stone Soup transition model using built-in ConstantVelocity
        # Create independent CV models for x and y dimensions
        cv_x = ConstantVelocity(noise_diff_coeff=sigma_a**2)
        cv_y = ConstantVelocity(noise_diff_coeff=sigma_a**2)
        self.transition_model = CombinedLinearGaussianTransitionModel([cv_x, cv_y])
        
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

    def initialise_track(self, detection: Detection, track_id: int) -> Track:
        """
        Create a new tentative track from a detection.
        
        Args:
            detection: Detection object
            track_id: Unique track identifier
        
        Returns:
            New Track object
        """
        # Convert measurement to state estimate
        z = np.asarray(detection.state_vector).flatten()
        x_init = self._measurement_to_state(z)
        
        # Create initial state
        initial_state = GaussianState(
            StateVector(x_init),
            CovarianceMatrix(self.initial_covar),
            timestamp=detection.timestamp
        )
        
        # Create track
        track = Track([initial_state], id=str(track_id))
        
        # Store metadata
        self.track_metadata[track_id] = {
            'status': 'Tentative',
            'frame_count': 1,
            'hits': 1,
            'consecutive_misses': 0,
            'hit_history': [1],
        }
        
        return track
    
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
            
            # Predict using transition model
            prediction = self.predictor.predict(
                prior=track[-1],
                timestamp=timestamp
            )
            
            track.append(prediction)
    
    def update(self, detections: List[Detection], timestamp: datetime) -> None:
        """
        Update tracks with detections using JPDA.
        
        Args:
            detections: List of Detection objects
            timestamp: Current timestamp
        """
        if not self.tracks or not detections:
            # No tracks or detections to update
            if self.tracks:
                # Mark all tracks as missed
                for track_id in self.tracks.keys():
                    self.track_metadata[track_id]['consecutive_misses'] += 1
                    self.track_metadata[track_id]['hit_history'].append(0)
                    self.track_metadata[track_id]['frame_count'] += 1
            return
        
        # Perform JPDA data association
        # Returns a mapping from tracks to MultipleHypothesis objects
        associations = self.data_associator.associate(
            tracks=set(self.tracks.values()),
            detections=set(detections),
            timestamp=timestamp
        )
        
        # Update tracks based on JPDA associations
        for track_id, track in self.tracks.items():
            # Find association for this track
            multi_hypothesis = associations.get(track)
            
            if multi_hypothesis and len(multi_hypothesis) > 0:
                # JPDA returns multiple hypotheses with probabilities
                # Get the best hypothesis (or perform weighted update)
                
                # For simplicity, use the hypothesis with highest probability
                best_hypothesis = max(
                    multi_hypothesis,
                    key=lambda h: h.probability if hasattr(h, 'probability') else 0.0
                )
                
                if best_hypothesis.measurement:
                    # Update with measurement
                    try:
                        posterior = self.updater.update(best_hypothesis)
                        track.append(posterior)
                        
                        # Update metadata
                        self.track_metadata[track_id]['hits'] += 1
                        self.track_metadata[track_id]['consecutive_misses'] = 0
                        self.track_metadata[track_id]['hit_history'].append(1)
                    except Exception as e:
                        print(f"Update failed for track {track_id}: {e}")
                        # Treat as missed detection
                        self.track_metadata[track_id]['consecutive_misses'] += 1
                        self.track_metadata[track_id]['hit_history'].append(0)
                else:
                    # Missed detection (null hypothesis)
                    self.track_metadata[track_id]['consecutive_misses'] += 1
                    self.track_metadata[track_id]['hit_history'].append(0)
            else:
                # No association found
                self.track_metadata[track_id]['consecutive_misses'] += 1
                self.track_metadata[track_id]['hit_history'].append(0)
            
            self.track_metadata[track_id]['frame_count'] += 1
    
    def initialise_new_tracks(self, 
                             detections: List[Detection],
                             associations: Dict) -> None:
        """
        Create new tracks from unassociated detections.
        
        Args:
            detections: All detections this frame
            associations: Association results from JPDA
        """
        # Find detections not associated with any track
        associated_detections = set()
        for multi_hypothesis in associations.values():
            for hypothesis in multi_hypothesis:
                if hypothesis.measurement:
                    associated_detections.add(hypothesis.measurement)
        
        # Create tracks from unassociated detections
        unassociated = [d for d in detections if d not in associated_detections]
        
        for detection in unassociated:
            track_id = self.next_track_id
            self.next_track_id += 1
            
            track = self.initialise_track(detection, track_id)
            self.tracks[track_id] = track
    
    def manage_tracks(self,
                     min_detections: int = 5,
                     max_consecutive_misses: int = 5) -> None:
        """
        Confirm tentative tracks and delete stale tracks.
        
        Args:
            min_detections: Minimum hits to confirm
            max_consecutive_misses: Max misses before deletion
        """
        track_ids_to_delete = []
        
        for track_id, metadata in self.track_metadata.items():
            # Confirmation
            if metadata['status'] == 'Tentative' and metadata['hits'] >= min_detections:
                metadata['status'] = 'Confirmed'
                print(f"Track {track_id} confirmed with {metadata['hits']} hits")
            
            # Deletion
            if metadata['consecutive_misses'] >= max_consecutive_misses:
                track_ids_to_delete.append(track_id)
                print(f"Track {track_id} deleted: {metadata['consecutive_misses']} consecutive misses")
        
        # Remove flagged tracks
        for track_id in track_ids_to_delete:
            del self.tracks[track_id]
            del self.track_metadata[track_id]
    
    def process_frame(self,
                     detection_centroids: np.ndarray,
                     timestamp: datetime) -> Tuple[List, List]:
        """
        Process a single frame: predict, update, manage.
        
        Args:
            detection_centroids: Detections [range, doppler, angle] (N, 3)
            timestamp: Frame timestamp
        
        Returns:
            (confirmed_tracks, tentative_tracks)
        """
        # Convert to Stone Soup Detection objects
        detections = [
            Detection(
                StateVector(det_cent.reshape(-1, 1)),
                timestamp=timestamp
            )
            for det_cent in detection_centroids
        ]
        
        # Step 1: Predict all existing tracks
        if self.tracks:
            self.predict(timestamp)
        
        # Step 2: Update existing tracks with JPDA
        associations = {}
        if self.tracks and detections:
            self.update(detections, timestamp)
            
            # Re-run association to find unassociated detections
            associations = self.data_associator.associate(
                tracks=set(self.tracks.values()),
                detections=set(detections),
                timestamp=timestamp
            )
        
        # Step 3: Initialize new tracks from unassociated detections
        if detections:
            self.initialise_new_tracks(detections, associations)
        
        # Step 4: Manage tracks (confirm/delete)
        self.manage_tracks()
        
        # Extract results
        return self._extract_track_results()
    
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
                'ConsecutiveMisses': metadata['consecutive_misses']
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