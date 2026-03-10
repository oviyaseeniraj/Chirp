import numpy as np
import os
import sys
import glob
import pickle
import matplotlib.pyplot as plt

# Add parent directory to path to find jpda_tracking.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jpda_tracking import MultiTargetJPDATracker
from animate_centroids import CentroidAnimator, TrackerBase

class JPDATrackerAdapter(TrackerBase):
    """Bridge between MultiTargetJPDATracker and CentroidAnimator."""
    def __init__(self, dt=0.1):
        self.tracker = MultiTargetJPDATracker(dt=dt)

    def update(self, detections):
        """
        Processes list of detection dicts and returns tracks for animation.
        """
        # Convert detections from dict format to [[range, doppler, angle_deg], ...]
        raw_centroids = []
        for d in detections:
            # Handle both formats (Node raw dict and list)
            if isinstance(d, dict):
                raw_centroids.append([
                    d.get('range_idx', 0) * 0.04, # Simplified range_res
                    (d.get('doppler_idx', 32) - 32) * 0.1, # Simplified vel_res
                    d.get('angle_deg', 0)
                ])
            else:
                raw_centroids.append(d[:3])

        active_tracks = self.tracker.update(raw_centroids)
        
        # Format for CentroidAnimator
        formatted_tracks = []
        for t in active_tracks:
            state = t['state'] # [px, py, vx, vy]
            formatted_tracks.append({
                'id': t['id'],
                'pos': np.array([state[0], state[1]]),
                'vel': np.array([state[2], state[3]]),
                'is_outlier': False
            })
        return formatted_tracks

def run_real_data_test():
    """Finds latest capture file, runs JPDA, and generates GIF."""
    temp_dir = os.path.join(os.path.dirname(__file__), "temp")
    files = glob.glob(os.path.join(temp_dir, "capture_*.pkl"))
    
    if not files:
        print(f"No capture files found in {temp_dir}. Have you run trajectory.py?")
        return
        
    latest_file = max(files, key=os.path.getctime)
    print(f"Ingesting latest capture: {latest_file}")
    
    animator = CentroidAnimator(latest_file)
    tracker = JPDATrackerAdapter(dt=0.1)
    
    output_gif = os.path.join(temp_dir, "jpda_trajectory.gif")
    print(f"Generating JPDA animation: {output_gif}")
    animator.animate(output_gif, tracker=tracker)
    
    print("\nSUCCESS: Real data animation complete.")

def test_single_target():
    print("Running Single Target Test...")
    tracker = MultiTargetJPDATracker(dt=0.1)
    
    # Target starts at (0, 5) moving at (0, 1) m/s
    true_x, true_y = 0.0, 5.0
    vx, vy = 0.0, 1.0
    dt = 0.1
    
    tracked_states = []
    frames = 50
    
    for i in range(frames):
        # Update true position
        true_x += vx * dt
        true_y += vy * dt
        
        # Simulate measurement: [range, doppler, angle_deg]
        r = np.sqrt(true_x**2 + true_y**2)
        r += np.random.normal(0, 0.05)
        angle = np.rad2deg(np.arctan2(true_x, true_y))
        angle += np.random.normal(0, 1.0)
        rr = (true_x * vx + true_y * vy) / r
        rr += np.random.normal(0, 0.05)
        
        centroids = [[r, rr, angle]]
        active_tracks = tracker.update(centroids)
        
        if active_tracks:
            tracked_states.append(active_tracks[0]['state'])
            
    print(f"Total frames: {frames}, Target tracked in {len(tracked_states)} frames")
    return len(tracked_states) > 30

def test_two_crossing_targets():
    print("\nRunning Two Crossing Targets Test...")
    tracker = MultiTargetJPDATracker(dt=0.1)
    
    # T1: moves left to right, T2: moves right to left
    t1_x, t1_y = -3.0, 6.0
    t1_vx, t1_vy = 1.0, 0.0
    t2_x, t2_y = 3.0, 6.0
    t2_vx, t2_vy = -1.0, 0.0
    
    dt = 0.1
    frames = 70
    stats = []
    
    for i in range(frames):
        t1_x += t1_vx * dt
        t1_y += t1_vy * dt
        t2_x += t2_vx * dt
        t2_y += t2_vy * dt
        
        centroids = []
        for (x, y, vx, vy) in [(t1_x, t1_y, t1_vx, t1_vy), (t2_x, t2_y, t2_vx, t2_vy)]:
            r = np.sqrt(x**2 + y**2)
            angle = np.rad2deg(np.arctan2(x, y))
            rr = (x * vx + y * vy) / r
            centroids.append([r, rr, angle])
            
        tracks = tracker.update(centroids)
        stats.append(len(tracks))
        
    print(f"Average tracks active: {np.mean(stats):.2f}")
    return np.all(np.array(stats[20:]) >= 1)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true", help="Run on real data from temp/")
    args = parser.parse_args()
    
    if args.real:
        run_real_data_test()
    else:
        s1 = test_single_target()
        s2 = test_two_crossing_targets()
        if s1 and s2:
            print("\nALL JPDA TESTS PASSED.")
        else:
            print("\nSOME TESTS FAILED.")
