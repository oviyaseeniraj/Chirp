import numpy as np
import scipy.linalg
from scipy.stats import chi2
import logging

logger = logging.getLogger(__name__)

class JPDAEKF:
    """
    Extended Kalman Filter for JPDA Tracking.
    State: [px, py, vx, vy]
    Measurement: [u, r, rr] where u = pi * sin(azimuth)
    """
    def __init__(self, state, covariance, Q, R, dt=0.1):
        self.x = np.array(state, dtype=float).flatten()
        self.P = np.array(covariance, dtype=float)
        self.Q = np.array(Q, dtype=float)
        self.R = np.array(R, dtype=float)
        self.dt = dt

    def predict(self):
        """Standard LKF prediction for constant velocity model."""
        F = np.array([
            [1, 0, self.dt, 0],
            [0, 1, 0, self.dt],
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ])
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + self.Q
        return self.x, self.P

    def get_h_and_jacobian(self, x):
        """Measurement function and its Jacobian."""
        px, py, vx, vy = x
        r = np.sqrt(px**2 + py**2) + 1e-9
        rr = (px*vx + py*vy) / r
        
        # Spatial frequency u = pi * sin(az). 
        # az = atan2(px, py) relative to Y-axis? (matching Fusion Center convention)
        # sin(az) = px / r
        u = np.pi * px / r
        
        z_pred = np.array([u, r, rr])
        
        # Jacobian H [3x4]
        H = np.zeros((3, 4))
        
        # du/dpx = pi * (r^2 - px^2) / r^3 = pi * py^2 / r^3
        H[0, 0] = np.pi * py**2 / r**3
        H[0, 1] = -np.pi * px * py / r**3
        
        # dr/dpx = px/r
        H[1, 0] = px / r
        H[1, 1] = py / r
        
        # drr/dpx = (vx*r - rr*px) / r^2
        H[2, 0] = (vx * r - rr * px) / r**2
        H[2, 1] = (vy * r - rr * py) / r**2
        H[2, 2] = px / r
        H[2, 3] = py / r
        
        return z_pred, H

    def update_soft(self, associations, detections):
        """
        Update state using JPDA soft association.
        associations: probabilities [prob_miss, prob_det1, prob_det2, ...]
        detections: list of measurements [ [u, r, rr], ... ]
        """
        if len(detections) == 0:
            return self.x, self.P

        z_pred, H = self.get_h_and_jacobian(self.x)
        S = H @ self.P @ H.T + self.R
        S_inv = np.linalg.inv(S)
        K = self.P @ H.T @ S_inv
        
        prob_miss = associations[0]
        beta_i_list = associations[1:]
        
        # Combined innovation
        y_combined = np.zeros(3)
        for i, beta_i in enumerate(beta_i_list):
            innovation = detections[i] - z_pred
            y_combined += beta_i * innovation
            
        # State update
        self.x = self.x + K @ y_combined
        
        # Covariance update
        beta_total = sum(beta_i_list)
        P_updated = (np.eye(4) - K @ H) @ self.P
        
        # Spread of innovations
        y_spread = np.zeros((3, 3))
        for i, beta_i in enumerate(beta_i_list):
            y_i = detections[i] - z_pred
            y_spread += beta_i * np.outer(y_i, y_i)
        y_spread -= np.outer(y_combined, y_combined)
        
        self.P = (1 - beta_total) * self.P + beta_total * P_updated + K @ y_spread @ K.T
        
        return self.x, self.P

