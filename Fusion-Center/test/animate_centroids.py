#!/usr/bin/env python3
"""
animate_centroids.py

Plays back radar centroid data from a .pkl file as an animated GIF.

The animator is decoupled from any specific filter. Pass any tracker that
implements the TrackerBase interface to CentroidAnimator.animate().
"""

import os
import pickle
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import sys
import glob
from abc import ABC, abstractmethod

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from Node.src.radar import config
except ImportError:
    class MockConfig:
        RANGE_RES = 0.04
        VELOCITY_RES = 0.1
        SLOW_TIME = 64
    config = MockConfig()


# ---------------------------------------------------------------------------
# Tracker Interface
# ---------------------------------------------------------------------------

class TrackerBase(ABC):
    """
    Interface for all radar trackers used with the animator.

    Each call to `update` receives the raw matched detection and returns
    the (possibly smoothed) position and velocity, plus an outlier flag.
    """

    @abstractmethod
    def update(self, detections: list):
        """
        Args:
            detections: List of detection dicts (e.g. from Node output).

        Returns:
            tracks: List of track dicts, each with 'pos' [x, y] and 'vel' [vx, vy].
        """
        ...


# ---------------------------------------------------------------------------
# Example tracker: pass-through (no filtering)
# ---------------------------------------------------------------------------

    def _polar_to_cartesian(self, range_idx, angle_rad):
        r = range_idx * config.RANGE_RES
        return r * np.sin(angle_rad), r * np.cos(angle_rad)

    def update(self, detections):
        if not detections:
            return []
        
        # Passthrough just picks the first one for backward compatibility or simplistic visualization
        c = detections[0]
        # Support both 'range_idx'/'angle_rad' (Node format) and [range, doppler, angle_deg] (JPDA format)
        if isinstance(c, dict):
            px, py = self._polar_to_cartesian(c.get('range_idx', 0), c.get('angle_rad', 0))
            v_rad = (c.get('doppler_idx', 32) - 32) * 0.1 # simplified
            vx = v_rad * np.sin(c.get('angle_rad', 0))
            vy = v_rad * np.cos(c.get('angle_rad', 0))
        else:
            r, rr, angle = c[0], c[1], c[2]
            px, py = r * np.sin(np.deg2rad(angle)), r * np.cos(np.deg2rad(angle))
            vx, vy = rr * np.sin(np.deg2rad(angle)), rr * np.cos(np.deg2rad(angle))

        return [{'pos': np.array([px, py]), 'vel': np.array([vx, vy]), 'is_outlier': False, 'id': 1}]


# ---------------------------------------------------------------------------
# Animator
# ---------------------------------------------------------------------------

