num_radars = 2;
num_targets = 4; % Num of Targets tracked by each radar
num_targets_in_overlapping_fov = 3;
num_iterations = 100;
initial_target_2_position = 5 + 1j*5;
initial_target_1_position = 35 + 1j*15;

initial_target_position = 20 + 1j*15;

% Get the radar positions and orientations
radar_position_array = [10 30; 
                        10 10];

radar_orientation_array = [0 180];

complex_radar_position_array = complex(radar_position_array(1, :), ...
                                       radar_position_array(2, :));

complex_trajectory_array = zeros([num_targets num_iterations]);
complex_trajectory_array_out_of_fov = zeros([num_radars num_iterations]); % 1 per radar


% Populate the complex trajectory array for Targets in the overlapping FOV
for target=1:num_targets_in_overlapping_fov
    complex_trajectory_array(target, :) = get_synthetic_trajectory(initial_target_position, ...
                                                      0, -1, ...
                                                      num_iterations);
end

complex_trajectory_array_out_of_fov(1, :) = get_synthetic_trajectory(initial_target_1_position, ...
                                                      0, -1, ...
                                                      num_iterations);

complex_trajectory_array_out_of_fov(2, :) = get_synthetic_trajectory(initial_target_2_position, ...
                                                      0, 1, ...
                                                      num_iterations);

complex_trajectory_estimate_array = zeros([num_radars*num_targets, num_iterations]);

%--------------------------------------------------------------------------
% Get target estimate array for N radars and M targets
% Row 1 to M -> Target estimates wrt Radar 1
% Row M+1 to 2M -> Target estimates wrt Radar 2, and so on.
shift=0;
for index = 1:num_radars
    % Get the complex trajectory estimate for the two radars
    angle_correction = exp(-1j*deg2rad(radar_orientation_array(index)));
    
    % First populate for the overlapping FOV targets
    for target=1:num_targets_in_overlapping_fov

        for t=1:num_iterations
            complex_trajectory_estimate_array((target+index+shift-1), t) = (complex_trajectory_array(target, t) - complex_radar_position_array(index))*angle_correction;
            noise = complex(2*randn, 2*randn);
            complex_trajectory_estimate_array((target+index+shift-1), t) = complex_trajectory_estimate_array((target+index+shift-1), t) + noise;
        end
    end

    % Now populate for the out of FOV targets
    for t=1:num_iterations
        complex_trajectory_estimate_array((index*num_targets), t) = (complex_trajectory_array_out_of_fov(index, t) - complex_radar_position_array(index))*angle_correction;
        noise = complex(2*randn, 2*randn);
        complex_trajectory_estimate_array((index*num_targets), t) = complex_trajectory_estimate_array((index*num_targets), t) + noise;
    end

    % Shift by num targets
    shift = shift + num_targets-1;
end

%==========================================================================
% Plot Ground Truth Data
figure;
hold on;

colour = [sprintf("green"), sprintf("blue"), sprintf("red")];
trajectories_legend = [];
for target=1:num_targets_in_overlapping_fov
    plot(real(complex_trajectory_array(target, :)), imag(complex_trajectory_array(target, :)), colour(target), "LineWidth", 1.5);
    trajectories_legend = [trajectories_legend sprintf("Target Trajectory %d in Overlapping FOV", target)];
end

colour_out_of_fov = [sprintf("magenta"), sprintf("cyan")];
trajectories_legend_out_of_fov = [];
for index=1:num_radars
    plot(real(complex_trajectory_array_out_of_fov(index, :)), imag(complex_trajectory_array_out_of_fov(index, :)), colour_out_of_fov(index), "LineWidth", 1.5);
    trajectories_legend_out_of_fov = [trajectories_legend_out_of_fov sprintf("Target Trajectory %d for Radar %d", num_targets, index)];
end
c = linspace(1, 100, num_radars);
radar_legend = [];
for index=1:num_radars
    scatter(real(complex_radar_position_array(index)), imag(complex_radar_position_array(index)), [], colour_out_of_fov(index), "filled");
    radar_legend = [radar_legend sprintf("Radar %d position", index)];
end

for index=1:num_radars
    text_string = sprintf("Radar %d", index);
    text(real(complex_radar_position_array(index))-1, imag(complex_radar_position_array(index))-2, text_string, 'FontSize', 7);
end

U = 4*cos(deg2rad(radar_orientation_array(:)));
V = 4*sin(deg2rad(radar_orientation_array(:)));
quiver(real(complex_radar_position_array(:)), imag(complex_radar_position_array(:)), U, V, "off", "black");

hold off;
legend([trajectories_legend, trajectories_legend_out_of_fov, radar_legend, "Radar_i orientation"]);
xlabel("X-Axis");
ylabel("Y-Axis");
title("Actual Ground Truth Data");
axis([-10 40 -20 40]);
grid on;

%==========================================================================
% Function to get Target synthetic trajectory

function [complex_trajectory_array] = get_synthetic_trajectory(initial_target_position, ...
                                      vel_x_max, vel_y_max, num_iterations)
    new_target_position = initial_target_position;

    complex_trajectory_array = zeros([1 num_iterations]);

    for t = 1:num_iterations
        z_t = trajectory_formation(new_target_position, vel_x_max, vel_y_max);
        complex_trajectory_array(t) = z_t;
        new_target_position = z_t;
    end
end

%==========================================================================
% Function for getting the trajectory formation of the target

function [complex_new_position] = trajectory_formation(complex_initial_position, vel_x_max, vel_y_max)

    delta_x = 2*rand;
    delta_y = 2*rand;
    max_x_velocity = vel_x_max;
    max_y_velocity = vel_y_max;
    complex_axial_velocity = complex(delta_x*max_x_velocity, delta_y*max_y_velocity);
    complex_new_position = complex_initial_position + complex_axial_velocity;

    noise = complex(0.5*randn, 0.5*randn);
    complex_new_position = complex_new_position + noise;
end