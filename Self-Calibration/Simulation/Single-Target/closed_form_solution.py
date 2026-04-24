import numpy as np
import matplotlib.pyplot as plt
import os
from datetime import datetime
from matplotlib.patches import FancyArrowPatch

def get_synthetic_trajectory(initial_target_position, vel_x_max, vel_y_max, num_iterations):
    """Generate synthetic target trajectory"""
    new_target_position = initial_target_position
    complex_trajectory_array = np.zeros(num_iterations, dtype=complex)
    
    for t in range(num_iterations):
        z_t = trajectory_formation(new_target_position, vel_x_max, vel_y_max)
        complex_trajectory_array[t] = z_t
        new_target_position = z_t
    
    return complex_trajectory_array

def trajectory_formation(complex_initial_position, vel_x_max, vel_y_max):
    """Generate next position in trajectory with random velocity"""
    delta_x = 2 * np.random.rand()
    delta_y = 2 * np.random.rand()
    max_x_velocity = vel_x_max
    max_y_velocity = vel_y_max
    complex_axial_velocity = complex(delta_x * max_x_velocity, delta_y * max_y_velocity)
    complex_new_position = complex_initial_position + complex_axial_velocity
    
    noise = complex(0.5 * np.random.randn(), 0.5 * np.random.randn())
    complex_new_position = complex_new_position + noise
    
    return complex_new_position

def generate_synthetic_data(output_dir=None):
    """Generate synthetic radar data"""
    # Configuration
    num_radars = 4
    num_targets = 1
    quantized_angle_degrees = 1
    num_iterations = 100
    initial_target_position = 20 + 1j*40
    
    # Generate target trajectory
    complex_trajectory_array = get_synthetic_trajectory(
        initial_target_position, 0, -1, num_iterations
    )
    
    # Radar positions and orientations
    radar_position_array = np.array([
        [0, 40, 40, 0],
        [-20, -20, 20, 20]
    ])
    radar_orientation_array = np.array([45, 135, 225, 315])
    
    complex_radar_position_array = radar_position_array[0, :] + 1j * radar_position_array[1, :]
    
    # Generate trajectory estimates for each radar
    complex_trajectory_estimate_array = np.zeros((num_radars, num_iterations), dtype=complex)
    
    for index in range(num_radars):
        angle_rad = np.deg2rad(radar_orientation_array[index])
        angle_correction = np.exp(-1j * angle_rad)
        for t in range(num_iterations):
            complex_trajectory_estimate_array[index, t] = (
                (complex_trajectory_array[t] - complex_radar_position_array[index]) * angle_correction
            )
            noise = complex(0.5 * np.random.randn(), 0.5 * np.random.randn())
            complex_trajectory_estimate_array[index, t] += noise
    
    # Plot Ground Truth Data
    plt.figure(figsize=(10, 8))
    plt.plot(complex_trajectory_array.real, complex_trajectory_array.imag, 
             'blue', linewidth=1.5, label='Target Trajectory')
    
    c = np.linspace(1, 100, num_radars)
    plt.scatter(complex_radar_position_array.real, complex_radar_position_array.imag, 
                c=c, cmap='viridis', s=100, label='Radar_i position')
    
    for index in range(num_radars):
        text_string = f"Radar {index+1}"
        plt.text(complex_radar_position_array[index].real - 2, 
                complex_radar_position_array[index].imag - 3, 
                text_string, fontsize=10)
    
    U = 12 * np.cos(np.deg2rad(radar_orientation_array))
    V = 12 * np.sin(np.deg2rad(radar_orientation_array))
    plt.quiver(complex_radar_position_array.real, complex_radar_position_array.imag, 
              U, V, scale=1, scale_units='xy', angles='xy', color='black', 
              label='Radar_i orientation')
    
    # Draw rectangle signifying overlapping FOV
    plot_radar_position_array = np.column_stack([
        radar_position_array, 
        radar_position_array[:, 0:1]
    ])
    plt.plot(plot_radar_position_array[0, :], plot_radar_position_array[1, :], 'r-')
    
    text_pos_x = np.max(radar_position_array[0, :])
    text_pos_y = np.mean(radar_position_array[1, :])
    plt.text(text_pos_x + 0.5, text_pos_y, 'Overlapping FOV', fontsize=10)
    
    plt.text(initial_target_position.real + 2, initial_target_position.imag - 3, 
            'Target Trajectory', fontsize=10)
    
    plt.legend()
    plt.xlabel("X-Axis (m)")
    plt.ylabel("Y-Axis (m)")
    plt.title("Ground Truth: 4-Radar Square Configuration - Actual Target Trajectory, Radar Positions & Orientations")
    plt.axis([-20, 60, -50, 50])
    plt.grid(True)
    plt.tight_layout()
    
    # Save plot if output directory provided
    if output_dir:
        filename = "01_ground_truth_square_config.png"
        plt.savefig(os.path.join(output_dir, filename), dpi=300, bbox_inches='tight')
        print(f"Saved: {filename}")
    
    return (num_radars, num_iterations, complex_trajectory_array, 
            radar_position_array, radar_orientation_array, 
            complex_radar_position_array, complex_trajectory_estimate_array)