class JPDA:
    """Joint Probabilistic Data Association Logic."""
    def __init__(self, prob_detection=0.9, clutter_density=1e-4, gating_threshold=12.0):
        self.pd = prob_detection
        self.clutter_density = clutter_density
        self.gating_threshold = gating_threshold

    def calculate_marginals(self, filters, detections):
        """
        Calculate marginal association probabilities.
        Returns: matrix [num_tracks x (num_detections + 1)] 
                 where index 0 of cols is 'no detection' (miss).
        """
        num_tracks = len(filters)
        num_dets = len(detections)
        
        if num_tracks == 0:
            return np.empty((0, num_dets + 1))
        if num_dets == 0:
            return np.ones((num_tracks, 1))

        # 1. Gating and Likelihoods
        # matrix of likelihoods det i associated with track j
        # likelihoods[i][j]
        likelihoods = np.zeros((num_dets, num_tracks))
        gated_matrix = np.zeros((num_dets, num_tracks), dtype=bool)

        for j, kf in enumerate(filters):
            z_pred, H = kf.get_h_and_jacobian(kf.x)
            S = H @ kf.P @ H.T + kf.R
            S_inv = np.linalg.inv(S)
            det_S = np.linalg.det(S)
            
            for i, det in enumerate(detections):
                diff = det - z_pred
                mahalanobis_dist_sq = diff.T @ S_inv @ diff
                
                if mahalanobis_dist_sq <= self.gating_threshold:
                    gated_matrix[i, j] = True
                    # Gaussian likelihood
                    likelihood = (1.0 / np.sqrt((2 * np.pi)**3 * det_S)) * np.exp(-0.5 * mahalanobis_dist_sq)
                    likelihoods[i, j] = likelihood

        # 2. Joint Event Generation (Simplified/Exhaustive for small scale)
        # For N tracks and M detections, find all valid assignments
        # An event is a mapping: {track_j: det_i} or {track_j: None}
        # Constraint: A detection can be assigned to at most one track.
        
        events = []
        
        def generate_events(track_idx, current_event):
            if track_idx == num_tracks:
                events.append(current_event.copy())
                return
            
            # Option 1: Track idx has no detection
            current_event[track_idx] = -1 # -1 means miss
            generate_events(track_idx + 1, current_event)
            
            # Option 2: Track idx has a gated detection not already used
            used_dets = [d for t, d in current_event.items() if t < track_idx and d != -1]
            for i in range(num_dets):
                if gated_matrix[i, track_idx] and i not in used_dets:
                    current_event[track_idx] = i
                    generate_events(track_idx + 1, current_event)
                    
        generate_events(0, {})
        
        # 3. Event Probabilities
        event_probs = []
        for event in events:
            # P(E) = (clutter_density)^(num_clutter) * Product_{tracks j} [P_d * L(z_i, j) if hit else (1-P_d)]
            # num_clutter = num_dets - num_hits
            num_hits = sum(1 for d in event.values() if d != -1)
            num_clutter = num_dets - num_hits
            
            prob = self.clutter_density**num_clutter
            for j, i in event.items():
                if i == -1:
                    prob *= (1 - self.pd)
                else:
                    prob *= self.pd * likelihoods[i, j]
            event_probs.append(prob)
            
        total_prob = sum(event_probs) + 1e-100
        normalized_probs = [p / total_prob for p in event_probs]
        
        # 4. Marginalize
        # beta[track_j][target_i] where i=0 is miss, i=1..M are detections
        beta = np.zeros((num_tracks, num_dets + 1))
        for idx, event in enumerate(events):
            p = normalized_probs[idx]
            for j, i in event.items():
                if i == -1:
                    beta[j, 0] += p
                else:
                    beta[j, i + 1] += p
                    
        # Final normalization per track (sanity check)
        for j in range(num_tracks):
            row_sum = np.sum(beta[j, :])
            if row_sum > 0:
                beta[j, :] /= row_sum
            else:
                beta[j, 0] = 1.0 # default to miss if something went wrong
                
        return beta

