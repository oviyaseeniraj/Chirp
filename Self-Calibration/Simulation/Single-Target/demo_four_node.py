"""
Demo script showing how to use the four_node_calibration module programmatically
"""

import numpy as np
import matplotlib.pyplot as plt
import os
from datetime import datetime
from four_node_calibration import FourNodeRadarCalibration, compare_configurations

def demo_single_configuration():
    """Demo 1: Run single configuration analysis"""
    print("\n" + "="*70)
    print("DEMO 1: Single Configuration Analysis")
    print("="*70)
    
    # Create calibrator with square configuration
    calibrator = FourNodeRadarCalibration(config='square')
    
    # Run full analysis with custom noise parameters
    results = calibrator.run_full_analysis(
        noise_std=0.5,              # Trajectory noise standard deviation
        measurement_noise_std=0.5,   # Measurement noise standard deviation
        random_seed=42               # Fixed seed for reproducibility
    )
    
    # Access results
    print("\nResults Summary:")
    print(f"Position errors shape: {results['position_errors'].shape}")
    print(f"Orientation errors shape: {results['orientation_errors'].shape}")
    
    # Calculate overall statistics
    pos_errors = results['position_errors']
    orient_errors = results['orientation_errors']
    
    # Get non-diagonal elements (actual errors, not self-comparisons)
    non_diag_pos = pos_errors[np.eye(4) == 0]
    non_diag_orient = orient_errors[np.eye(4) == 0]
    
    print(f"\nOverall Performance:")
    print(f"  Avg Position Error: {np.mean(non_diag_pos):.3f} m")
    print(f"  Avg Orientation Error: {np.mean(non_diag_orient):.3f}°")
    
    return results


def demo_different_configurations():
    """Demo 2: Try different network configurations"""
    print("\n" + "="*70)
    print("DEMO 2: Testing Different Configurations")
    print("="*70)
    
    configs = ['square', 'linear', 'L-shape', 'diamond']
    results = {}
    
    for config in configs:
        print(f"\nTesting {config} configuration...")
        calibrator = FourNodeRadarCalibration(config=config)
        results[config] = calibrator.run_full_analysis(
            noise_std=0.5,
            measurement_noise_std=0.5,
            random_seed=42
        )
    
    # Compare performance
    print("\n" + "="*70)
    print("Performance Comparison:")
    print("="*70)
    print(f"{'Configuration':<15} {'Avg Pos Error (m)':<20} {'Avg Orient Error (°)':<20}")
    print("-"*70)
    
    for config in configs:
        pos_errors = results[config]['position_errors']
        orient_errors = results[config]['orientation_errors']
        
        non_diag_pos = pos_errors[np.eye(4) == 0]
        non_diag_orient = orient_errors[np.eye(4) == 0]
        
        print(f"{config.capitalize():<15} {np.mean(non_diag_pos):<20.3f} {np.mean(non_diag_orient):<20.3f}")
    
    return results


