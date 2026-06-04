clear all;
clc;
% Call two radar two target configuration script
%two_radar_multi_target;
two_radar_multi_target_in_out_fov;

% Relative Dictionary results for Radar 2 w.r.t. Radar 1
residual_dict = dictionary;
relative_position_dict = dictionary;
relative_orientation_dict = dictionary;

P_actual_array = [];
theta_actual_array = [];

for radar_1_track=1:num_targets
    for radar_2_track=1:num_targets
        radar_2_track_shifted = radar_2_track+num_targets;
        complex_trajectory_estimate_array_pairwise = zeros([num_radars num_iterations]);
        complex_trajectory_estimate_array_pairwise(1, :) = complex_trajectory_estimate_array(radar_1_track, :);
        complex_trajectory_estimate_array_pairwise(2, :) = complex_trajectory_estimate_array(radar_2_track_shifted, :);

        % Get closed form solution
        [P_array, theta_array, P_optimal_array, theta_optimal_array, residual_array] = get_closed_form_value(complex_radar_position_array, ...
            radar_orientation_array, complex_trajectory_estimate_array_pairwise, num_radars, num_iterations);

        P_actual_array = P_array;
        theta_actual_array = theta_array;
        
        %==========================================================================
        % Plot averaged relative calibration results for Multi-Radar Network
        
        [P_optimal_avg_array, theta_optimal_avg_array] = get_averaged_calibration(num_radars, P_optimal_array, theta_optimal_array);

        disp("Target Track for Radar 1 : "+radar_1_track);
        disp("Target Track for Radar 2 : "+radar_2_track);
        disp("Relative Position of Radar 2 w.r.t Radar 1 : "+P_optimal_avg_array(1, 2));
        disp("Relative Orientation of Radar 2 w.r.t Radar 1 : "+theta_optimal_avg_array(1, 2));
        disp("Residual :"+max(residual_array(:)));

        residual_dict({[radar_1_track, radar_2_track]}) = max(residual_array(:));
        relative_position_dict({[radar_1_track, radar_2_track]}) = P_optimal_avg_array(1, 2);
        relative_orientation_dict({[radar_1_track, radar_2_track]}) = theta_optimal_avg_array(1, 2);
    end
end

residual_dict_unfiltered = residual_dict;
relative_position_dict_unfiltered = relative_position_dict;
relative_orientation_dict_unfiltered = relative_orientation_dict;

residual_dict = dictionary;
relative_position_dict = dictionary;
relative_orientation_dict = dictionary;

% Get the smallest num_target items in the residual dict
residual_values_arr = values(residual_dict_unfiltered);
residual_keys_arr = keys(residual_dict_unfiltered);
[~, filtered_residual_indices_arr] = mink(residual_values_arr, num_targets);

for index=1:numel(filtered_residual_indices_arr)
    key = residual_keys_arr(filtered_residual_indices_arr(index));
    residual_dict(key) = residual_dict_unfiltered(key);
    relative_position_dict(key) = relative_position_dict_unfiltered(key);
    relative_orientation_dict(key) = relative_orientation_dict_unfiltered(key);
end


% DB SCAN
relative_pos_array = [real(values(relative_position_dict)) imag(values(relative_position_dict))];

% Num of dimensions in data = 2, therefore select minpts = 2+1 = 3
minpts = 3;

kD = pdist2(relative_pos_array, relative_pos_array,'euc','Smallest',minpts);
figure;
plot(sort(kD(end,:)));
title('k-distance graph');
xlabel('Points sorted with nearest distances');
ylabel('Nearest distances');
grid on;

% Sensitive to epsilon
epsilon = 0.65;

[idx, corepts] = dbscan(relative_pos_array, epsilon, minpts);

cluster_arr = idx.*corepts;

% Plot clustering results
figure;
num_groups = length(unique(idx));
gscatter(relative_pos_array(:, 1), relative_pos_array(:, 2), idx, hsv(num_groups));
xlabel("X-Axis");
ylabel("Y-Axis");
title("Relative Calibration Clusters of Radar 2 w.r.t Radar 1");
annotation('ellipse',[0.48 0.48 .07 .07],'Color','black')
axis([5 35 -20 20]);
grid on;

