import numpy as np
from typing import List, Dict, Tuple
from datetime import datetime, timedelta

from dataclasses import dataclass, field

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

from stonesoup.types.hypothesis import SingleHypothesis

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
            z += np.random.multivariate_normal(np.zeros(3), self.noise_covar).reshape(-1, 1)
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


class JPDATracker:
    @dataclass
    class AssociationData:
        probabilities_tracks_detections = None
        probabilities_detections_non_clutter = None 
        probabilities_effective_track_hit = None 

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
        
    def __init__(self, dt=0.1, detection_probability=0.9, clutter_density=0.01, gating_threshold=0.5, **kwargs):
        sigma_a = kwargs.get('sigma_a', 0.1)
        sigma_range = kwargs.get('sigma_range', 0.1)
        sigma_doppler = kwargs.get('sigma_doppler', 0.1)
        sigma_angle = kwargs.get('sigma_angle', np.pi / 4.0)

        self.dt = dt
        self.prob_detect = detection_probability
        self.clutter_density = clutter_density
        self.gating_threshold = gating_threshold
        
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

    """
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
                'StateCovariance': state.covariance,
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
    """

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
        associations = self.AssociationData()
        if self.tracks:
            #associations = self.data_associator.associate(
            #    tracks=set(self.tracks.values()),
            #    detections=set(detections),
            #    timestamp=timestamp
            #)
            # Pass the pre-computed associations to avoid re-calculating inside update
            
            #3 lists, of size n, where n is the number of tracks
            associations = self.get_soft_associations_and_marginals(detections,
                                                                    self.tracks,
                                                                    self.prob_detect,
                                                                    self.clutter_density,
                                                                    self.gating_threshold,
                                                                    )
            
            self.update(detections, timestamp, associations=associations)
        
        print(associations)
        # Step 3: Initialize new tracks from same associations
        if detections:
            self.initialise_new_tracks(detections, associations)

        # New Step: Merge similar tracks BEFORE management
        self.remove_duplicates(threshold=30.0)
        
        # Step 4: Manage tracks
        self.manage_tracks()
        
        # Extract results
        return self._extract_track_results()

    #associates (range, doppler, angle) detections with existing tracks

    def get_soft_associations_and_marginals(self, detection_centroids: List[Detection],
                                            track_dict: Dict,
                                            detection_probability: float,
                                            clutter_density: float,
                                            gating_threshold: float,
                                            use_track_exclusion: bool = True) -> AssociationData:
        """
        Calculate soft associations and marginal probabilities.

        Args:
            detection_centroids: List of Detection objects with measurement vectors [range, doppler, angle]
            track_dict: Dictionary of tracks
            detection_probability: P(detection | target exists)
            clutter_density: False alarm density
            gating_threshold: Mahalanobis distance gating threshold
            use_exclusion:  If False, allow multiple tracks to claim same detection (default).
                                    - this will work when detections are spatially separate across tracks
                                    (but there may be repeated detections of the same object)
                            If True, use JPDA with mutual track exclusion.

        Returns:
            AssociationData with association probabilities
        """
        
        associations = self.AssociationData()
        
        num_detections = 0
        num_tracks = 0
        
        if detection_centroids is not None and len(detection_centroids) > 0:
            print("Detections (range, doppler, angle):")
            print(detection_centroids)
            num_detections = len(detection_centroids)
        
        if track_dict:
            for track_id, track_info in track_dict.items():
                status = self.track_metadata.get(track_id, {}).get('status', 'Unknown')
                print(f"Track_ID {track_id}, Status {status}")
        num_tracks = len(track_dict)
        
        distance_matrix = self.get_distance_matrix(detection_centroids, track_dict, gating_threshold, self.measurement_model)
        
        if distance_matrix is not None and distance_matrix.size > 0:
            if use_track_exclusion:
                # JPDA with mutual exclusion: each detection from exactly one source
                associations = self.calculate_association_probabilities_exclude(
                    distance_matrix,
                    detection_probability,
                    clutter_density
                )
            else:
                print("shouldn't be here")
                pass
                # Simplified: allow multiple tracks to claim same detection
                #associations = calculate_association_probabilities_nonexclude(
                #    distance_matrix,
                #    detection_probability,
                #    clutter_density
                #)
        else:
            # No detections or no tracks
            probabilities_tracks_detections = np.zeros((num_tracks, num_detections + 1))
            probabilities_detections_non_clutter = np.ones(num_detections)
            probabilities_effective_track_hit = np.zeros(num_tracks)

            associations.probabilities_tracks_detections = probabilities_tracks_detections
            associations.probabilities_detections_non_clutter = probabilities_detections_non_clutter
            associations.probabilities_effective_track_hit = probabilities_effective_track_hit
        
        return associations
        

    #potentially slower because it uses jpda_events
    def calculate_association_probabilities_exclude(self,distance_matrix: np.ndarray,
                                                detection_probability: float,
                                                clutter_density: float,
                                                relaxed=False) -> AssociationData:
        """
        Calculate soft association probabilities WITH mutual exclusion (JPDA).
        
        Only allows each detection to be assigned to at most one track.
        Respects global assignment constraints via feasible joint events.
        
        This is the "true JPDA" approach where tracks must exclude each other
        from claiming the same detection.
        
        Args:
            distance_matrix: Mahalanobis distances, shape (n_det, n_trk)
                            Set to np.inf for gated-out pairs
            detection_probability: P(detection | target exists)
            clutter_density: False alarm density
            relaxed:        allows each track to have multiple detections - better for unstable centroiding algorithm
        
        Returns:
            AssociationData with marginalized probabilities from JPDA events
        """
        associations = self.AssociationData()
        
        n_trk = distance_matrix.shape[0]
        n_det = distance_matrix.shape[1]
        
        # Initialize output
        probabilities_tracks_detections = np.zeros((n_trk, n_det + 1))
        probabilities_detections_clutter = np.zeros(n_det)
        probabilities_detections_non_clutter = np.ones(n_det)
        probabilities_effective_track_hit = np.zeros(n_trk)
        
        max_num_feasible_joint_events = 3
        
        # Step 1: Convert distances to likelihoods
        likelihood_matrix = self.get_likelihood_matrix(distance_matrix, detection_probability, clutter_density)
        
        # Step 2: Generate feasible joint events (enforces mutual exclusion)
       
        #if relaxed:
        #    print("jpda_events_relaxed not defined")
        #    #FJE, FJE_Probs = jpda_events_relaxed(likelihood_matrix, max_num_feasible_joint_events)
        #else:
        
        FJE, FJE_Probs = self.jpda_events(likelihood_matrix, max_num_feasible_joint_events)
        # Step 3: Marginalize to get association probabilities
        probabilities_tracks_detections, probabilities_detections_clutter, probabilities_effective_track_hit = \
            self.compute_marginal_probabilities_from_events(
                FJE, FJE_Probs,
                n_det,
                n_trk
            )
        
        # Convert clutter probabilities to non-clutter probabilities
        probabilities_detections_non_clutter = 1.0 - probabilities_detections_clutter
        
        associations.probabilities_tracks_detections = probabilities_tracks_detections
        associations.probabilities_detections_non_clutter = probabilities_detections_non_clutter
        associations.probabilities_effective_track_hit = probabilities_effective_track_hit
        
        return associations

    def compute_marginal_probabilities_from_events(self,FJE: np.ndarray, 
                                                FJE_Probs: np.ndarray,
                                                num_detections: int,
                                                num_tracks: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Compute marginal association probabilities from feasible joint events.
        
        Takes a set of weighted joint events and marginalizes to get:
        - P(detection_j assigned to track_i)
        - P(detection_j is clutter)
        - P(track_i receives no detection / is missed)
        
        Args:
            FJE: Feasible Joint Events array, shape (n_trk+1, n_det, n_events)
                event[0, d] = 1 means detection d is clutter
                event[t+1, d] = 1 means detection d assigned to track t
            FJE_Probs: Event probabilities, shape (n_events,), sum to 1.0
            num_detections: Number of detections
            num_tracks: Number of tracks
        
        Returns:
            probabilities_tracks_detections: shape (n_trk, n_det+1)
                                            Last column is P(miss | track)
            probabilities_detections_clutter: shape (n_det,)
            probabilities_effective_track_hit: shape (n_trk,)
        """
        # Initialize accumulators
        probabilities_tracks_detections = np.zeros((num_tracks, num_detections + 1))
        probabilities_detections_clutter = np.zeros(num_detections)
        probabilities_effective_track_hit = np.zeros(num_tracks)
        
        # Marginalize over all events
        for k in range(FJE.shape[2]):  # Iterate over events
            event = FJE[:, :, k]
            event_probability = FJE_Probs[k]
            
            # Process each detection
            for j in range(num_detections):
                # If detection j is clutter in this event
                if event[0, j] == 1:
                    probabilities_detections_clutter[j] += event_probability
                
                # If detection j is assigned to a track in this event
                for i in range(num_tracks):
                    if event[i+1, j] == 1:
                        probabilities_tracks_detections[i, j] += event_probability
            
            # Process each track's missed detection probability
            for i in range(num_tracks):
                # If track i received no detection in this event
                if np.all(event[i + 1, :] == 0):
                    probabilities_tracks_detections[i, -1] += event_probability
                    probabilities_effective_track_hit[i] += 0  # No hit in this event
        
        # Normalize per-track probabilities (each row sums to 1.0)
        for i in range(num_tracks):
            row_sum = np.sum(probabilities_tracks_detections[i, :])
            if row_sum > 0:
                probabilities_tracks_detections[i, :] /= row_sum
            
            # Effective hit = sum of all detection association probabilities
            probabilities_effective_track_hit[i] = np.sum(
                probabilities_tracks_detections[i, :num_detections]
            )
        
        return probabilities_tracks_detections, probabilities_detections_clutter, probabilities_effective_track_hit

    def get_likelihood_matrix(self,distance_matrix: np.ndarray, 
                            detection_probability: float, 
                            clutter_density: float) -> np.ndarray:
        """Calculate likelihood matrix from distance matrix."""
        n_trk = distance_matrix.shape[0]
        n_det = distance_matrix.shape[1]
        
        likelihood_matrix = np.zeros((n_trk + 1, n_det + 1))
        
        # Column 0: missed detection, Row 0: clutter
        likelihood_matrix[:,0] = 1 - detection_probability
        likelihood_matrix[0,:] = clutter_density
        
        for i in range(n_trk):
            for j in range(n_det):
                likelihood_matrix[i + 1, j + 1] = detection_probability * np.exp(-0.5 * distance_matrix[i, j])
        
        return likelihood_matrix


    def get_distance_matrix(self, detection_centroids: List[Detection],
                            track_dict: Dict,
                            gating_threshold: float,
                            model: NonLinearGaussianMeasurement) -> Optional[np.ndarray]:
        """
        Calculate distance matrix between detections and tracks.

        Args:
            detection_centroids: List of Detection objects with measurement vectors
            track_dict: Dictionary of tracks
            gating_threshold: Gate size threshold

        Returns:
            Distance matrix of shape (num_detections, num_tracks)
        """
        
        if not track_dict or detection_centroids is None or len(detection_centroids) == 0:
            return None
        
        track_ids_list = list(track_dict.keys())
        n_det = len(detection_centroids)
        n_trk = len(track_ids_list)
        
        distance_matrix = np.zeros((n_trk, n_det))
        
        for trk_idx, track_id in enumerate(track_ids_list):
            track_info = track_dict[track_id]
            
            # Get predicted state from EKF
            # State: [x, y, vx, vy]
            state = track_info[-1]  # GaussianState
            state_vec = state.state_vector.flatten()  # [x, vx, y, vy]
            
            # Predicted measurement: [range, doppler, angle]
            meas_pred = model.function(state).flatten()
            
            # Measurement Jacobian
            H = model.jacobian(state)
            
            # Get covariance - handle both GaussianState (.covariance) and GaussianStatePrediction (.covar)
            state_covar = getattr(state, 'covariance', None) or getattr(state, 'covar', None)
            if state_covar is None:
                print(f"Warning: Could not get covariance from state of type {type(state)}")
                continue
            # Innovation covariance
            S = model.noise_covar + H @ state_covar @ H.T
            
            for det_idx in range(n_det):

                # Extract measurement vector from Detection object
                det_meas = detection_centroids[det_idx].state_vector.flatten()

                # Innovation: [range, doppler, angle]
                innovation = det_meas - meas_pred
                
                # Normalize angle difference to [-pi, pi]
                innovation[2] = np.arctan2(np.sin(innovation[2]), np.cos(innovation[2]))
                
                try:
                    squared_distance = innovation @ np.linalg.solve(S, innovation)
                except np.linalg.LinAlgError:
                    squared_distance = innovation.T @ np.linalg.pinv(S) @ innovation
                
                if squared_distance > gating_threshold:
                    distance_matrix[trk_idx,det_idx] = np.inf
                else:
                    distance_matrix[trk_idx,det_idx] = squared_distance
        
        print("Distance Matrix:")
        print(distance_matrix)
        
        return distance_matrix

    def jpda_events(self,likelihood_matrix: np.ndarray, 
                    max_events: int) -> Tuple[np.ndarray, np.ndarray]:
        """
        Basic feasible joint-event generator.

        likelihood_matrix shape: (n_trk + 1, n_det + 1)
        row 0: missed-detection factors for tracks (col 1..)
        col 0: clutter factors for detections (row 1..)

        Returns:
        FJE: shape (n_trk+1, n_det, n_events)
            event[0,d]=1 -> detection d is clutter
            event[t+1,d]=1 -> detection d assigned to track t
        FJE_Probs: normalized event probabilities
        """
        n_det = likelihood_matrix.shape[1] - 1
        n_trk = likelihood_matrix.shape[0] - 1

        if n_det < 0 or n_trk < 0:
            return np.zeros((0, 0, 0)), np.array([])

        events = []
        weights = []

        assign = [-1] * n_det          # -1 means clutter, else track index [0..n_trk-1]
        used_tracks = [False] * n_trk

        def finalize_event():
            event = np.zeros((n_trk+1, n_det), dtype=int)
            w = 1.0

            assigned_tracks = set()
            for d in range(n_det):
                t = assign[d] #a detection may only be assigned to one track
                if t < 0:
                    #classify detection d as clutter
                    event[0, d] = 1
                    w *= likelihood_matrix[0, d + 1]
                else:
                    #associate detection d with track t
                    event[t + 1,d] = 1
                    w *= likelihood_matrix[t + 1,d+1]
                    assigned_tracks.add(t)

            # missed-detection contribution for unassigned tracks
            for t in range(n_trk):
                if t not in assigned_tracks:
                    w *= likelihood_matrix[t + 1,0]

            events.append(event)
            weights.append(w)

        def dfs(d_idx: int):
            if d_idx == n_det:
                finalize_event()
                return

            # Option 1: clutter
            assign[d_idx] = -1
            dfs(d_idx + 1)

            # Option 2: assign to one unused track
            #a track may only be associated with one detection
            for t in range(n_trk):
                if not used_tracks[t]:
                    used_tracks[t] = True
                    assign[d_idx] = t
                    dfs(d_idx + 1)
                    used_tracks[t] = False

        dfs(0)

        if not events:
            return np.zeros((n_trk+1, n_det, 1), dtype=int), np.array([1.0])

        weights = np.asarray(weights, dtype=float)

        # keep top-k events
        k = max(1, int(max_events))
        if len(weights) > k:
            idx = np.argsort(weights)[-k:]
            events = [events[i] for i in idx]
            weights = weights[idx]

        s = np.sum(weights)
        if s < 0:
            print("jpda_events: SUM of WEIGHTS should be positive")
            exit()
            #probs = np.ones(len(weights), dtype=float) / len(weights)
        else:
            probs = weights / s

        FJE = np.stack(events, axis=2)  # (n_det, n_trk+1, n_events)
        return FJE, probs


    # ...existing code...
    """
    def initialise_new_tracks(self, detections: List[Detection], associations: Dict) -> None:
        
        #Create new tracks from detections that are not strongly claimed by existing tracks.
        #Matches MATLAB claim < threshold_init logic.
        # threshold_init = 0.05 from MATLAB code
        threshold_init = 0.05

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
    """
    def initialise_new_tracks(self, detections: List[Detection], associations: 'JPDATracker.AssociationData') -> None:
        #Create new tracks from detections that are not strongly claimed by existing tracks.
        #Matches MATLAB claim < threshold_init logic.
        
        # threshold_init = 0.05 from MATLAB code
        threshold_init = 0.05
        
        for det_idx, detection in enumerate(detections):
            # Calculate 'Claim': Max probability any track identifies with this detection
            if associations.probabilities_tracks_detections is not None and associations.probabilities_tracks_detections.size > 0:
                claim = np.max(associations.probabilities_tracks_detections[:, det_idx])
            else:
                claim = 0.0
            
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
                    'bit_vector': [0, 0, 0, 0, 0, 0, 0, 1],  # 8-bit history window
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
                Pi = np.asarray(ti.covariance, dtype=float)
                Pj = np.asarray(tj.covariance, dtype=float)

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
    """
    def update(self, detections: List[Detection], timestamp: datetime, associations: Dict = None) -> None:
        #Matched to MATLAB: Soft JPDA Weighted Update (correctjpda equivalent).
        print(len(detections))
            # Calculate Effective Hit Probability (Sum of detection hypotheses)
            prob_hit = sum(float(h.probability) for h in multi_hypothesis if not isinstance(h.measurement, MissedDetection))
            
            # MATLAB threshold_hit_miss = 0.3
            if prob_hit < 0.3:
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
"""
    def update(self, detections: List[Detection], timestamp: datetime, 
           associations: 'JPDATracker.AssociationData' = None) -> None:
        """Matched to MATLAB: Soft JPDA Weighted Update (correctjpda equivalent)."""
        print(len(detections))
        
        if associations is None:
            print("Error, failed to associate")
            return
        
        # Build track_id to index mapping
        track_ids_list = list(self.tracks.keys())
        track_id_to_idx = {tid: idx for idx, tid in enumerate(track_ids_list)}
        n_det = len(detections)
        
        for track_id, track in self.tracks.items():
            print("============================")
            print(f"Associated Track {track_id}")
            
            track_idx = track_id_to_idx[track_id]
            
            # Get association probabilities for this track
            track_probs = associations.probabilities_tracks_detections[track_idx, :]
            prob_hit = associations.probabilities_effective_track_hit[track_idx]
            
            # MATLAB threshold_hit_miss = 0.3
            if prob_hit < 0.3:
                self._register_miss(track_id)
                # Keep the predicted state (already appended by predict())
                continue
            
            # Soft Update: Moment Matching (True JPDA)
            try:
                posteriors = []
                weights = []
                weighted_meas = np.zeros((3, 1))
                
                # Get the current predicted state (appended by predict())
                predicted_state = track[-1]
                
                # Process each detection association
                for det_idx in range(n_det):
                    prob = track_probs[det_idx]
                    if prob > 0:
                        weights.append(prob)
                        detection = detections[det_idx]
                        
                        meas_hypothesis = SingleHypothesis(
                            prediction=predicted_state,
                            measurement=detection,
                            measurement_prediction=None  # Will be computed by updater
                        )

                        # Update the prediction with this detection
                        hypothesis = self.updater.update(meas_hypothesis, timestamp=timestamp)
                        posteriors.append(hypothesis)
                        weighted_meas += prob * detection.state_vector
                
                # Process miss hypothesis (last column)
                miss_prob = track_probs[-1]
                if miss_prob > 0:
                    weights.append(miss_prob)
                    posteriors.append(predicted_state)
                    exp_z = self.measurement_model.function(predicted_state)
                    weighted_meas += miss_prob * exp_z
                
                self.track_metadata[track_id]['last_weighted_meas'] = weighted_meas.flatten()
                
                # Fuse using Mixture of Gaussians (Moment Matching)
                if posteriors:
                    # Sum weighted state vectors
                    x_fused_array = sum(w * p.state_vector for w, p in zip(weights, posteriors))
                    
                    # Wrap in StateVector - needs to be column vector
                    x_fused = StateVector(x_fused_array.reshape(-1, 1) if x_fused_array.ndim == 1 
                                        else x_fused_array)
                    
                    # Fuse covariances with spreading term
                    P_fused = sum(w * (p.covar + (p.state_vector - x_fused) @ (p.state_vector - x_fused).T) 
                                for w, p in zip(weights, posteriors))
                    
                    # Wrap covariance matrix
                    P_fused = CovarianceMatrix(P_fused)
                    
                    # REPLACE the predicted state with the fused state
                    track[-1] = GaussianState(x_fused, P_fused, timestamp=timestamp)
                    self._register_hit(track_id, prob_hit)
            except Exception as e:
                print(f"Update exception for track {track_id}: {e}")
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


    def _maha_dist(self, state1: State, state2: State):
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
    
    tracker = JPDATracker(
        dt=0.1,
        detection_probability=0.9,
        clutter_density=0.01,
        gating_threshold=0.8
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