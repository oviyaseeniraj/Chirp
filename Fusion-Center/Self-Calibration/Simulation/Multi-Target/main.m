% Call two radar two target configuration script
two_radar_two_target_out_of_fov;

% Get closed form solution
[P_array, theta_array, P_optimal_array, theta_optimal_array, residual_array] = get_closed_form_value(complex_radar_position_array, ...
    radar_orientation_array, complex_trajectory_estimate_array, num_radars, num_iterations);

%==========================================================================
% Plot averaged relative calibration results for Multi-Radar Network

[P_optimal_avg_array, theta_optimal_avg_array] = get_averaged_calibration(num_radars, P_optimal_array, theta_optimal_array);


%==========================================================================
radar_0_index = 1;
% Get the complex_shifted_trajectory_estimate w.r.t Radar 0 = 1
complex_shifted_trajectory_estimate_array = zeros([num_radars num_iterations]);
complex_shifted_trajectory_estimate_array(1, :) = complex_trajectory_estimate_array(1, :);
complex_shifted_trajectory_estimate_array(2, :) = (complex_trajectory_estimate_array(2, :)-P_optimal_avg_array(2, 1))*exp(-1j*deg2rad(theta_optimal_avg_array(2, 1)));

%==========================================================================
% Plot relative calibration results with target-association
figure;
hold on;
trajectories_legend = [];
radar_legend = [];
for index = 1:num_radars
    plot(real(complex_shifted_trajectory_estimate_array(index, :)), ...
         imag(complex_shifted_trajectory_estimate_array(index, :)), colour(index), "LineWidth", 1.5);
    
    trajectories_legend = [trajectories_legend sprintf("Target Trajectory %d Estimate wrt Ref Radar", index)];
end

for index=1:num_radars
    scatter(real(P_array(radar_0_index, index)), imag(P_array(radar_0_index, index)), ...
            colour(index), "filled");

    radar_legend = [radar_legend sprintf("Radar %d Actual Relative Position wrt Ref Radar", index)];

end

scatter(real(P_optimal_avg_array(radar_0_index, :)), imag(P_optimal_avg_array(radar_0_index, :)), ...
            180, "red", "X");

U = 4*cos(deg2rad(theta_array(radar_0_index, :)));
V = 4*sin(deg2rad(theta_array(radar_0_index, :)));

quiver(real(P_array(radar_0_index, :)), imag(P_array(radar_0_index, :)), U, V, "off", "black");

U_new = 5*cos(deg2rad(theta_optimal_avg_array(radar_0_index, :)));
V_new = 5*sin(deg2rad(theta_optimal_avg_array(radar_0_index, :)));

quiver(real(P_optimal_avg_array(radar_0_index, :)), imag(P_optimal_avg_array(radar_0_index, :)), ...
       U_new, V_new, "off", "magenta");

%{
theta_legend = [];
for index=1:num_radars
    U = 4*cos(deg2rad(theta_array(radar_0_index, index)));
    V = 4*sin(deg2rad(theta_array(radar_0_index, index)));
    
    quiver(real(P_array(radar_0_index, index)), imag(P_array(radar_0_index, index)), U, V, "off", colour(index));
    
    theta_legend = [theta_legend sprintf("Radar %d Actual Relative Orientation wrt Ref Radar", index)];

    U_new = 5*cos(deg2rad(theta_optimal_avg_array(radar_0_index, index)));
    V_new = 5*sin(deg2rad(theta_optimal_avg_array(radar_0_index, index)));
    
    quiver(real(P_optimal_array(radar_0_index, index)), imag(P_optimal_array(radar_0_index, index)), ...
           U_new, V_new, "off", colour(index));

    theta_legend = [theta_legend sprintf("Averaged Radar %d Optimal Relative Orientation wrt Ref Radar", index)];

end
%}


for index=1:num_radars
    text_string = sprintf("Radar %d", index);
    text(real(P_optimal_array(radar_0_index, index)), ...
         imag(P_optimal_array(radar_0_index, index))+1.5, ...
         text_string, 'FontSize', 8);
end

hold off;
legend([trajectories_legend, radar_legend, ...
       "Averaged Radar_i Optimal Relative Position wrt Ref Radar", ...
       "Radar_i Actual Relative Orientation wrt Ref Radar", ...
       "Averaged Radar_i Optimal Relative Orientation wrt Ref Radar"]);
        
xlabel("X-Axis");
ylabel("Y-Axis");
title("Relative Averaged Calibration Data for Ref Radar ", num2str(radar_0_index));
grid on;
axis([-5 25 -20 20]);