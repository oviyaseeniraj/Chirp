#!/usr/bin/env python3
"""
Minimal script to run calibration on C++ radar data.
Called directly from implementation.cpp after data collection.

Usage: python3 calibrate.py <data_directory>
Example: python3 calibrate.py /home/fusionsense/repos/AVR/RadarPipeline/test/non_thread/frame_data
"""

import sys
import os
import json
import glob
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Non-interactive for Jetson
import matplotlib.pyplot as plt

def load_cpp_data(data_dir):
    """Load and organize JSON files from C++ output"""
    json_files = glob.glob(os.path.join(data_dir, "*.json"))
    
    if not json_files:
        raise ValueError(f"No JSON files found in {data_dir}")
    
    # Group by node name
    node_data = {}
    for jfile in json_files:
        with open(jfile) as f:
            data = json.load(f)
            node = data['Node']
            if node not in node_data:
                node_data[node] = []
            
            # Convert angle/range to x,y coordinates
            angle_rad = np.deg2rad(data['Angle'])
            range_m = data['Range']
            x = range_m * np.sin(angle_rad)
            y = range_m * np.cos(angle_rad)
            
            node_data[node].append(complex(x, y))
    
    # Convert to array
    num_radars = len(node_data)
    num_frames = min(len(frames) for frames in node_data.values())
    
    trajectory = np.zeros((num_radars, num_frames), dtype=complex)
    for i, (node, frames) in enumerate(sorted(node_data.items())):
        trajectory[i, :] = frames[:num_frames]
    
    print(f"Loaded {num_radars} radars, {num_frames} frames each")
    return trajectory, list(sorted(node_data.keys()))

def calibrate(trajectory):
    """Run closed-form calibration algorithm"""
    num_radars, num_frames = trajectory.shape
    
    P_opt = np.zeros((num_radars, num_radars), dtype=complex)
    theta_opt = np.zeros((num_radars, num_radars))
    
    for i in range(num_radars):
        for k in range(num_radars):
            z_i = trajectory[i, :]
            z_k = trajectory[k, :]
            z_i_mean = np.mean(z_i)
            z_k_mean = np.mean(z_k)
            
            val = np.sum((z_k - z_k_mean) * np.conj(z_i - z_i_mean))
            phi = np.arctan2(val.imag, val.real)
            
            theta_opt[i, k] = np.rad2deg(-phi)
            P_opt[i, k] = z_i_mean - np.exp(-1j * phi) * z_k_mean
    
    # Average across all pairs
    P_avg = np.zeros((num_radars, num_radars), dtype=complex)
    theta_avg = np.zeros((num_radars, num_radars))
    
    for ref in range(num_radars):
        for i in range(num_radars):
            for k in range(num_radars):
                P_avg[ref, i] += (P_opt[k, i] * np.exp(1j * np.deg2rad(theta_opt[ref, k])) + P_opt[ref, k])
                theta_avg[ref, i] += theta_opt[k, i] + theta_opt[ref, k]
            P_avg[ref, i] /= num_radars
            theta_avg[ref, i] /= num_radars
    
    return P_avg, theta_avg

def visualize(trajectory, P_opt, theta_opt, nodes, output_dir):
    """Create visualization plots"""
    num_radars = trajectory.shape[0]
    
    for ref in range(num_radars):
        plt.figure(figsize=(10, 8))
        
        # Plot trajectory
        plt.plot(trajectory[ref, :].real, trajectory[ref, :].imag, 
                'b-', alpha=0.3, label=f'{nodes[ref]} Trajectory')
        
        # Plot radar positions
        plt.scatter(P_opt[ref, :].real, P_opt[ref, :].imag, 
                   s=200, c='red', marker='X', zorder=10)
        
        # Plot orientations
        for i in range(num_radars):
            angle_rad = np.deg2rad(theta_opt[ref, i])
            dx = 5 * np.cos(angle_rad)
            dy = 5 * np.sin(angle_rad)
            plt.arrow(P_opt[ref, i].real, P_opt[ref, i].imag,
                     dx, dy, head_width=2, color='black', zorder=5)
            plt.text(P_opt[ref, i].real, P_opt[ref, i].imag + 3, 
                    nodes[i], ha='center', fontsize=10)
        
        plt.grid(True)
        plt.gca().set_aspect('equal', adjustable='box')
        plt.xlabel('X (meters)')
        plt.ylabel('Y (meters)')
        plt.title(f'Calibration Results - {nodes[ref]} Reference Frame')
        plt.legend()
        
        filename = os.path.join(output_dir, f'calibration_{nodes[ref]}.png')
        plt.savefig(filename, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"Saved: {filename}")

def save_results(P_opt, theta_opt, nodes, output_dir):
    """Save calibration results to text file"""
    filename = os.path.join(output_dir, 'calibration_results.txt')
    
    with open(filename, 'w') as f:
        f.write("="*60 + "\n")
        f.write("RADAR CALIBRATION RESULTS\n")
        f.write("="*60 + "\n\n")
        
        for i, ref_node in enumerate(nodes):
            f.write(f"{ref_node} as Reference:\n")
            f.write("-"*50 + "\n")
            for k, node in enumerate(nodes):
                if i != k:
                    f.write(f"  {node}: Position=({P_opt[i,k].real:.2f}, {P_opt[i,k].imag:.2f})m, "
                           f"Orientation={theta_opt[i,k]:.1f}°\n")
            f.write("\n")
    
    print(f"Results saved: {filename}")

def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    
    data_dir = sys.argv[1]
    
    if not os.path.exists(data_dir):
        print(f"Error: Directory not found: {data_dir}")
        sys.exit(1)
    
    # Create output directory
    output_dir = os.path.join(data_dir, 'calibration_output')
    os.makedirs(output_dir, exist_ok=True)
    
    print("="*60)
    print("RADAR CALIBRATION")
    print("="*60)
    print(f"Data directory: {data_dir}")
    print(f"Output directory: {output_dir}\n")
    
    # Load data
    print("Loading data...")
    trajectory, nodes = load_cpp_data(data_dir)
    
    # Run calibration
    print("Running calibration algorithm...")
    P_opt, theta_opt = calibrate(trajectory)
    
    # Save results
    print("Saving results...")
    save_results(P_opt, theta_opt, nodes, output_dir)
    
    # Visualize
    print("Creating plots...")
    visualize(trajectory, P_opt, theta_opt, nodes, output_dir)
    
    print("\n" + "="*60)
    print("CALIBRATION COMPLETE")
    print("="*60)
    print(f"Results: {output_dir}/")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

