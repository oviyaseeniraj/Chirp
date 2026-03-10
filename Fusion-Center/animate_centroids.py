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
    def update(self, pos: np.ndarray, vel: np.ndarray):
        """
        Args:
            pos: Raw Cartesian position [x, y] in metres.
            vel: Raw Cartesian velocity [vx, vy] in m/s.

        Returns:
            s_pos (np.ndarray): Smoothed/filtered position [x, y].
            s_vel (np.ndarray): Smoothed/filtered velocity [vx, vy].
            is_outlier (bool): True if the raw point was flagged as an outlier.
        """
        ...


# ---------------------------------------------------------------------------
# Example tracker: pass-through (no filtering)
# ---------------------------------------------------------------------------

class PassthroughTracker(TrackerBase):
    """Returns raw detections unchanged. Useful as a baseline."""

    def update(self, pos, vel):
        return pos.copy(), vel.copy(), False


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
        frame_text = ax.text(0.02, 0.95, '', transform=ax.transAxes, fontsize=12,
                            fontweight='bold', bbox=dict(facecolor='white', alpha=0.5))

        history_x, history_y = [], []
        self._quiver = None  # current arrow artist

        def update(frame_idx):
            nonlocal history_x, history_y

            # Remove previous arrow
            if self._quiver is not None:
                self._quiver.remove()
                self._quiver = None

            if frame_idx >= len(self.frames):
                return

            detections = self.frames[frame_idx].get('clusters', [])

            if not detections:
                scatter.set_offsets(np.empty((0, 2)))
                frame_text.set_text(f'Frame: {frame_idx}/{len(self.frames)} [EMPTY]')
                return

            raw_pos, raw_vel = self._pick_detection(detections)
            s_pos, s_vel, is_outlier = tracker.update(raw_pos, raw_vel)
            self.last_xy = s_pos

            scatter.set_offsets(s_pos.reshape(1, 2))
            scatter.set_array(np.array([1.0 if is_outlier else 0.0]))

            # Quiver must be recreated each frame — blit=False + remove() is the
            # standard workaround for Matplotlib Quiver in animations.
            self._quiver = ax.quiver(
                s_pos[0], s_pos[1], s_vel[0], s_vel[1],
                color='orange', alpha=0.95, scale=0.5, scale_units='xy',
                width=0.012, headwidth=4, headlength=4, zorder=6
            )

            history_x.append(s_pos[0])
            history_y.append(s_pos[1])
            if len(history_x) > 200:
                history_x = history_x[-200:]
                history_y = history_y[-200:]
            trail_pts.set_data(history_x, history_y)

            status = " [OUTLIER]" if is_outlier else ""
            frame_text.set_text(f'Frame: {frame_idx}/{len(self.frames)}{status}')

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
