
% Get the configurations defined in the config file
%config;

% Get synthesized data
generate_synthetic_data;

% Get the Optimization results for all the N radars
complex_radar_relative_optimal_position_array = zeros([num_radars num_radars]);
radar_relative_optimal_orientation_array = zeros([num_radars num_radars]);

for index = 1:num_radars
    [complex_radar_relative_optimal_position_array_i, radar_relative_optimal_orientation_array_i] = optimization(complex_radar_position_array, ...
                            radar_orientation_array, complex_trajectory_estimate_array, ...
                            num_radars, index, num_iterations, quantized_angle_degrees, true);

    complex_radar_relative_optimal_position_array(index, :) = complex_radar_relative_optimal_position_array_i;
    radar_relative_optimal_orientation_array(index, :) = radar_relative_optimal_orientation_array_i;
end

%-------------------------------------------------------------------------

[relative_optimal_position_array_shifted, relative_optimal_orientation_array_shifted] = shift_relative_calibration(complex_radar_relative_optimal_position_array, ...
                    radar_relative_optimal_orientation_array, 1, num_radars, true);

% Convert radian angle array to degrees
radar_relative_optimal_orientation_array = rad2deg(radar_relative_optimal_orientation_array);
relative_optimal_orientation_array_shifted = rad2deg(relative_optimal_orientation_array_shifted);

%--------------------------------------------------------------------------

% We currently have the relative position and orientation matrices with
% respect to each radar. We can shift and rotate to a consistent coordinate
% system (Maybe for a single radar, and check if that is consistent with
% it's own relative results.

% For example, we have relative results for Radar 1, 2, 3, 4. We shift
% their coordinate systems (For 2, 3, 4) so that we get the relative
% results for Radar 1 for checking consistency.

function [relative_optimal_position_array_shifted, relative_optimal_orientation_array_shifted] = shift_relative_calibration(relative_radar_position_array, ...
         relative_radar_orientation_array, ref_radar_index, num_radars, plot_results)
    
    c = linspace(1, 100, num_radars);

    relative_optimal_position_array_shifted = relative_radar_position_array;
    relative_optimal_orientation_array_shifted = relative_radar_orientation_array;

    for i = 1:num_radars
        relative_optimal_position_array_shifted(i, :) = relative_optimal_position_array_shifted(i, :) - relative_optimal_position_array_shifted(i, ref_radar_index);
        
        shifted_angle_array = relative_optimal_orientation_array_shifted(i, :) - relative_optimal_orientation_array_shifted(i, ref_radar_index);
        shifted_angle_array(shifted_angle_array < 0) = shifted_angle_array(shifted_angle_array < 0) + 2*pi;
        
        relative_optimal_orientation_array_shifted(i, :) = shifted_angle_array;
    end

    if plot_results
        for i = 1:num_radars
            figure;
            scatter(real(relative_optimal_position_array_shifted(i, :)), imag(relative_optimal_position_array_shifted(i, :)), [], c, "filled");
            hold on;
        
            U_new = 5*cos(relative_optimal_orientation_array_shifted(i, :));
            V_new = 5*sin(relative_optimal_orientation_array_shifted(i, :));
            quiver(real(relative_optimal_position_array_shifted(i, :)), imag(relative_optimal_position_array_shifted(i, :)), U_new, V_new, "off", "black");
            
            for j=1:num_radars
                text_string = sprintf("Radar %d", j);
                text(real(relative_optimal_position_array_shifted(i, j))-2, imag(relative_optimal_position_array_shifted(i, j))-3, text_string, 'FontSize', 8);
            end
    
            hold off;
            legend("Radar_i relative position", "Radar_i relative orientation");
            xlabel("X-Axis");
            ylabel("Y-Axis");
            title(["Relative Radar Data for Radar ", num2str(i), "shifted to Radar ", num2str(ref_radar_index), " coordinate system"]);
            %axis([-30 70 -50 50]);
            grid on;
        end
    end
end