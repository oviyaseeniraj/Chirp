import numpy as np
from scipy.optimize import linear_sum_assignment
import time

class EKFTracker:
    """
    Extended Kalman Filter for 2D Constant Velocity Model.
    State: [px, py, vx, vy]
    Measurement: [px, py, v_doppler]
    """
    def __init__(self, track_id, initial_pos, dt=0.1):
        self.track_id = track_id
        self.dt = dt
        
        # State: [x, y, vx, vy]
        self.x = np.array([initial_pos[0], initial_pos[1], 0, 0], dtype=np.float32)
        
        # State covariance
        self.P = np.diag([1.0, 1.0, 5.0, 5.0]).astype(np.float32)
        
        # Process noise
        q = 0.1
        self.Q = np.diag([q, q, q*2, q*2]).astype(np.float32)
        
        # Measurement noise [x, y, v_doppler]
        self.R = np.diag([0.1, 0.1, 0.5]).astype(np.float32)
        
        self.age = 0
        self.hits = 1
        self.misses = 0

    def predict(self):
        dt = self.dt
        # Transition matrix F
        F = np.array([
            [1, 0, dt, 0],
            [0, 1, 0, dt],
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ], dtype=np.float32)
        
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + self.Q
        self.age += 1
        return self.x

    def update(self, z):
        """
        EKF Update Step
        z: [px, py, v_doppler]
        """
        px, py, vx, vy = self.x
        
        # 1. Measurement Function h(x)
        r = np.sqrt(px**2 + py**2) + 1e-6
        v_doppler_pred = (px * vx + py * vy) / r
        z_pred = np.array([px, py, v_doppler_pred], dtype=np.float32)
        
        # 2. Jacobian H
        # dh/dpx, dh/dpy, dh/dvx, dh/dvy
        # For px, py: H[:2, :2] = Identity
        # For v_doppler:
        # dv_d/dpx = (vx*r - (px*vx+py*vy)*(px/r)) / r^2
        # dv_d/dvx = px/r
        H = np.zeros((3, 4), dtype=np.float32)
        H[0, 0] = 1
        H[1, 1] = 1
        
        # Velocity derivatives
        H[2, 0] = (vx * r - (px * vx + py * vy) * (px / r)) / (r**2)
        H[2, 1] = (vy * r - (px * vx + py * vy) * (py / r)) / (r**2)
        H[2, 2] = px / r
        H[2, 3] = py / r
        
        # 3. Kalman Gain
        S = H @ self.P @ H.T + self.R
        K = self.P @ H.T @ np.linalg.inv(S)
        
        # 4. Update
        y = z - z_pred
        self.x = self.x + K @ y
        self.P = (np.eye(4) - K @ H) @ self.P
        
        self.hits += 1
        self.misses = 0

class MultiTargetTracker:
    def __init__(self, dt=0.1, max_misses=5, min_hits=3, dist_threshold=2.0):
        self.tracks = []
        self.next_id = 1
        self.dt = dt
        self.max_misses = max_misses
        self.min_hits = min_hits
        self.dist_threshold = dist_threshold

    def update(self, detections):
        """
        detections: list of [px, py, v_doppler]
        """
        # 1. Predict
        for track in self.tracks:
            track.predict()
            
        if len(detections) == 0:
            for track in self.tracks:
                track.misses += 1
            self.tracks = [t for t in self.tracks if t.misses <= self.max_misses]
            return self.get_active_tracks()

        # 2. Association (Hungarian Algorithm)
        if len(self.tracks) > 0:
            cost_matrix = np.zeros((len(self.tracks), len(detections)))
            for i, track in enumerate(self.tracks):
                for j, det in enumerate(detections):
                    # distance between track prediction and detection
                    dist = np.linalg.norm(track.x[:2] - det[:2])
                    cost_matrix[i, j] = dist
            
            row_ind, col_ind = linear_sum_assignment(cost_matrix)
            
            used_tracks = set()
            used_detections = set()
            
            for r, c in zip(row_ind, col_ind):
                if cost_matrix[r, c] < self.dist_threshold:
                    self.tracks[r].update(detections[c])
                    used_tracks.add(r)
                    used_detections.add(c)
            
            # Unmatched tracks
            for i in range(len(self.tracks)):
                if i not in used_tracks:
                    self.tracks[i].misses += 1
            
            # Unmatched detections (new tracks)
            for j in range(len(detections)):
                if j not in used_detections:
                    new_track = EKFTracker(self.next_id, detections[j][:2], self.dt)
                    # Initialize with the detection Doppler if available
                    new_track.x[2] = detections[j][2] * (detections[j][0] / (np.linalg.norm(detections[j][:2]) + 1e-6))
                    new_track.x[3] = detections[j][2] * (detections[j][1] / (np.linalg.norm(detections[j][:2]) + 1e-6))
                    self.tracks.append(new_track)
                    self.next_id += 1
        else:
            # All detections are new tracks
            for det in detections:
                new_track = EKFTracker(self.next_id, det[:2], self.dt)
                self.tracks.append(new_track)
                self.next_id += 1

        # 3. Clean up
        self.tracks = [t for t in self.tracks if t.misses <= self.max_misses]
        return self.get_active_tracks()

    def get_active_tracks(self):
        """Only return tracks that have enough hits to be considered stable"""
        return [
            {
                "id": t.track_id,
                "x": float(t.x[0]),
                "y": float(t.x[1]),
                "vx": float(t.x[2]),
                "vy": float(t.x[3]),
                "velocity": float(np.sqrt(t.x[2]**2 + t.x[3]**2)),
                "hits": t.hits,
                "misses": t.misses
            }
            for t in self.tracks if t.hits >= self.min_hits
        ]
