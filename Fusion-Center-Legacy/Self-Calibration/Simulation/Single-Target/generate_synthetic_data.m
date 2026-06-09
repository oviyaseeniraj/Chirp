% Set the configurations of the experiment
% 1. Num of radars
% 2. Num of targets
% 3. num of iterations

num_radars = 4;
num_targets = 1;
quantized_angle_degrees = 1;
num_iterations = 100;
initial_target_position = 20+ 1j*40;

complex_trajectory_array = get_synthetic_trajectory(initial_target_position, ...
                                                    0, -1, num_iterations);

% Get the position and the orientation info of the four radars
radar_position_array = [0 40 40 0; 
                        -20 -20 20 20];
radar_orientation_array = [45 135 225 315];

complex_radar_position_array = complex(radar_position_array(1, :), ...
                                       radar_position_array(2, :));

% Get the polar to cartesian coordinates of the target trajectory_estimate
% for both the radars
complex_trajectory_estimate_array = zeros([num_radars, num_iterations]);


for index=1:num_radars
    angle_rad = deg2rad(radar_orientation_array(index));
    angle_correction = exp(-1j*angle_rad);
    for t=1:num_iterations
        complex_trajectory_estimate_array(index, t) = (complex_trajectory_array(t) - complex_radar_position_array(index))*angle_correction;
        noise = complex(0.5*randn, 0.5*randn);
        complex_trajectory_estimate_array(index, t) = complex_trajectory_estimate_array(index, t) + noise;
    end
end

%==========================================================================
% Plot Ground Truth Data
figure;
plot(real(complex_trajectory_array(:)), imag(complex_trajectory_array(:)), "blue", "LineWidth", 1.5);
hold on;
c = linspace(1, 100, num_radars);
scatter(real(complex_radar_position_array(:)), imag(complex_radar_position_array(:)), [], c, "filled");

for index=1:num_radars
    text_string = sprintf("Radar %d", index);
    text(real(complex_radar_position_array(index))-2, imag(complex_radar_position_array(index))-3, text_string, 'FontSize', 10);
end

U = 12*cos(deg2rad(radar_orientation_array(:)));
V = 12*sin(deg2rad(radar_orientation_array(:)));
quiver(real(complex_radar_position_array(:)), imag(complex_radar_position_array(:)), U, V, "off", "black");

% Draw rectangle signifying overlapping FOV
plot_radar_position_array = [radar_position_array(1, :) radar_position_array(1, 1); 
                             radar_position_array(2, :) radar_position_array(2, 1)];
plot(plot_radar_position_array(1, :), plot_radar_position_array(2, :), 'r-');

text_pos_x = max(radar_position_array(1, :));
text_pos_y = mean(radar_position_array(2, :));

text(text_pos_x+0.5, text_pos_y, 'Overlapping FOV', 'FontSize', 10);

text(real(initial_target_position)+2, imag(initial_target_position)-3, 'Target Trajectory', 'FontSize', 10);

hold off;
legend("Target Trajectory", "Radar_i position", "Radar_i orientation");
xlabel("X-Axis");
ylabel("Y-Axis");
title("Actual Ground Truth Data");
axis([-20 60 -50 50]);
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