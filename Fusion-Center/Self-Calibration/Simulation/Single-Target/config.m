% Set the configurations of the experiment
% 1. Num of radars
% 2. Num of targets
% 3. num of iterations

num_radars = 2;
num_targets = 1;
quantized_angle_degrees = 1;

load("../mmwave-data-for-anirban/Exp1/Exp1_R1_Az.mat");
load("../mmwave-data-for-anirban/Exp1/Exp1_R1_Range.mat");

az_rad_arr = zeros([num_radars length(az)]);
range_arr = zeros([num_radars length(range)]);

az_rad_arr(1, :) = deg2rad(az);
range_arr(1, :) = range;

load("../mmwave-data-for-anirban/Exp1/Exp1_R2_Az.mat");
load("../mmwave-data-for-anirban/Exp1/Exp1_R2_Range.mat")

az_rad_arr(2, :) = deg2rad(az);
range_arr(2, :) = range;

num_iterations = length(az);

clear az range;

% Get the position and the orientation info of the two radars
radar_position_array = [0 4.8; 
                        0 4.9];

complex_radar_position_array = complex(radar_position_array(1, :), radar_position_array(2, :));

radar_orientation_array = [0 90];

% Get the polar to cartesian coordinates of the target trajectory_estimate
% for both the radars
complex_trajectory_estimate_array = zeros([num_radars, num_iterations]);

for index=1:num_radars
    [x, y] = pol2cart(az_rad_arr(index, :), range_arr(index, :));
    complex_trajectory_estimate_array(index, :) = complex(x, y);
    clear x y;
end
