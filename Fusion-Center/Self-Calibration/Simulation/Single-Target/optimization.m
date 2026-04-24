% Getting the results for N radars. Selecting one radar each time as the
% reference and obtaining the otimal location and orientation of the others
% relative to it.

function [complex_radar_relative_optimal_position_array, radar_relative_optimal_orientation_array] = optimization(complex_radar_position_array, ...
                                                 radar_orientation_array, complex_trajectory_estimate_array, ...
                                                 num_radars, radar_0_index, num_iterations, quantized_angle_degrees, plot_results)

    complex_radar_0_position = complex_radar_position_array(radar_0_index);
    radar_0_orientation = radar_orientation_array(radar_0_index);

    complex_radar_relative_optimal_position_array = zeros([1 num_radars]);
    radar_relative_optimal_orientation_array = zeros([1 num_radars]);

    for index = 1:num_radars
        if index == radar_0_index
            complex_radar_relative_optimal_position_array(:, index) = complex(0, 0);
            radar_relative_optimal_orientation_array(:, index) = 0;
        else

            [complex_radar_optimal_position, radar_optimal_orientation] = get_optimized_data(num_iterations, ...
                                   radar_0_index, index, complex_trajectory_estimate_array, ...
                                   quantized_angle_degrees);

            complex_radar_relative_optimal_position_array(:, index) = complex_radar_optimal_position;
            radar_relative_optimal_orientation_array(:, index) = radar_optimal_orientation;
        end
    end

    if plot_results
        % Relative Position of the kth Radar w.r.t. ith Radar -> P_ki
        % P_ki = (P_k - P_i)e^(-j*theta_i)
        radar_0_orientation_rad = deg2rad(radar_0_orientation);
        complex_radar_relative_position_array = (complex_radar_position_array - complex_radar_0_position) * exp(-1j*radar_0_orientation_rad);
        radar_relative_orientation_array = radar_orientation_array - radar_0_orientation;

        figure;
        plot(real(complex_trajectory_estimate_array(radar_0_index, :)), imag(complex_trajectory_estimate_array(radar_0_index, :)), "LineWidth", 1.5);
        hold on;

        scatter(real(complex_radar_relative_optimal_position_array(:)), ...
                    imag(complex_radar_relative_optimal_position_array(:)), 140, "red", "X");

        scatter(real(complex_radar_relative_position_array(:)), imag(complex_radar_relative_position_array(:)), "blue", "filled");

        U = 5*cos(deg2rad(radar_relative_orientation_array(:)));
        V = 5*sin(deg2rad(radar_relative_orientation_array(:)));

        quiver(real(complex_radar_relative_position_array(:)), imag(complex_radar_relative_position_array(:)), U, V, "off", "black");

        U_new = 6*cos(radar_relative_optimal_orientation_array(:));
        V_new = 6*sin(radar_relative_optimal_orientation_array(:));

        quiver(real(complex_radar_relative_optimal_position_array(:)), imag(complex_radar_relative_optimal_position_array(:)), U_new, V_new, "off", "magenta");

        for index=1:num_radars
            text_string = sprintf("Radar %d", index);
            text(real(complex_radar_relative_optimal_position_array(index)), imag(complex_radar_relative_optimal_position_array(index))+4, text_string, 'FontSize', 8);
        end

        hold off;
        legend("Target Trajectory", "Radar_i Relative Optimal Position wrt Radar_0", ...
               "Radar_i Actual Relative Position wrt Radar_0", ...
               "Radar_i Actual Relative Orientation wrt Radar_0", ...
               "Radar_i Relative Optimal Orientation wrt Radar_0");
        
        xlabel("X-Axis");
        ylabel("Y-Axis");
        title("Relative Data for Ref Radar ", num2str(radar_0_index));
        grid on;
    end
end

function [radar_optimal_position, radar_optimal_orientation] = get_optimized_data(num_iterations, ...
                                                      radar_0_index, radar_i_index, ...
                                                      complex_trajectory_estimate_array, ...
                                                      quantized_angle_degrees)
    orientation_angle_quantized_rad = deg2rad(quantized_angle_degrees);
    num_quantizations = 2*pi/orientation_angle_quantized_rad;
    radar_i_quantized_orientation_array = linspace(orientation_angle_quantized_rad, ...
                                               2*pi, num_quantizations);
    radar_i_optimal_position_array = ([1 num_quantizations]);
    cost_array = zeros([1 num_quantizations]);

    % Linear Least Squares Optimization :
    % minimize f(x) = ||Ax - b||^2

    A = ones([num_iterations 1]);
    complex_b_array = zeros([num_iterations num_quantizations]);

    complex_trajectory_estimate_array_radar_0 = complex_trajectory_estimate_array(radar_0_index, :);
    complex_trajectory_estimate_array_radar_i = complex_trajectory_estimate_array(radar_i_index, :);

    for t=1:num_iterations
        complex_z_0_hat_t = complex_trajectory_estimate_array_radar_0(t);
        complex_z_i_hat_t = complex_trajectory_estimate_array_radar_i(t);
        
        for quant=1:num_quantizations
            complex_b = complex_z_0_hat_t - exp(1j*radar_i_quantized_orientation_array(quant))*complex_z_i_hat_t;
            complex_b_array(t, quant) = complex_b;
        end
    end

    for quant = 1:num_quantizations
        [radar_i_optimized_position, resnorm] = lsqlin(A, complex_b_array(:, quant), [], []);
        radar_i_optimal_position_array(1, quant) = radar_i_optimized_position;
        cost_array(quant) = abs(resnorm);
    end

    [~, optimal_index] = min(cost_array);

    radar_optimal_position = radar_i_optimal_position_array(1, optimal_index);
    radar_optimal_orientation = radar_i_quantized_orientation_array(optimal_index);
end