class CentroidAnimator:
    def __init__(self, input_file):
        with open(input_file, 'rb') as f:
            self.node_data = pickle.load(f)

        self.node_id = list(self.node_data.keys())[0]
        self.frames = self.node_data[self.node_id]
        self.last_xy = None

        print(f"Loaded {len(self.frames)} frames from node '{self.node_id}'")

    def _polar_to_cartesian(self, range_idx, angle_rad):
        r = range_idx * config.RANGE_RES
        return r * np.sin(angle_rad), r * np.cos(angle_rad)

    def _pick_detection(self, detections):
        """Convert detections to Cartesian and associate to the current track."""
        candidates = []
        for c in detections:
            px, py = self._polar_to_cartesian(c['range_idx'], c['angle_rad'])
            v_rad = (c['doppler_idx'] - getattr(config, 'SLOW_TIME', 64) // 2) * getattr(config, 'VELOCITY_RES', 0.1)
            vx = v_rad * np.sin(c['angle_rad'])
            vy = v_rad * np.cos(c['angle_rad'])
            candidates.append((np.array([px, py]), np.array([vx, vy])))

        if self.last_xy is None:
            return candidates[0]

        dists = [np.linalg.norm(c[0] - self.last_xy) for c in candidates]
        return candidates[np.argmin(dists)]

    def animate(self, output_file, tracker: TrackerBase = None):
        """
        Render the animation to a GIF.

        Args:
            output_file: Path to write the output GIF.
            tracker: Any object implementing TrackerBase. Defaults to
                     PassthroughTracker (no filtering).
        """
        if tracker is None:
            tracker = PassthroughTracker()

        fig, ax = plt.subplots(figsize=(8, 8))
        ax.set_xlim(-5, 5)
        ax.set_ylim(0, 10)
        ax.set_aspect('equal')
        ax.grid(True, alpha=0.4)
        ax.set_xlabel("Lateral (m)")
        ax.set_ylabel("Range (m)")
        tracker_name = type(tracker).__name__
        ax.set_title(f"{tracker_name} — {self.node_id}")

        # Blue = inlier, Red = outlier (bwr colormap, values 0.0 / 1.0)
        scatter = ax.scatter([], [], c=[], s=80, edgecolors='black',
                            linewidths=0.5, cmap='bwr', vmin=0, vmax=1, zorder=5)
        trail_pts, = ax.plot([], [], 'o', color='lightblue', markersize=2, alpha=0.3, zorder=3)
        # Status text
        frame_text = ax.text(0.02, 0.95, '', transform=ax.transAxes, fontsize=12,
                            fontweight='bold', bbox=dict(facecolor='white', alpha=0.5))

        self._track_artists = {} # id -> {'scatter': ..., 'quiver': ..., 'trail': ...}
        self._history = {} # id -> {'x': [], 'y': []}

        def update(frame_idx):
            if frame_idx >= len(self.frames):
                return

            detections = self.frames[frame_idx].get('clusters', [])
            
            # Update tracks
            tracks = tracker.update(detections)
            
            # Basic track cleanup (remove artists for tracks that disappeared)
            active_ids = {t['id'] for t in tracks}
            for tid in list(self._track_artists.keys()):
                if tid not in active_ids:
                    self._track_artists[tid]['scatter'].remove()
                    self._track_artists[tid]['quiver'].remove()
                    self._track_artists[tid]['trail'].remove()
                    del self._track_artists[tid]

            for t in tracks:
                tid = t['id']
                pos = t['pos']
                vel = t['vel']
                is_outlier = t.get('is_outlier', False)

                if tid not in self._track_artists:
                    # Create new artists for this track
                    sc = ax.scatter([], [], s=80, edgecolors='black', linewidths=0.5, 
                                   cmap='bwr', vmin=0, vmax=1, zorder=5)
                    tr, = ax.plot([], [], 'o', markersize=2, alpha=0.3, zorder=3)
                    # Quiver is tricky, we'll store its parameters and update
                    self._track_artists[tid] = {
                        'scatter': sc,
                        'trail': tr,
                        'quiver': None,
                        'color': plt.cm.tab10(tid % 10)
                    }
                    self._history[tid] = {'x': [], 'y': []}
                    tr.set_color(self._track_artists[tid]['color'])

                artists = self._track_artists[tid]
                artists['scatter'].set_offsets(pos.reshape(1, 2))
                artists['scatter'].set_array(np.array([1.0 if is_outlier else 0.0]))
                
                if artists['quiver'] is not None:
                    artists['quiver'].remove()
                
                artists['quiver'] = ax.quiver(
                    pos[0], pos[1], vel[0], vel[1],
                    color=artists['color'], alpha=0.8, scale=0.5, scale_units='xy',
                    width=0.01, headwidth=4, headlength=4, zorder=6
                )

                self._history[tid]['x'].append(pos[0])
                self._history[tid]['y'].append(pos[1])
                if len(self._history[tid]['x']) > 50:
                    self._history[tid]['x'].pop(0)
                    self._history[tid]['y'].pop(0)
                artists['trail'].set_data(self._history[tid]['x'], self._history[tid]['y'])

            frame_text.set_text(f'Frame: {frame_idx}/{len(self.frames)} - Tracks: {len(tracks)}')

        anim = FuncAnimation(fig, update, frames=len(self.frames), interval=100, blit=False)
        print(f"Saving to {output_file}...")
        anim.save(output_file, writer='pillow', fps=10)
        plt.close()
        print("Done.")


# ---------------------------------------------------------------------------
# Entry point — swap tracker here
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    temp_dir = os.path.join(os.path.dirname(__file__), "temp")
    files = glob.glob(os.path.join(temp_dir, "*.pkl"))
    if not files:
        print("No .pkl files found in temp/")
        sys.exit(1)

    latest_file = max(files, key=os.path.getctime)
    animator = CentroidAnimator(latest_file)

    # --- Swap your tracker here ---
    # from naive_filtering import NaiveFilter          # example
    # from EKF import EKFTracker                       # example
    tracker = PassthroughTracker()
    # tracker = NaiveFilter(alpha=0.1, pos_threshold=1.2, vel_threshold=3.0)

    output_gif = os.path.join(temp_dir, "trajectory_animation.gif")
    animator.animate(output_gif, tracker=tracker)
