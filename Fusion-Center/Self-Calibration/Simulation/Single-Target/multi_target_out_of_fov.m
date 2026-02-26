num_radars = 2;
num_targets = 2;
num_iterations = 10;
initial_target_2_position = 5 + 1j*5;
initial_target_1_position = 25 + 1j*15;

% Get the radar positions and orientations
radar_position_array = [10 20; 
                        10 10];

radar_orientation_array = [0 180];

complex_radar_position_array = complex(radar_position_array(1, :), ...
                                       radar_position_array(2, :));

complex_trajectory_array = zeros([num_targets num_iterations]);

complex_trajectory_array(1, :) = get_synthetic_trajectory(initial_target_1_position, ...
                                                      0, -1, ...
                                                      num_iterations);

complex_trajectory_array(2, :) = get_synthetic_trajectory(initial_target_2_position, ...
                                                      0, 1, ...
                                                      num_iterations);

complex_trajectory_estimate_array = zeros([num_radars, num_iterations]);

% Get the complex trajectory estimate for the two radars
angle_correction = exp(-1j*deg2rad(radar_orientation_array(1)));
for t=1:num_iterations
    complex_trajectory_estimate_array(1, t) = (complex_trajectory_array(1, t) - complex_radar_position_array(1))*angle_correction;
end

angle_correction = exp(-1j*deg2rad(radar_orientation_array(2)));
for t=1:num_iterations
    complex_trajectory_estimate_array(2, t) = (complex_trajectory_array(2, t) - complex_radar_position_array(2))*angle_correction;
end

%==========================================================================
% Plot Ground Truth Data
figure;
hold on;
colour = rand([num_targets 3]);
trajectories_legend = [];
for target=1:num_targets
    col = [colour(target, :)];
    plot(real(complex_trajectory_array(target, :)), imag(complex_trajectory_array(target, :)), "Color", col, "LineWidth", 1.5);
    trajectories_legend = [trajectories_legend sprintf("Target Trajectory %d", target)];
end
c = linspace(1, 100, num_radars);
scatter(real(complex_radar_position_array(:)), imag(complex_radar_position_array(:)), [], c, "filled");

for index=1:num_radars
    text_string = sprintf("Radar %d", index);
    text(real(complex_radar_position_array(index))-2, imag(complex_radar_position_array(index))-3, text_string, 'FontSize', 7);
end

U = 4*cos(deg2rad(radar_orientation_array(:)));
V = 4*sin(deg2rad(radar_orientation_array(:)));
quiver(real(complex_radar_position_array(:)), imag(complex_radar_position_array(:)), U, V, "off", "black");

hold off;
legend([trajectories_legend, "Radar_i position", "Radar_i orientation"]);
xlabel("X-Axis");
ylabel("Y-Axis");
title("Actual Ground Truth Data");
axis([-10 40 -5 20]);
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

    delta_x = 1;
    delta_y = 1;
    max_x_velocity = vel_x_max;
    max_y_velocity = vel_y_max;
    complex_axial_velocity = complex(delta_x*max_x_velocity, delta_y*max_y_velocity);
    complex_new_position = complex_initial_position + complex_axial_velocity;

    noise = complex(randn, randn);
    complex_new_position = complex_new_position + noise;
end