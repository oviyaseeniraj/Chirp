% Get synthesized data
generate_synthetic_data;
%multi_target_out_of_fov;

% Get the actual relative positions and orientations of the Radars wrt each
% other
P_array = zeros([num_radars num_radars]);
theta_array = zeros([num_radars num_radars]);

for i=1:num_radars
    for k=1:num_radars
        P_array(i, k) = (complex_radar_position_array(k) - complex_radar_position_array(i))*exp(-1j*deg2rad(radar_orientation_array(i)));
        theta_array(i, k) = radar_orientation_array(k) - radar_orientation_array(i);
    end
end

P_optimal_array = zeros([num_radars num_radars]);
theta_optimal_array = zeros([num_radars num_radars]);
residual_array = zeros([num_radars num_radars]);

for i=1:num_radars
    for k=1:num_radars
        z_i_hat_t = complex_trajectory_estimate_array(i, :);
        z_k_hat_t = complex_trajectory_estimate_array(k, :);
        z_i_hat_t_mean = mean(z_i_hat_t);
        z_k_hat_t_mean = mean(z_k_hat_t);

        val = 0;
        for t=1:num_iterations
            val = val + (z_k_hat_t(t) - z_k_hat_t_mean)*(conj(z_i_hat_t(t) - z_k_hat_t_mean));
        end

        phi = atan2(imag(val), real(val));
        theta_optimal_array(i, k) = rad2deg(-phi);
        P_optimal_array(i, k) = z_i_hat_t_mean - exp(-1j*phi)*z_k_hat_t_mean;

        sum = 0;
        for t=1:num_iterations
            sum = sum + (abs(z_k_hat_t(t) - z_k_hat_t_mean))^2 + (abs(z_i_hat_t(t) - z_i_hat_t_mean))^2;
        end

        sum = sum - 2*abs(val);
        residual_array(i, k) = sum;
    end
end

%==========================================================================
% Plot averaged relative calibration results for Multi-Radar Network

[P_optimal_avg_array, theta_optimal_avg_array] = get_averaged_calibration(num_radars, P_optimal_array, theta_optimal_array);

%==========================================================================
% Plot relative averaged calibration results for Radar Network
for index=1:num_radars
    plot_relative_calibration_info(index, num_radars, complex_trajectory_estimate_array, ...
        P_array, theta_array, P_optimal_avg_array, theta_optimal_avg_array);
end

%==========================================================================
% Get averaged calibration info for multi-radar scenario
function [P_optimal_avg_array, theta_optimal_avg_array] = get_averaged_calibration(num_radars, P_optimal_array, theta_optimal_array)

    P_optimal_avg_array = zeros([num_radars num_radars]);
    theta_optimal_avg_array = zeros([num_radars num_radars]);

    for ref_radar_index=1:num_radars
        for i=1:num_radars
            for k=1:num_radars
                P_optimal_avg_array(ref_radar_index, i) = P_optimal_avg_array(ref_radar_index, i) + (P_optimal_array(k, i)*exp(1j*deg2rad(theta_optimal_array(ref_radar_index, k)))) + P_optimal_array(ref_radar_index, k);
                
                new_added_theta = theta_optimal_array(k, i) + theta_optimal_array(ref_radar_index, k);

                % Prevent cyclic issues in angle averaging
                new_added_theta = atan2d(sind(new_added_theta), cosd(new_added_theta));
                
                theta_optimal_avg_array(ref_radar_index, i) = theta_optimal_avg_array(ref_radar_index, i) + new_added_theta;
            end
            P_optimal_avg_array(ref_radar_index, i) = P_optimal_avg_array(ref_radar_index, i)/num_radars;
            theta_optimal_avg_array(ref_radar_index, i) = theta_optimal_avg_array(ref_radar_index, i)/num_radars;
        end
    end
end

%==========================================================================
% Function to plot relative radar calibration info
function [] = plot_relative_calibration_info(radar_0_index, num_radars, ...
                    complex_trajectory_estimate, P_array, theta_array, ...
                    P_optimal_array, theta_optimal_array)

    figure;
    plot(real(complex_trajectory_estimate(radar_0_index, :)), ...
         imag(complex_trajectory_estimate(radar_0_index, :)), "LineWidth", 1.5);
    hold on;

    scatter(real(P_optimal_array(radar_0_index, :)), imag(P_optimal_array(radar_0_index, :)), ...
            140, "red", "X");

    scatter(real(P_array(radar_0_index, :)), imag(P_array(radar_0_index, :)), ...
            "blue", "filled");

    U = 10*cos(deg2rad(theta_array(radar_0_index, :)));
    V = 10*sin(deg2rad(theta_array(radar_0_index, :)));

    quiver(real(P_array(radar_0_index, :)), imag(P_array(radar_0_index, :)), U, V, "off", "black");

    U_new = 15*cos(deg2rad(theta_optimal_array(radar_0_index, :)));
    V_new = 15*sin(deg2rad(theta_optimal_array(radar_0_index, :)));

    quiver(real(P_optimal_array(radar_0_index, :)), imag(P_optimal_array(radar_0_index, :)), ...
           U_new, V_new, "off", "magenta");

    for index=1:num_radars
        text_string = sprintf("Radar %d", index);
        text(real(P_optimal_array(radar_0_index, index)), ...
             imag(P_optimal_array(radar_0_index, index))+4, ...
             text_string, 'FontSize', 10);
    end

    hold off;
    legend("Target Trajectory Estimate wrt Ref Radar", "Averaged Radar_i Optimal Relative Position wrt Ref Radar", ...
           "Radar_i Actual Relative Position wrt Ref Radar", ...
           "Radar_i Actual Relative Orientation wrt Ref Radar", ...
           "Averaged Radar_i Optimal Relative Orientation wrt Ref Radar");
        
    xlabel("X-Axis");
    ylabel("Y-Axis");
    title("Relative Averaged Calibration Data for Ref Radar ", num2str(radar_0_index));
    grid on;
    axis([-20 100 -80 80]);
end