def get_averaged_calibration(num_radars, P_optimal_array, theta_optimal_array):
    """Get averaged calibration info for multi-radar scenario"""
    P_optimal_avg_array = np.zeros((num_radars, num_radars), dtype=complex)
    theta_optimal_avg_array = np.zeros((num_radars, num_radars))
    
    for ref_radar_index in range(num_radars):
        for i in range(num_radars):
            for k in range(num_radars):
                P_optimal_avg_array[ref_radar_index, i] += (
                    (P_optimal_array[k, i] * np.exp(1j * np.deg2rad(theta_optimal_array[ref_radar_index, k]))) + 
                    P_optimal_array[ref_radar_index, k]
                )
                
                new_added_theta = theta_optimal_array[k, i] + theta_optimal_array[ref_radar_index, k]
                
                # Prevent cyclic issues in angle averaging
                new_added_theta = np.rad2deg(np.arctan2(
                    np.sin(np.deg2rad(new_added_theta)), 
                    np.cos(np.deg2rad(new_added_theta))
                ))
                
                theta_optimal_avg_array[ref_radar_index, i] += new_added_theta
            
            P_optimal_avg_array[ref_radar_index, i] /= num_radars
            theta_optimal_avg_array[ref_radar_index, i] /= num_radars
    
    return P_optimal_avg_array, theta_optimal_avg_array

def plot_relative_calibration_info(radar_0_index, num_radars, complex_trajectory_estimate,
                                   P_array, theta_array, P_optimal_array, theta_optimal_array,
                                   output_dir=None):
    """Plot relative radar calibration info"""
    plt.figure(figsize=(12, 10))
    
    plt.plot(complex_trajectory_estimate[radar_0_index, :].real,
            complex_trajectory_estimate[radar_0_index, :].imag,
            linewidth=1.5, label='Target Trajectory Estimate wrt Ref Radar')
    
    plt.scatter(P_optimal_array[radar_0_index, :].real,
               P_optimal_array[radar_0_index, :].imag,
               s=140, c='red', marker='X',
               label='Averaged Radar_i Optimal Relative Position wrt Ref Radar')
    
    plt.scatter(P_array[radar_0_index, :].real,
               P_array[radar_0_index, :].imag,
               c='blue', s=100,
               label='Radar_i Actual Relative Position wrt Ref Radar')
    
    U = 10 * np.cos(np.deg2rad(theta_array[radar_0_index, :]))
    V = 10 * np.sin(np.deg2rad(theta_array[radar_0_index, :]))
    plt.quiver(P_array[radar_0_index, :].real, P_array[radar_0_index, :].imag,
              U, V, scale=1, scale_units='xy', angles='xy', color='black',
              label='Radar_i Actual Relative Orientation wrt Ref Radar')
    
    U_new = 15 * np.cos(np.deg2rad(theta_optimal_array[radar_0_index, :]))
    V_new = 15 * np.sin(np.deg2rad(theta_optimal_array[radar_0_index, :]))
    plt.quiver(P_optimal_array[radar_0_index, :].real,
              P_optimal_array[radar_0_index, :].imag,
              U_new, V_new, scale=1, scale_units='xy', angles='xy', color='magenta',
              label='Averaged Radar_i Optimal Relative Orientation wrt Ref Radar')
    
    for index in range(num_radars):
        text_string = f"Radar {index+1}"
        plt.text(P_optimal_array[radar_0_index, index].real,
                P_optimal_array[radar_0_index, index].imag + 4,
                text_string, fontsize=10)
    
    plt.legend(loc='best', fontsize=9)
    plt.xlabel("X-Axis (m)")
    plt.ylabel("Y-Axis (m)")
    plt.title(f"Square Configuration: Radar {radar_0_index+1} Reference Frame - "
             f"Averaged Calibration Results (Estimated vs Actual Relative Positions & Orientations)")
    plt.grid(True)
    plt.axis([-20, 100, -80, 80])
    plt.tight_layout()
    
    # Save plot if output directory provided
    if output_dir:
        filename = f"0{radar_0_index+2}_calibration_radar{radar_0_index+1}_reference.png"
        plt.savefig(os.path.join(output_dir, filename), dpi=300, bbox_inches='tight')
        print(f"Saved: {filename}")

