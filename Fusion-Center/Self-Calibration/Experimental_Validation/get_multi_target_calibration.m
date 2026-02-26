% FUNCTION - get_multi_target_calibration
% Get multi-target calibration result for a two radar setup

function [relative_position, relative_orientation, track_mapping, normalized_residual_value] = get_multi_target_calibration(trajectory_combination_dict)
    track_combinations = keys(trajectory_combination_dict);


    residual_dict_unfiltered = dictionary;
    relative_position_dict_unfiltered = dictionary;
    relative_orientation_dict_unfiltered = dictionary;

    radar_1_track_list = [];
    radar_2_track_list = [];

    for track_combination_idx = 1:length(track_combinations)
        track_combination = track_combinations(track_combination_idx);

        track_combination_array = cell2mat(track_combination);

        radar_1_track = track_combination_array(1);
        radar_2_track = track_combination_array(2);

        radar_1_track_list = [radar_1_track_list radar_1_track];
        radar_2_track_list = [radar_2_track_list radar_2_track];

        complex_trajectory_estimate_array = cell2mat(lookup(trajectory_combination_dict, ...
                                                     track_combination));

        trajectory_size = size(complex_trajectory_estimate_array);
        num_radars = trajectory_size(1);
        num_iterations = trajectory_size(2);
    
        [P_optimal_array, theta_optimal_array, residual_array] = get_closed_form_solution(complex_trajectory_estimate_array, ...
                                               num_radars, num_iterations);

        % Get normalized residual value
        residual_array = residual_array/num_iterations;

        % TO-DO Weight the residuals with the number of iterations(frames)
        % (May not be required)
        residual_dict_unfiltered({[radar_1_track, radar_2_track]}) = max(residual_array(:));
        relative_position_dict_unfiltered({[radar_1_track, radar_2_track]}) = P_optimal_array(1, 2);
        relative_orientation_dict_unfiltered({[radar_1_track, radar_2_track]}) = theta_optimal_array(1, 2);
    end

    % Get the number of unique tracks for radar 1 and radar 2
    num_tracks_radar_1 = numel(unique(radar_1_track_list));
    num_tracks_radar_2 = numel(unique(radar_2_track_list));

    max_num_overlapping_tracks = min(num_tracks_radar_1, num_tracks_radar_2);

    % Get the smallest num_target items in the residual dict
    [relative_position_dict, relative_orientation_dict, residual_dict] = get_n_min_filtered_tracks(relative_position_dict_unfiltered, ...
                                  relative_orientation_dict_unfiltered, ...
                                  residual_dict_unfiltered, ...
                                  max_num_overlapping_tracks);

    if max_num_overlapping_tracks > 1
        [pose_cluster_dict, min_mean_residual_value, min_mean_residual_cluster_index] = get_radar_pose_clustering(relative_position_dict, ...
                           relative_orientation_dict, residual_dict, false);

        cluster_labels = keys(pose_cluster_dict);
        min_mean_residual_cluster_label = cluster_labels(min_mean_residual_cluster_index);

        cluster_info_dict = pose_cluster_dict(min_mean_residual_cluster_label);
        relative_position = cell2mat(cluster_info_dict('Mean Relative Position'));
        relative_orientation = cell2mat(cluster_info_dict('Mean Relative Orientation'));
        track_mapping = cluster_info_dict('Track Mapping');
        track_mapping = track_mapping{1}';
        normalized_residual_value = min_mean_residual_value;
    else
        relative_position = values(relative_position_dict);
        relative_orientation = values(relative_orientation_dict);
        track_mapping = keys(residual_dict);
        normalized_residual_value = values(residual_dict);
    end

end

%==========================================================================
% FUNCTION - get_n_min_filtered_tracks
% Get the track combinations which yield the N-min residuals 
%==========================================================================
function [relative_position_dict_filtered, relative_orientation_dict_filtered, residual_dict_filtered] = get_n_min_filtered_tracks(relative_position_dict_unfiltered, ...
            relative_orientation_dict_unfiltered, residual_dict_unfiltered, ...
            max_num_overlapping_tracks)

    relative_position_dict_filtered = dictionary;
    relative_orientation_dict_filtered = dictionary;
    residual_dict_filtered = dictionary;

    % Get the smallest num_target items in the residual dict
    residual_values_arr = values(residual_dict_unfiltered);
    residual_keys_arr = keys(residual_dict_unfiltered);
    [~, filtered_residual_indices_arr] = mink(residual_values_arr, max_num_overlapping_tracks);
    
    for index=1:numel(filtered_residual_indices_arr)
        key = residual_keys_arr(filtered_residual_indices_arr(index));
        residual_dict_filtered(key) = residual_dict_unfiltered(key);
        relative_position_dict_filtered(key) = relative_position_dict_unfiltered(key);
        relative_orientation_dict_filtered(key) = relative_orientation_dict_unfiltered(key);
    end
end


