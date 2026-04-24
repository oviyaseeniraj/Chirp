import numpy as np
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
import os
from datetime import datetime

class FourNodeRadarCalibration:
    """Advanced 4-node radar calibration with multiple analysis features"""
    
    def __init__(self, config='square'):
        """
        Initialize 4-node radar network
        
        Args:
            config: Network configuration ('square', 'linear', 'L-shape', 'diamond')
        """
        self.num_radars = 4
        self.num_iterations = 100
        self.config = config
        self.output_dir = None
        self.setup_configuration(config)
    
    def create_output_directory(self):
        """Create output directory for this configuration"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = os.path.join("output", f"{self.config}_config_{timestamp}")
        os.makedirs(self.output_dir, exist_ok=True)
        return self.output_dir
    
    def setup_configuration(self, config):
        """Setup different 4-radar configurations"""
        if config == 'square':
            # Square configuration
            self.radar_position_array = np.array([
                [0, 40, 40, 0],
                [-20, -20, 20, 20]
            ])
            self.radar_orientation_array = np.array([45, 135, 225, 315])
            self.initial_target_position = 20 + 1j*40
            
        elif config == 'linear':
            # Linear configuration
            self.radar_position_array = np.array([
                [0, 20, 40, 60],
                [0, 0, 0, 0]
            ])
            self.radar_orientation_array = np.array([90, 90, 90, 90])
            self.initial_target_position = 30 + 1j*30
            
        elif config == 'L-shape':
            # L-shaped configuration
            self.radar_position_array = np.array([
                [0, 30, 60, 60],
                [0, 0, 0, 30]
            ])
            self.radar_orientation_array = np.array([45, 90, 135, 225])
            self.initial_target_position = 30 + 1j*30
            
        elif config == 'diamond':
            # Diamond configuration
            self.radar_position_array = np.array([
                [30, 60, 30, 0],
                [0, 30, 60, 30]
            ])
            self.radar_orientation_array = np.array([0, 90, 180, 270])
            self.initial_target_position = 30 + 1j*30
        
        self.complex_radar_position_array = (
            self.radar_position_array[0, :] + 1j * self.radar_position_array[1, :]
        )
    
    def generate_trajectory(self, vel_x_max=0, vel_y_max=-1, noise_std=0.5):
        """Generate synthetic target trajectory with configurable noise"""
        new_target_position = self.initial_target_position
        complex_trajectory_array = np.zeros(self.num_iterations, dtype=complex)
        
        for t in range(self.num_iterations):
            delta_x = 2 * np.random.rand()
            delta_y = 2 * np.random.rand()
            complex_axial_velocity = complex(delta_x * vel_x_max, delta_y * vel_y_max)
            complex_new_position = new_target_position + complex_axial_velocity
            
            noise = complex(noise_std * np.random.randn(), noise_std * np.random.randn())
            complex_new_position += noise
            
            complex_trajectory_array[t] = complex_new_position
            new_target_position = complex_new_position
        
        return complex_trajectory_array
    
    def generate_radar_observations(self, complex_trajectory_array, measurement_noise_std=0.5):
        """Generate radar observations with measurement noise"""
        complex_trajectory_estimate_array = np.zeros(
            (self.num_radars, self.num_iterations), dtype=complex
        )
        
        for index in range(self.num_radars):
            angle_rad = np.deg2rad(self.radar_orientation_array[index])
            angle_correction = np.exp(-1j * angle_rad)
            
            for t in range(self.num_iterations):
                # Transform to radar local coordinate frame
                complex_trajectory_estimate_array[index, t] = (
                    (complex_trajectory_array[t] - self.complex_radar_position_array[index]) * 
                    angle_correction
                )
                # Add measurement noise
                noise = complex(
                    measurement_noise_std * np.random.randn(),
                    measurement_noise_std * np.random.randn()
                )
                complex_trajectory_estimate_array[index, t] += noise
        
        return complex_trajectory_estimate_array
    
    def compute_ground_truth_calibration(self):
        """Compute actual relative positions and orientations"""
        P_array = np.zeros((self.num_radars, self.num_radars), dtype=complex)
        theta_array = np.zeros((self.num_radars, self.num_radars))
        
        for i in range(self.num_radars):
            for k in range(self.num_radars):
                P_array[i, k] = (
                    (self.complex_radar_position_array[k] - self.complex_radar_position_array[i]) * 
                    np.exp(-1j * np.deg2rad(self.radar_orientation_array[i]))
                )
                theta_array[i, k] = self.radar_orientation_array[k] - self.radar_orientation_array[i]
        
        return P_array, theta_array
    
    def closed_form_calibration(self, complex_trajectory_estimate_array):
        """Perform closed-form calibration solution"""
        P_optimal_array = np.zeros((self.num_radars, self.num_radars), dtype=complex)
        theta_optimal_array = np.zeros((self.num_radars, self.num_radars))
        residual_array = np.zeros((self.num_radars, self.num_radars))
        
        for i in range(self.num_radars):
            for k in range(self.num_radars):
                z_i_hat_t = complex_trajectory_estimate_array[i, :]
                z_k_hat_t = complex_trajectory_estimate_array[k, :]
                z_i_hat_t_mean = np.mean(z_i_hat_t)
                z_k_hat_t_mean = np.mean(z_k_hat_t)
                
                # Compute correlation
                val = 0
                for t in range(self.num_iterations):
                    val += (z_k_hat_t[t] - z_k_hat_t_mean) * np.conj(z_i_hat_t[t] - z_k_hat_t_mean)
                
                # Extract orientation
                phi = np.arctan2(val.imag, val.real)
                theta_optimal_array[i, k] = np.rad2deg(-phi)
                
                # Extract position
                P_optimal_array[i, k] = z_i_hat_t_mean - np.exp(-1j * phi) * z_k_hat_t_mean
                
                # Compute residual
                sum_val = 0
                for t in range(self.num_iterations):
                    sum_val += (np.abs(z_k_hat_t[t] - z_k_hat_t_mean)**2 + 
                               np.abs(z_i_hat_t[t] - z_i_hat_t_mean)**2)
                
                sum_val -= 2 * np.abs(val)
                residual_array[i, k] = sum_val
        
        return P_optimal_array, theta_optimal_array, residual_array
    
    def get_averaged_calibration(self, P_optimal_array, theta_optimal_array):
        """Average calibration results across all radar pairs"""
        P_optimal_avg_array = np.zeros((self.num_radars, self.num_radars), dtype=complex)
        theta_optimal_avg_array = np.zeros((self.num_radars, self.num_radars))
        
        for ref_radar_index in range(self.num_radars):
            for i in range(self.num_radars):
                for k in range(self.num_radars):
                    P_optimal_avg_array[ref_radar_index, i] += (
                        (P_optimal_array[k, i] * 
                         np.exp(1j * np.deg2rad(theta_optimal_array[ref_radar_index, k]))) + 
                        P_optimal_array[ref_radar_index, k]
                    )
                    
                    new_added_theta = (theta_optimal_array[k, i] + 
                                      theta_optimal_array[ref_radar_index, k])
                    
                    # Prevent cyclic issues in angle averaging
                    new_added_theta = np.rad2deg(np.arctan2(
                        np.sin(np.deg2rad(new_added_theta)), 
                        np.cos(np.deg2rad(new_added_theta))
                    ))
                    
                    theta_optimal_avg_array[ref_radar_index, i] += new_added_theta
                
                P_optimal_avg_array[ref_radar_index, i] /= self.num_radars
                theta_optimal_avg_array[ref_radar_index, i] /= self.num_radars
        
        return P_optimal_avg_array, theta_optimal_avg_array
    
    def compute_calibration_errors(self, P_array, theta_array, 
                                   P_optimal_avg_array, theta_optimal_avg_array):
        """Compute calibration errors (position and orientation)"""
        position_errors = np.zeros((self.num_radars, self.num_radars))
        orientation_errors = np.zeros((self.num_radars, self.num_radars))
        
        for i in range(self.num_radars):
            for k in range(self.num_radars):
                if i != k:
                    position_errors[i, k] = np.abs(P_array[i, k] - P_optimal_avg_array[i, k])
                    
                    angle_diff = theta_array[i, k] - theta_optimal_avg_array[i, k]
                    # Normalize angle difference to [-180, 180]
                    angle_diff = np.rad2deg(np.arctan2(
                        np.sin(np.deg2rad(angle_diff)),
                        np.cos(np.deg2rad(angle_diff))
                    ))
                    orientation_errors[i, k] = np.abs(angle_diff)
        
        return position_errors, orientation_errors
    
    def plot_ground_truth(self, complex_trajectory_array):
        """Plot ground truth scenario"""
        plt.figure(figsize=(12, 10))
        
        plt.plot(complex_trajectory_array.real, complex_trajectory_array.imag, 
                'blue', linewidth=2, label='Target Trajectory', zorder=1)
        
        c = np.linspace(1, 100, self.num_radars)
        plt.scatter(self.complex_radar_position_array.real, 
                   self.complex_radar_position_array.imag, 
                   c=c, cmap='viridis', s=200, label='Radar Positions', 
                   edgecolors='black', linewidths=2, zorder=3)
        
        for index in range(self.num_radars):
            text_string = f"R{index+1}"
            plt.text(self.complex_radar_position_array[index].real + 2, 
                    self.complex_radar_position_array[index].imag + 3, 
                    text_string, fontsize=12, fontweight='bold')
        
        # Plot orientations
        U = 12 * np.cos(np.deg2rad(self.radar_orientation_array))
        V = 12 * np.sin(np.deg2rad(self.radar_orientation_array))
        plt.quiver(self.complex_radar_position_array.real, 
                  self.complex_radar_position_array.imag, 
                  U, V, scale=1, scale_units='xy', angles='xy', 
                  color='red', width=0.01, label='Radar Orientations', zorder=2)
        
        # Draw FOV polygon
        plot_radar_position_array = np.column_stack([
            self.radar_position_array, 
            self.radar_position_array[:, 0:1]
        ])
        plt.plot(plot_radar_position_array[0, :], plot_radar_position_array[1, :], 
                'g--', linewidth=2, alpha=0.5, label='Overlapping FOV')
        
        plt.legend(loc='best', fontsize=11)
        plt.xlabel("X-Axis (m)", fontsize=12)
        plt.ylabel("Y-Axis (m)", fontsize=12)
        plt.title(f"Ground Truth: 4-Radar {self.config.capitalize()} Configuration - "
                 f"Actual Target Trajectory, Radar Positions, Orientations & Overlapping FOV", 
                 fontsize=13, fontweight='bold')
        plt.grid(True, alpha=0.3)
        plt.axis('equal')
        plt.tight_layout()
        
        # Save plot
        if self.output_dir:
            filename = f"01_ground_truth_{self.config}_config.png"
            plt.savefig(os.path.join(self.output_dir, filename), dpi=300, bbox_inches='tight')
            print(f"Saved: {filename}")
    
    def plot_calibration_results_comprehensive(self, radar_0_index, 
                                              complex_trajectory_estimate,
                                              P_array, theta_array, 
                                              P_optimal_avg_array, 
                                              theta_optimal_avg_array,
                                              position_errors, orientation_errors):
        """Comprehensive calibration results plot"""
        fig = plt.figure(figsize=(16, 12))
        gs = GridSpec(2, 2, figure=fig)
        
        # Main calibration plot
        ax1 = fig.add_subplot(gs[0, :])
        ax1.plot(complex_trajectory_estimate[radar_0_index, :].real,
                complex_trajectory_estimate[radar_0_index, :].imag,
                'b-', linewidth=1.5, alpha=0.6, 
                label='Target Trajectory Estimate')
        
        ax1.scatter(P_optimal_avg_array[radar_0_index, :].real,
                   P_optimal_avg_array[radar_0_index, :].imag,
                   s=200, c='red', marker='X', edgecolors='darkred', linewidths=2,
                   label='Estimated Relative Position', zorder=3)
        
        ax1.scatter(P_array[radar_0_index, :].real,
                   P_array[radar_0_index, :].imag,
                   s=150, c='blue', edgecolors='darkblue', linewidths=2,
                   label='Actual Relative Position', zorder=3)
        
        # Actual orientations
        U = 10 * np.cos(np.deg2rad(theta_array[radar_0_index, :]))
        V = 10 * np.sin(np.deg2rad(theta_array[radar_0_index, :]))
        ax1.quiver(P_array[radar_0_index, :].real, P_array[radar_0_index, :].imag,
                  U, V, scale=1, scale_units='xy', angles='xy', color='blue',
                  width=0.008, label='Actual Relative Orientation', zorder=2)
        
        # Estimated orientations
        U_new = 15 * np.cos(np.deg2rad(theta_optimal_avg_array[radar_0_index, :]))
        V_new = 15 * np.sin(np.deg2rad(theta_optimal_avg_array[radar_0_index, :]))
        ax1.quiver(P_optimal_avg_array[radar_0_index, :].real,
                  P_optimal_avg_array[radar_0_index, :].imag,
                  U_new, V_new, scale=1, scale_units='xy', angles='xy', 
                  color='red', width=0.008, 
                  label='Estimated Relative Orientation', zorder=2)
        
        for index in range(self.num_radars):
            text_string = f"R{index+1}"
            ax1.text(P_optimal_avg_array[radar_0_index, index].real,
                    P_optimal_avg_array[radar_0_index, index].imag + 5,
                    text_string, fontsize=11, fontweight='bold')
        
        ax1.legend(loc='best', fontsize=10)
        ax1.set_xlabel("X-Axis (m)", fontsize=11)
        ax1.set_ylabel("Y-Axis (m)", fontsize=11)
        ax1.set_title(f"{self.config.capitalize()} Configuration: Radar {radar_0_index+1} Reference Frame - "
                     f"Target Trajectory with Estimated vs Actual Relative Radar Positions & Orientations", 
                     fontsize=12, fontweight='bold')
        ax1.grid(True, alpha=0.3)
        
        # Position errors plot
        ax2 = fig.add_subplot(gs[1, 0])
        non_diag_pos_errors = position_errors[radar_0_index, :][
            np.arange(self.num_radars) != radar_0_index
        ]
        radar_indices = [i+1 for i in range(self.num_radars) if i != radar_0_index]
        
        bars1 = ax2.bar(radar_indices, non_diag_pos_errors, 
                       color='steelblue', edgecolor='navy', linewidth=1.5)
        ax2.set_xlabel("Radar Index", fontsize=11)
        ax2.set_ylabel("Position Error (m)", fontsize=11)
        ax2.set_title(f"{self.config.capitalize()} Config: Position Calibration Errors "
                     f"(Reference Radar {radar_0_index+1} to Other Radars)", 
                     fontsize=11, fontweight='bold')
        ax2.grid(True, alpha=0.3, axis='y')
        
        # Add value labels on bars
        for bar in bars1:
            height = bar.get_height()
            ax2.text(bar.get_x() + bar.get_width()/2., height,
                    f'{height:.2f}m', ha='center', va='bottom', fontsize=9)
        
        # Orientation errors plot
        ax3 = fig.add_subplot(gs[1, 1])
        non_diag_orient_errors = orientation_errors[radar_0_index, :][
            np.arange(self.num_radars) != radar_0_index
        ]
        
        bars2 = ax3.bar(radar_indices, non_diag_orient_errors, 
                       color='coral', edgecolor='darkred', linewidth=1.5)
        ax3.set_xlabel("Radar Index", fontsize=11)
        ax3.set_ylabel("Orientation Error (degrees)", fontsize=11)
        ax3.set_title(f"{self.config.capitalize()} Config: Orientation Calibration Errors "
                     f"(Reference Radar {radar_0_index+1} to Other Radars)", 
                     fontsize=11, fontweight='bold')
        ax3.grid(True, alpha=0.3, axis='y')
        
        # Add value labels on bars
        for bar in bars2:
            height = bar.get_height()
            ax3.text(bar.get_x() + bar.get_width()/2., height,
                    f'{height:.2f}°', ha='center', va='bottom', fontsize=9)
        
        plt.tight_layout()
        
        # Save plot
        if self.output_dir:
            filename = f"0{radar_0_index+2}_{self.config}_calibration_radar{radar_0_index+1}_reference.png"
            plt.savefig(os.path.join(self.output_dir, filename), dpi=300, bbox_inches='tight')
            print(f"Saved: {filename}")
    
    def plot_error_summary(self, position_errors, orientation_errors):
        """Plot summary of all calibration errors"""
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
        
        # Position error heatmap
        im1 = ax1.imshow(position_errors, cmap='YlOrRd', aspect='auto')
        ax1.set_xticks(np.arange(self.num_radars))
        ax1.set_yticks(np.arange(self.num_radars))
        ax1.set_xticklabels([f'R{i+1}' for i in range(self.num_radars)])
        ax1.set_yticklabels([f'R{i+1}' for i in range(self.num_radars)])
        ax1.set_xlabel("Target Radar", fontsize=11)
        ax1.set_ylabel("Reference Radar", fontsize=11)
        ax1.set_title(f"{self.config.capitalize()} Configuration: Position Calibration Error Heatmap "
                     f"(All Radar Pairs in meters)", fontsize=12, fontweight='bold')
        
        # Add text annotations
        for i in range(self.num_radars):
            for j in range(self.num_radars):
                if i != j:
                    text = ax1.text(j, i, f'{position_errors[i, j]:.2f}',
                                   ha="center", va="center", color="black", fontsize=10)
        
        plt.colorbar(im1, ax=ax1, label='Error (m)')
        
        # Orientation error heatmap
        im2 = ax2.imshow(orientation_errors, cmap='YlOrRd', aspect='auto')
        ax2.set_xticks(np.arange(self.num_radars))
        ax2.set_yticks(np.arange(self.num_radars))
        ax2.set_xticklabels([f'R{i+1}' for i in range(self.num_radars)])
        ax2.set_yticklabels([f'R{i+1}' for i in range(self.num_radars)])
        ax2.set_xlabel("Target Radar", fontsize=11)
        ax2.set_ylabel("Reference Radar", fontsize=11)
        ax2.set_title(f"{self.config.capitalize()} Configuration: Orientation Calibration Error Heatmap "
                     f"(All Radar Pairs in degrees)", fontsize=12, fontweight='bold')
        
        # Add text annotations
        for i in range(self.num_radars):
            for j in range(self.num_radars):
                if i != j:
                    text = ax2.text(j, i, f'{orientation_errors[i, j]:.2f}',
                                   ha="center", va="center", color="black", fontsize=10)
        
        plt.colorbar(im2, ax=ax2, label='Error (degrees)')
        plt.tight_layout()
        
        # Save plot
        if self.output_dir:
            filename = f"06_{self.config}_error_heatmaps_all_pairs.png"
            plt.savefig(os.path.join(self.output_dir, filename), dpi=300, bbox_inches='tight')
            print(f"Saved: {filename}")
    
    def run_full_analysis(self, noise_std=0.5, measurement_noise_std=0.5, 
                         random_seed=42):
        """Run complete calibration analysis"""
        if random_seed is not None:
            np.random.seed(random_seed)
        
        # Create output directory
        self.create_output_directory()
        
        print(f"\n{'='*60}")
        print(f"4-Node Radar Calibration Analysis")
        print(f"Configuration: {self.config.upper()}")
        print(f"Output Directory: {self.output_dir}")
        print(f"{'='*60}\n")
        
        # Generate data
        print("Generating synthetic data...")
        complex_trajectory_array = self.generate_trajectory(
            vel_x_max=0, vel_y_max=-1, noise_std=noise_std
        )
        complex_trajectory_estimate_array = self.generate_radar_observations(
            complex_trajectory_array, measurement_noise_std=measurement_noise_std
        )
        
        # Compute ground truth
        print("Computing ground truth calibration...")
        P_array, theta_array = self.compute_ground_truth_calibration()
        
        # Run closed-form calibration
        print("Running closed-form calibration...")
        P_optimal_array, theta_optimal_array, residual_array = \
            self.closed_form_calibration(complex_trajectory_estimate_array)
        
        # Average calibration results
        print("Averaging calibration results...")
        P_optimal_avg_array, theta_optimal_avg_array = \
            self.get_averaged_calibration(P_optimal_array, theta_optimal_array)
        
        # Compute errors
        print("Computing calibration errors...")
        position_errors, orientation_errors = self.compute_calibration_errors(
            P_array, theta_array, P_optimal_avg_array, theta_optimal_avg_array
        )
        
        # Print statistics
        print(f"\n{'='*60}")
        print("Calibration Error Statistics:")
        print(f"{'='*60}")
        
        non_diag_pos_errors = position_errors[np.eye(self.num_radars) == 0]
        non_diag_orient_errors = orientation_errors[np.eye(self.num_radars) == 0]
        
        print(f"Position Errors:")
        print(f"  Mean:   {np.mean(non_diag_pos_errors):.3f} m")
        print(f"  Std:    {np.std(non_diag_pos_errors):.3f} m")
        print(f"  Max:    {np.max(non_diag_pos_errors):.3f} m")
        print(f"  Min:    {np.min(non_diag_pos_errors):.3f} m")
        
        print(f"\nOrientation Errors:")
        print(f"  Mean:   {np.mean(non_diag_orient_errors):.3f}°")
        print(f"  Std:    {np.std(non_diag_orient_errors):.3f}°")
        print(f"  Max:    {np.max(non_diag_orient_errors):.3f}°")
        print(f"  Min:    {np.min(non_diag_orient_errors):.3f}°")
        print(f"{'='*60}\n")
        
        # Generate plots
        print("Generating plots...")
        self.plot_ground_truth(complex_trajectory_array)
        
        for index in range(self.num_radars):
            self.plot_calibration_results_comprehensive(
                index, complex_trajectory_estimate_array,
                P_array, theta_array, P_optimal_avg_array, theta_optimal_avg_array,
                position_errors, orientation_errors
            )
        
        self.plot_error_summary(position_errors, orientation_errors)
        
        print(f"\nAnalysis complete! All plots saved to: {self.output_dir}")
        
        return {
            'position_errors': position_errors,
            'orientation_errors': orientation_errors,
            'P_optimal_avg': P_optimal_avg_array,
            'theta_optimal_avg': theta_optimal_avg_array,
            'P_actual': P_array,
            'theta_actual': theta_array
        }


def compare_configurations():
    """Compare different 4-node configurations"""
    configs = ['square', 'linear', 'L-shape', 'diamond']
    results = {}
    
    # Create comparison output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    comparison_dir = os.path.join("output", f"comparison_{timestamp}")
    os.makedirs(comparison_dir, exist_ok=True)
    
    print("\n" + "="*70)
    print("COMPARING DIFFERENT 4-NODE CONFIGURATIONS")
    print(f"Comparison output directory: {comparison_dir}")
    print("="*70)
    
    for config in configs:
        print(f"\nRunning configuration: {config.upper()}")
        calibrator = FourNodeRadarCalibration(config=config)
        results[config] = calibrator.run_full_analysis(
            noise_std=0.5, 
            measurement_noise_std=0.5,
            random_seed=42
        )
    
    # Summary comparison plot
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    config_names = []
    mean_pos_errors = []
    mean_orient_errors = []
    
    for config in configs:
        config_names.append(config.capitalize())
        pos_errors = results[config]['position_errors']
        orient_errors = results[config]['orientation_errors']
        
        non_diag_pos = pos_errors[np.eye(4) == 0]
        non_diag_orient = orient_errors[np.eye(4) == 0]
        
        mean_pos_errors.append(np.mean(non_diag_pos))
        mean_orient_errors.append(np.mean(non_diag_orient))
    
    ax1.bar(config_names, mean_pos_errors, color=['steelblue', 'coral', 'mediumseagreen', 'gold'],
           edgecolor='black', linewidth=1.5)
    ax1.set_ylabel("Mean Position Error (m)", fontsize=11)
    ax1.set_title("Configuration Comparison: Position Errors", fontsize=12, fontweight='bold')
    ax1.grid(True, alpha=0.3, axis='y')
    
    for i, v in enumerate(mean_pos_errors):
        ax1.text(i, v, f'{v:.3f}m', ha='center', va='bottom', fontsize=10, fontweight='bold')
    
    ax2.bar(config_names, mean_orient_errors, color=['steelblue', 'coral', 'mediumseagreen', 'gold'],
           edgecolor='black', linewidth=1.5)
    ax2.set_ylabel("Mean Orientation Error (degrees)", fontsize=11)
    ax2.set_title("Configuration Comparison: Orientation Errors", fontsize=12, fontweight='bold')
    ax2.grid(True, alpha=0.3, axis='y')
    
    for i, v in enumerate(mean_orient_errors):
        ax2.text(i, v, f'{v:.3f}°', ha='center', va='bottom', fontsize=10, fontweight='bold')
    
    plt.tight_layout()
    
    # Save comparison plot
    filename = "config_comparison_summary.png"
    plt.savefig(os.path.join(comparison_dir, filename), dpi=300, bbox_inches='tight')
    print(f"\nSaved comparison plot: {filename}")
    print(f"All comparison results saved to: {comparison_dir}")
    
    plt.show()


def main():
    """Main function with menu options"""
    print("\n" + "="*70)
    print("4-NODE RADAR CALIBRATION SYSTEM")
    print("="*70)
    print("\nOptions:")
    print("1. Run single configuration (default: square)")
    print("2. Compare all configurations")
    print("3. Custom configuration")
    
    choice = input("\nEnter choice (1/2/3) [default: 1]: ").strip() or "1"
    
    if choice == "1":
        config = input("Enter configuration (square/linear/L-shape/diamond) [default: square]: ").strip() or "square"
        calibrator = FourNodeRadarCalibration(config=config)
        calibrator.run_full_analysis()
        plt.show()
    
    elif choice == "2":
        compare_configurations()
    
    elif choice == "3":
        print("\nCustom configuration not yet implemented. Using square configuration.")
        calibrator = FourNodeRadarCalibration(config='square')
        calibrator.run_full_analysis()
        plt.show()
    
    else:
        print("Invalid choice. Using default square configuration.")
        calibrator = FourNodeRadarCalibration(config='square')
        calibrator.run_full_analysis()
        plt.show()


if __name__ == "__main__":
    main()