def create_output_directory():
    """Create output directory structure"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join("output", f"basic_calibration_{timestamp}")
    os.makedirs(output_dir, exist_ok=True)
    return output_dir

def main():
    """Main function to run closed form solution for radar calibration"""
    # Set random seed for reproducibility (optional, comment out for random results)
    np.random.seed(42)
    
    # Create output directory
    output_dir = create_output_directory()
    print(f"Output directory: {output_dir}")
    
    # Get synthesized data
    (num_radars, num_iterations, complex_trajectory_array, radar_position_array,
     radar_orientation_array, complex_radar_position_array,
     complex_trajectory_estimate_array) = generate_synthetic_data(output_dir)
    
    # Get the actual relative positions and orientations of the Radars wrt each other
    P_array = np.zeros((num_radars, num_radars), dtype=complex)
    theta_array = np.zeros((num_radars, num_radars))
    
    for i in range(num_radars):
        for k in range(num_radars):
            P_array[i, k] = (
                (complex_radar_position_array[k] - complex_radar_position_array[i]) * 
                np.exp(-1j * np.deg2rad(radar_orientation_array[i]))
            )
            theta_array[i, k] = radar_orientation_array[k] - radar_orientation_array[i]
    
    # Calculate optimal positions and orientations
    P_optimal_array = np.zeros((num_radars, num_radars), dtype=complex)
    theta_optimal_array = np.zeros((num_radars, num_radars))
    residual_array = np.zeros((num_radars, num_radars))
    
    for i in range(num_radars):
        for k in range(num_radars):
            z_i_hat_t = complex_trajectory_estimate_array[i, :]
            z_k_hat_t = complex_trajectory_estimate_array[k, :]
            z_i_hat_t_mean = np.mean(z_i_hat_t)
            z_k_hat_t_mean = np.mean(z_k_hat_t)
            
            val = 0
            for t in range(num_iterations):
                val += (z_k_hat_t[t] - z_k_hat_t_mean) * np.conj(z_i_hat_t[t] - z_k_hat_t_mean)
            
            phi = np.arctan2(val.imag, val.real)
            theta_optimal_array[i, k] = np.rad2deg(-phi)
            P_optimal_array[i, k] = z_i_hat_t_mean - np.exp(-1j * phi) * z_k_hat_t_mean
            
            sum_val = 0
            for t in range(num_iterations):
                sum_val += (np.abs(z_k_hat_t[t] - z_k_hat_t_mean)**2 + 
                           np.abs(z_i_hat_t[t] - z_i_hat_t_mean)**2)
            
            sum_val -= 2 * np.abs(val)
            residual_array[i, k] = sum_val
    
    # Plot averaged relative calibration results for Multi-Radar Network
    P_optimal_avg_array, theta_optimal_avg_array = get_averaged_calibration(
        num_radars, P_optimal_array, theta_optimal_array
    )
    
    # Plot relative averaged calibration results for Radar Network
    for index in range(num_radars):
        plot_relative_calibration_info(index, num_radars, complex_trajectory_estimate_array,
                                      P_array, theta_array, P_optimal_avg_array, theta_optimal_avg_array,
                                      output_dir)
    
    print(f"\nAll plots saved to: {output_dir}")
    plt.show()

if __name__ == "__main__":
    main()