%{
%==========================================================================
pose_cluster_dict = dictionary;

    track_mapping_array = keys(residual_dict);
    residual_array = values(residual_dict);
    complex_relative_pos_array = values(relative_position_dict);
    relative_orientation_array = values(relative_orientation_dict);

    unique_labels = unique(idx);
    label_track_mappings = [];
    label_residuals = zeros(length(unique_labels)-1, 1); % -1 to ignore noise
    label_positions = zeros(length(unique_labels)-1, 1);
    label_orientations = zeros(length(unique_labels)-1, 1);

    j = 1;
    for i=1:length(unique_labels)
        if unique_labels(i) ~= -1 % Ignore noise points
            cluster_residuals = residual_array(idx == unique_labels(i));
            label_residuals(j) = mean(cluster_residuals, 1);

            cluster_positions = complex_relative_pos_array(idx == unique_labels(i));
            label_positions(j) = mean(cluster_positions);

            cluster_orientations = relative_orientation_array(idx == unique_labels(i));
            label_orientations(j) = mean(cluster_orientations);

            % TO-DO : Check the track mappings 
            cluster_track_mappings = track_mapping_array(idx == unique_labels(i));
            label_track_mappings = [label_track_mappings; cluster_track_mappings'];

            dict = dictionary;
            dict = insert(dict, 'Mean Residual', label_residuals(j));
            dict = insert(dict, 'Mean Relative Position', label_positions(j));
            dict = insert(dict, 'Mean Relative Orientation', label_orientations(j));
            dict = insert(dict, 'Track Mapping', label_track_mappings);

            pose_cluster_dict = insert(pose_cluster_dict, unique_labels(i), dict);
            j = j + 1;
        end
    end

    % Get the cluster with the minimum mean residual value
    [~, min_mean_residual_cluster_index] = min(label_residuals);
%==========================================================================
%}

% Find the cluster with the max number of points
binc = min(cluster_arr):max(cluster_arr);
counts = hist(cluster_arr,binc);

[~, max_cluster_index] = max(counts);
max_cluster_key = binc(max_cluster_index);

avg_complex_relative_position_arr = [];
avg_relative_orientation_arr = [];

if max_cluster_key ~= 0
    relative_position_arr = values(relative_position_dict);
    relative_orientation_arr = values(relative_orientation_dict);
    
    relative_orientation_arr(relative_orientation_arr < 0) = relative_orientation_arr(relative_orientation_arr < 0) + 360;
    
    for track_mapping=1:numel(cluster_arr)
        if cluster_arr(track_mapping) == max_cluster_key
            avg_complex_relative_position_arr = [avg_complex_relative_position_arr relative_position_arr(track_mapping)];
            avg_relative_orientation_arr = [avg_relative_orientation_arr relative_orientation_arr(track_mapping)];
        end
    end
else
    % Do further thresholding because DBSCAN failed to find clusters
    % Filter out the matchings which have the residual above a certain
    % threshold
    
    threshold = 2e+03; % Subject to change
    
    for radar_1_track=1:num_targets
        for radar_2_track=1:num_targets
            if lookup(residual_dict, {[radar_1_track, radar_2_track]}) > threshold
                disp("Removing track match :"+radar_1_track+" "+radar_2_track);
                residual_dict = remove(residual_dict, {[radar_1_track, radar_2_track]});
                relative_position_dict = remove(relative_position_dict, {[radar_1_track, radar_2_track]});
                relative_orientation_dict = remove(relative_orientation_dict, {[radar_1_track, radar_2_track]});
            end
        end
    end

    % Get the average calibration data
    relative_position_arr = values(relative_position_dict);
    relative_orientation_arr = values(relative_orientation_dict);

    avg_complex_relative_position_arr = relative_position_arr;
    avg_relative_orientation_arr = relative_orientation_arr;
end

avg_complex_relative_position = mean(avg_complex_relative_position_arr);
avg_relative_orientation = mean(avg_relative_orientation_arr);

P_resultant_array = [0+1j*0 avg_complex_relative_position];
theta_resultant_array = [0 avg_relative_orientation];

%==========================================================================
% Plot relative calibration results with target-association

radar_0_index = 1;

figure;
hold on;
radar_legend = [];

for index=1:num_radars
    scatter(real(P_actual_array(radar_0_index, index)), imag(P_actual_array(radar_0_index, index)), ...
            colour(index), "filled");

    radar_legend = [radar_legend sprintf("Radar %d Actual Relative Position wrt Ref Radar", index)];

end

scatter(real(P_resultant_array(:)), imag(P_resultant_array(:)), ...
            180, "red", "X");

U = 4*cos(deg2rad(theta_actual_array(radar_0_index, :)));
V = 4*sin(deg2rad(theta_actual_array(radar_0_index, :)));

quiver(real(P_actual_array(radar_0_index, :)), imag(P_actual_array(radar_0_index, :)), U, V, "off", "black");

U_new = 7*cos(deg2rad(theta_resultant_array(:)));
V_new = 7*sin(deg2rad(theta_resultant_array(:)));

quiver(real(P_resultant_array(:)), imag(P_resultant_array(:)), ...
       U_new, V_new, "off", "magenta");


for index=1:num_radars
    text_string = sprintf("Radar %d", index);
    text(real(P_resultant_array(index)), ...
         imag(P_resultant_array(index))+1.5, ...
         text_string, 'FontSize', 8);
end

hold off;
legend([radar_legend, ...
       "Averaged Radar_i Optimal Relative Position wrt Ref Radar", ...
       "Radar_i Actual Relative Orientation wrt Ref Radar", ...
       "Averaged Radar_i Optimal Relative Orientation wrt Ref Radar"]);
        
xlabel("X-Axis");
ylabel("Y-Axis");
title("Relative Averaged Calibration Data for Ref Radar ", num2str(radar_0_index));
grid on;
axis([-5 25 -20 20]);