class MultiTargetJPDATracker:
    def __init__(self, dt=0.1, config=None):
        self.dt = dt
        self.tracks = {} # id -> track_info dict
        self.next_id = 1
        self.jpda = JPDA()
        
        # Tuning parameters (matching MATLAB where possible)
        self.conf_threshold = 5 # 5 hits to confirm
        self.window_size = 8
        self.del_threshold = 5 # 5 misses to delete
        self.merge_threshold = 7.0 # Mahalanobis distance for merging
        
    def update(self, centroids):
        """
        centroids: Nx3 array [range, doppler, angle_deg]
        """
        if len(centroids) == 0:
            converted_centroids = []
        else:
            # Re-format to spatial: [u, r, rr]
            # u = pi * sin(deg2rad(angle_deg))
            # r = range
            # rr = doppler
            converted_centroids = []
            for c in centroids:
                u = np.pi * np.sin(np.deg2rad(c[2]))
                converted_centroids.append(np.array([u, c[0], c[1]]))

        # 1. Prediction for all tracks
        track_ids = list(self.tracks.keys())
        filters = [self.tracks[tid]['filter'] for tid in track_ids]
        for kf in filters:
            kf.predict()
            
        # 2. JPDA Association
        marginals = self.jpda.calculate_marginals(filters, converted_centroids)
        
        # 3. Soft Update
        for j, tid in enumerate(track_ids):
            self.tracks[tid]['filter'].update_soft(marginals[j], converted_centroids)
            
            # Update hit/miss statistics
            prob_hit = 1.0 - marginals[j, 0]
            self.tracks[tid]['association_history'].append(1 if prob_hit > 0.3 else 0)
            if len(self.tracks[tid]['association_history']) > self.window_size:
                self.tracks[tid]['association_history'].pop(0)
                
            if prob_hit < 0.3:
                self.tracks[tid]['consecutive_misses'] += 1
            else:
                self.tracks[tid]['consecutive_misses'] = 0
                
            self.tracks[tid]['age'] += 1
            
            # Confirmation
            if self.tracks[tid]['status'] == "tentative":
                if sum(self.tracks[tid]['association_history']) >= self.conf_threshold:
                    self.tracks[tid]['status'] = "confirmed"

        # 4. Deletion
        to_delete = [tid for tid, info in self.tracks.items() if info['consecutive_misses'] >= self.del_threshold]
        for tid in to_delete:
            del self.tracks[tid]
            
        # 5. Track Initiation
        # If a detection has low probability of belonging to any track, spawn new
        if len(converted_centroids) > 0:
            for i in range(len(converted_centroids)):
                # probability that det i is associated with any track
                prob_associated = 0
                if track_ids:
                    prob_associated = np.sum(marginals[:, i + 1])
                
                if prob_associated < 1e-3: # Not claimed?
                    self._initiate_track(converted_centroids[i])

        # 6. Merge tracks
        self._merge_tracks()
        
        return self.get_active_tracks()

    def _initiate_track(self, z):
        # Initial state from [u, r, rr]
        # x = r * sin(az) = r * (u/pi)
        # y = r * cos(az) = r * sqrt(1 - (u/pi)^2)
        u, r, rr = z
        sin_az = u / np.pi
        cos_az = np.sqrt(max(0, 1 - sin_az**2))
        
        px = r * sin_az
        py = r * cos_az
        vx = rr * sin_az
        vy = rr * cos_az
        
        state = [px, py, vx, vy]
        cov = np.diag([1.0, 1.0, 5.0, 5.0])
        Q = np.eye(4) * 0.1
        R = np.diag([0.01, 0.01, 0.01]) # TODO: Tune R based on radar specs
        
        new_track = {
            'filter': JPDAEKF(state, cov, Q, R, self.dt),
            'status': 'tentative',
            'age': 1,
            'consecutive_misses': 0,
            'association_history': [1]
        }
        self.tracks[self.next_id] = new_track
        self.next_id += 1

    def _merge_tracks(self):
        tids = list(self.tracks.keys())
        to_remove = set()
        
        for i in range(len(tids)):
            if tids[i] in to_remove: continue
            for j in range(i + 1, len(tids)):
                if tids[j] in to_remove: continue
                
                tid1, tid2 = tids[i], tids[j]
                f1, f2 = self.tracks[tid1]['filter'], self.tracks[tid2]['filter']
                
                # Mahalanobis distance between states
                diff = f1.x - f2.x
                P_avg = 0.5 * (f1.P + f2.P)
                try:
                    dist_sq = diff.T @ np.linalg.inv(P_avg) @ diff
                    if dist_sq < self.merge_threshold:
                        # Keep confirmed over tentative, or older over younger
                        if self.tracks[tid2]['status'] == 'confirmed' and self.tracks[tid1]['status'] == 'tentative':
                            to_remove.add(tid1)
                        else:
                            to_remove.add(tid2)
                except np.linalg.LinAlgError:
                    continue
                    
        for tid in to_remove:
            del self.tracks[tid]

    def get_active_tracks(self):
        return [
            {
                'id': tid,
                'state': info['filter'].x.tolist(),
                'status': info['status'],
                'age': info['age']
            }
            for tid, info in self.tracks.items() if info['status'] == 'confirmed'
        ]

if __name__ == "__main__":
    # Simple self-test
    tracker = MultiTargetJPDATracker()
    # Dummy centroids: range, doppler, angle_deg
    z1 = [5.0, 0.0, 10.0]
    tracks = tracker.update([z1])
    print(f"Frame 1 Tracks: {len(tracks)}")
    
    # Simulate a target moving at 1m/s
    for i in range(10):
        r = 5.0 + (i+1)*0.1
        tracks = tracker.update([[r, 1.0, 10.0]])
        print(f"Frame {i+2} Tracks: {len(tracks)}")