def demo_noise_sensitivity():
    """Demo 3: Test sensitivity to noise levels"""
    # Create demo output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    demo_dir = os.path.join("output", f"demo_noise_sensitivity_{timestamp}")
    os.makedirs(demo_dir, exist_ok=True)
    
    print("\n" + "="*70)
    print("DEMO 3: Noise Sensitivity Analysis")
    print(f"Output Directory: {demo_dir}")
    print("="*70)
    
    noise_levels = [0.1, 0.5, 1.0, 2.0]
    results = []
    
    calibrator = FourNodeRadarCalibration(config='square')
    
    for noise_std in noise_levels:
        print(f"\nTesting with noise std = {noise_std}...")
        
        # Run analysis
        result = calibrator.run_full_analysis(
            noise_std=noise_std,
            measurement_noise_std=noise_std,
            random_seed=42
        )
        
        pos_errors = result['position_errors']
        orient_errors = result['orientation_errors']
        
        non_diag_pos = pos_errors[np.eye(4) == 0]
        non_diag_orient = orient_errors[np.eye(4) == 0]
        
        results.append({
            'noise_std': noise_std,
            'mean_pos_error': np.mean(non_diag_pos),
            'mean_orient_error': np.mean(non_diag_orient),
            'std_pos_error': np.std(non_diag_pos),
            'std_orient_error': np.std(non_diag_orient)
        })
    
    # Plot noise sensitivity
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    
    noise_vals = [r['noise_std'] for r in results]
    pos_means = [r['mean_pos_error'] for r in results]
    pos_stds = [r['std_pos_error'] for r in results]
    orient_means = [r['mean_orient_error'] for r in results]
    orient_stds = [r['std_orient_error'] for r in results]
    
    ax1.errorbar(noise_vals, pos_means, yerr=pos_stds, marker='o', 
                 linewidth=2, markersize=8, capsize=5, label='Position Error')
    ax1.set_xlabel('Noise Standard Deviation', fontsize=11)
    ax1.set_ylabel('Mean Position Error (m)', fontsize=11)
    ax1.set_title('Position Error vs Noise Level', fontsize=12, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.legend()
    
    ax2.errorbar(noise_vals, orient_means, yerr=orient_stds, marker='s', 
                 linewidth=2, markersize=8, capsize=5, color='coral', 
                 label='Orientation Error')
    ax2.set_xlabel('Noise Standard Deviation', fontsize=11)
    ax2.set_ylabel('Mean Orientation Error (degrees)', fontsize=11)
    ax2.set_title('Orientation Error vs Noise Level', fontsize=12, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    ax2.legend()
    
    plt.tight_layout()
    
    # Save plot
    filename = "noise_sensitivity_analysis.png"
    plt.savefig(os.path.join(demo_dir, filename), dpi=300, bbox_inches='tight')
    print(f"\nSaved: {filename}")
    
    # Print summary
    print("\n" + "="*70)
    print("Noise Sensitivity Summary:")
    print("="*70)
    print(f"{'Noise Std':<12} {'Pos Error (m)':<20} {'Orient Error (°)':<20}")
    print("-"*70)
    for r in results:
        print(f"{r['noise_std']:<12.1f} {r['mean_pos_error']:.3f} ± {r['std_pos_error']:.3f}     "
              f"{r['mean_orient_error']:.3f} ± {r['std_orient_error']:.3f}")
    
    return results


def demo_trajectory_length():
    """Demo 4: Effect of trajectory length on accuracy"""
    # Create demo output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    demo_dir = os.path.join("output", f"demo_trajectory_length_{timestamp}")
    os.makedirs(demo_dir, exist_ok=True)
    
    print("\n" + "="*70)
    print("DEMO 4: Trajectory Length Analysis")
    print(f"Output Directory: {demo_dir}")
    print("="*70)
    
    trajectory_lengths = [50, 100, 200, 500]
    results = []
    
    for num_iter in trajectory_lengths:
        print(f"\nTesting with {num_iter} time steps...")
        
        calibrator = FourNodeRadarCalibration(config='square')
        calibrator.num_iterations = num_iter
        
        result = calibrator.run_full_analysis(
            noise_std=0.5,
            measurement_noise_std=0.5,
            random_seed=42
        )
        
        pos_errors = result['position_errors']
        orient_errors = result['orientation_errors']
        
        non_diag_pos = pos_errors[np.eye(4) == 0]
        non_diag_orient = orient_errors[np.eye(4) == 0]
        
        results.append({
            'num_iterations': num_iter,
            'mean_pos_error': np.mean(non_diag_pos),
            'mean_orient_error': np.mean(non_diag_orient)
        })
    
    # Plot results
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    
    iters = [r['num_iterations'] for r in results]
    pos_errs = [r['mean_pos_error'] for r in results]
    orient_errs = [r['mean_orient_error'] for r in results]
    
    ax1.plot(iters, pos_errs, marker='o', linewidth=2, markersize=10, color='steelblue')
    ax1.set_xlabel('Number of Time Steps', fontsize=11)
    ax1.set_ylabel('Mean Position Error (m)', fontsize=11)
    ax1.set_title('Position Error vs Trajectory Length', fontsize=12, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    
    ax2.plot(iters, orient_errs, marker='s', linewidth=2, markersize=10, color='coral')
    ax2.set_xlabel('Number of Time Steps', fontsize=11)
    ax2.set_ylabel('Mean Orientation Error (degrees)', fontsize=11)
    ax2.set_title('Orientation Error vs Trajectory Length', fontsize=12, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # Save plot
    filename = "trajectory_length_analysis.png"
    plt.savefig(os.path.join(demo_dir, filename), dpi=300, bbox_inches='tight')
    print(f"\nSaved: {filename}")
    
    # Print summary
    print("\n" + "="*70)
    print("Trajectory Length Summary:")
    print("="*70)
    print(f"{'Time Steps':<15} {'Pos Error (m)':<20} {'Orient Error (°)':<20}")
    print("-"*70)
    for r in results:
        print(f"{r['num_iterations']:<15} {r['mean_pos_error']:<20.3f} {r['mean_orient_error']:<20.3f}")
    
    return results


def main():
    """Run all demos"""
    print("\n" + "="*70)
    print("FOUR-NODE RADAR CALIBRATION - INTERACTIVE DEMOS")
    print("="*70)
    print("\nAvailable Demos:")
    print("1. Single Configuration Analysis")
    print("2. Different Configurations Comparison")
    print("3. Noise Sensitivity Analysis")
    print("4. Trajectory Length Analysis")
    print("5. Run All Demos")
    print("6. Full Configuration Comparison (from module)")
    
    choice = input("\nSelect demo (1-6) [default: 1]: ").strip() or "1"
    
    if choice == "1":
        demo_single_configuration()
        plt.show()
    
    elif choice == "2":
        demo_different_configurations()
        plt.show()
    
    elif choice == "3":
        demo_noise_sensitivity()
        plt.show()
    
    elif choice == "4":
        demo_trajectory_length()
        plt.show()
    
    elif choice == "5":
        print("\nRunning all demos...")
        demo_single_configuration()
        demo_different_configurations()
        demo_noise_sensitivity()
        demo_trajectory_length()
        plt.show()
    
    elif choice == "6":
        compare_configurations()
    
    else:
        print("Invalid choice. Running demo 1.")
        demo_single_configuration()
        plt.show()


if __name__ == "__main__":
    main()