%==========================================================================
% FUNCTION - get_radar_pose_clustering
% Further filtering tracks based on DBSCAN based radar pose clustering
%==========================================================================
function [pose_cluster_dict, min_mean_residual_value, min_mean_residual_cluster_index] = get_radar_pose_clustering(relative_position_dict, ...
                                             relative_orientation_dict, ...
                                             residual_dict, plotting)

    relative_pos_array = [real(values(relative_position_dict)) imag(values(relative_position_dict))];
    relative_orientation_array = values(relative_orientation_dict);

    % Take min number of points to form a cluster = 2
    minpts = 2;
    
    % Sensitive to epsilon
    if minpts < size(relative_pos_array, 1)
        epsilon = get_epsilon_value(relative_pos_array, minpts);
    else
        % Epsilon value = distance between points
        epsilon = pdist2(relative_pos_array(1, :), ...
                         relative_pos_array(2, :));
    end
    
    % DBSCAN clustering
    [idx_pos, ~] = dbscan(relative_pos_array, epsilon, minpts);

    if minpts < size(relative_orientation_array, 1)
        epsilon = get_epsilon_value(relative_orientation_array, minpts);
    else
        % Epsilon value = distance between points
        epsilon = pdist2(relative_orientation_array(1, :), ...
                         relative_orientation_array(2, :));
    end
    
    % DBSCAN clustering
    [idx_orientation, ~] = dbscan(relative_pos_array, epsilon, minpts);

    % Get the common indices, which are part of the same cluster
    idx = idx_pos((idx_pos == idx_orientation) & (idx_pos ~= -1));
    
    % cluster_arr = idx.*corepts;
    
    if plotting
        % Plot clustering results
        figure;
        num_groups = length(unique(idx));
        gscatter(relative_pos_array(:, 1), relative_pos_array(:, 2), ...
                 idx, hsv(num_groups));
        xlabel("X-Axis");
        ylabel("Y-Axis");
        title("Relative Calibration Clusters of Radar 2 w.r.t Radar 1");
        annotation('ellipse',[0.48 0.48 .07 .07],'Color','black')
        axis([5 35 -20 20]);
        grid on;
    end

    % Populate the Pose Cluster Dictionary

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

            cluster_track_mappings = track_mapping_array(idx == unique_labels(i));
            label_track_mappings = [label_track_mappings; cluster_track_mappings'];

            dict = dictionary;
            dict = insert(dict, 'Mean Residual', {label_residuals(j)});
            dict = insert(dict, 'Mean Relative Position', {label_positions(j)});
            dict = insert(dict, 'Mean Relative Orientation', {label_orientations(j)});
            dict = insert(dict, 'Track Mapping', {label_track_mappings});

            pose_cluster_dict = insert(pose_cluster_dict, unique_labels(i), dict);
            j = j + 1;
        end
    end

    % Get the cluster with the minimum mean residual value
    [min_mean_residual_value, min_mean_residual_cluster_index] = min(label_residuals);
end

%==========================================================================
% FUNCTION : get_epsilon_value
%==========================================================================

%{
function epsilon = get_epsilon_value(points, minpts)
    % Initialize distance matrix
    kthDistances = pdist2(points, points, 'euc', 'Smallest', minpts);

    % Compute Epsilon (ε) Using Statistical Heuristics
    epsilon_mean_std = mean(kthDistances) + 1.5 * std(kthDistances);
    disp(['Recommended Epsilon (Mean + 1.5*StdDev): ', num2str(epsilon_mean_std(1))]);
    
    % Compute Epsilon (ε) Using Percentile-Based Selection
    epsilon_percentile = prctile(kthDistances, 95); % 95th percentile
    disp(['Recommended Epsilon - Percentile : ', epsilon_percentile]);

    epsilon = epsilon_mean_std(1);
end
%}

function epsilon = get_epsilon_value(points, minPts)
    % Initialize distance matrix
    n = size(points, 1);
    distance_matrix = zeros(n, n);
    
    for i = 1:n
        for j = 1:n
            distance_matrix(i, j) = pdist2(points(i, :), points(j, :));
        end
    end

    % Step 4: Find k-th Nearest Neighbor Distance (for k = minPts)
    
    kthDistances = zeros(n, 1);

    for i = 1:n
        sortedDistances = sort(distance_matrix(i,:)); % Sort distances for each point
        kthDistances(i) = sortedDistances(minPts+1); % Get k-th nearest neighbor (skip self-distance)
    end

    sortedKDistances = sort(kthDistances);

    % Automatic Elbow Detection Using Second-Order Differences
    differences = diff(sortedKDistances); % First derivative (rate of change)
    secondDifferences = diff(differences); % Second derivative (curvature)

    [~, elbowIndex] = max(secondDifferences); % Find index of maximum curvature
    epsilon_auto = sortedKDistances(elbowIndex); % Optimal epsilon

    %disp(['Automatically Selected Epsilon: ', num2str(epsilon_auto)]);

    % Compute Epsilon (ε) Using Statistical Heuristics
    epsilon_mean_std = mean(kthDistances) + 1.5 * std(kthDistances);
    %disp(['Recommended Epsilon (Mean + 1.5*StdDev): ', num2str(epsilon_mean_std)]);
    
    % Compute Epsilon (ε) Using Percentile-Based Selection
    epsilon_percentile = prctile(kthDistances, 95); % 95th percentile
    %disp(epsilon_percentile);

    epsilon = epsilon_auto;
end