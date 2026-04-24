clear; clc;

experiment_name = 'may17_cfg1_radar2_straight_noRangeFT';
%data_path = strcat('D:\Research\Dist-Radar\Radar_Pipeline_Output\Data\Hann\', experiment_name, '_RF_CFAR_Angle.mat');
data_path = strcat('C:\Users\anirb\Downloads\', experiment_name, '_RF_CFAR_Angle.mat');
%data_path = strcat('/Users/lalithagiridhar/Desktop/UCSB/Research/Distributed MIMO Radar/Radar Signal Processing Pipeline w Anirban/New_outputs/Data/Hann/', 'Single_ExpA_R2_noRangeFT_RF_CFAR_Angle.mat');



load(data_path, 'detection_log');

% Use this for selective cases
detectionLog = detection_log;
%detectionLog = detection_log(100:600);

% Set the measurement noise parameters
sigma_azimuth = 30;
sigma_range = 0.035;

measurement_noise = [sigma_azimuth^2 0; 0 sigma_range^2];

for k = 1:numel(detectionLog)
    detections = detectionLog{k};
    for j = 1:numel(detections)
        detections{j}.MeasurementNoise(1:2, 1:2) = measurement_noise;
    end
    detectionLog{k} = detections;
end

num_frames = numel(detection_log);

[TargetTrack] = get_target_tracks(detectionLog);


%==========================================================================
% Tracking parameters
%==========================================================================
min_range_rate = 0.065;
min_power_val = 0;

min_cluster_points = 1000;
max_cluster_points = 0;

% Initialize a JPDA tracker
tracker = trackerJPDA(TrackLogic="Integrated");
tracker.FilterInitializationFcn = @ekf_custom;

% Volume of measurement space
azSpan = 180;
rSpan = 18;
dopplerSpan = 5;
V = azSpan*rSpan*dopplerSpan;

% Setting the Detection parameters

% Number of false alarms per step
nFalse = 5;

% Number of new targets per step
nNew = 0.1;

% Probability of detecting the object
Pd = 0.8;

tracker.ClutterDensity = nFalse/V;
tracker.NewTargetDensity = nNew/V;
tracker.DetectionProbability = Pd;

tracker.InitializationThreshold = 0.01;

%tracker.AssignmentThreshold = 8;

%tracker.ClassFusionMethod = "Bayes";
%tracker.InitialClassProbabilities = [0.96 0.02 0.02];

% Confirm a track with more than 95 percent
% probability of existence
tracker.ConfirmationThreshold = 0.95; 

% Delete a track with less than 0.001
% probability of existence
tracker.DeletionThreshold = 0.015;

tracks = objectTrack.empty(0,1);

% Track dictionary
track_dict = dictionary;

output_video_path = strcat('Videos/', experiment_name, '_Detected_Tracks.avi');
% 
figure();
vw = VideoWriter(output_video_path);
vw.Quality = 100;
vw.FrameRate = 20;
open(vw);

prev_plot_dict = dictionary;

for frame_idx=1:numel(TargetTrack)

    if frame_idx > 64
        disp('64');
    end

    tracks_snapshot = TargetTrack{frame_idx};

    % Normalize the powers
    %tracks_snapshot(:, 4) = normalize_weights(tracks_snapshot(:, 4));

    [is_success, labels, unique_labels, centroids, max_cluster_points, min_cluster_points] = get_clusters(tracks_snapshot, measurement_noise, max_cluster_points, min_cluster_points);

    if is_success == true

        % Get only the centroids which have doppler above bare minimum
        if numel(centroids) > 0
            centroids = get_dynamic_tracks(centroids, min_range_rate);
        end

        if numel(centroids) > 0
            centroid_coordinates = filter_based_on_power(centroids, min_power_val);
            centroids = centroid_coordinates;
        end

        if numel(centroids) > 0
            % Get detection object corresponding to cluster centroids
            detections = get_clustered_detection_object(frame_idx, centroids, ...
                                                        measurement_noise);
    
            % Track centroid returns
            if isLocked(tracker) || ~isempty(detections)
                tracks = tracker(detections, frame_idx);
            end
    
            % Plot for specific frame ids (Currently set to all frames)
            if rem(frame_idx, 1) == 0
                prev_plot_dict = plot_data(prev_plot_dict, tracks_snapshot, ...
                                          centroids, tracks, ...
                                          10, frame_idx, false, true, false);
            end
        end

        track_dict = add_tracks_to_dict(track_dict, tracks, frame_idx);

        Frame = getframe(gcf);
        writeVideo(vw,Frame);
        pause(0.001);
    end
end

hold off;
close(vw);

close all;

output_path = strcat('Data/New_Tracking_Data_May/', experiment_name, '_Track_Dict.mat');
save(output_path, 'track_dict');

output_data_file = strcat(experiment_name, '_detection_data.mat');
save(output_data_file, 'prev_plot_dict');

%==========================================================================
% FUNCTION : normalize_weights
%==========================================================================
function normalized_weight_vector = normalize_weights(weight_vector)

    normalized_weight_vector = weight_vector/sum(weight_vector);
end


%==========================================================================
% FUNCTION : add_tracks_to_dict
%==========================================================================
function track_dict = add_tracks_to_dict(track_dictionary, tracks, frame_idx)

    track_dict = track_dictionary;

    % Track Dictionary format - {Track_ID : {Frame_Idx : [x; y]}}
    for index=1:numel(tracks)
        track_id = tracks(index).TrackID;
        
        if isConfigured(track_dict)
            dict = lookup(track_dict, track_id, "FallbackValue", dictionary);
        else
            dict = dictionary;
        end
        dict = insert(dict, frame_idx, {tracks(index).State});
        track_dict = insert(track_dict, track_id, dict);
    end
end

%==========================================================================
% FUNCTION : plot_tracks
%==========================================================================
function [] = plot_tracks(tracks)

    tp = theaterPlot('XLimits',[0 10],'YLimits',[-10 10]);
    trackP = trackPlotter(tp,'DisplayName','Tracks','MarkerFaceColor','g');

    positionSelector = [1 0 0 0; 0 0 1 0; 0 0 0 0]; % [x, y]
    velocitySelector = [0 1 0 0; 0 0 0 1; 0 0 0 0]; % [vx, vy]

    [pos,cov] = getTrackPositions(tracks, positionSelector);
    vel = getTrackVelocities(tracks, velocitySelector);

    if numel(tracks)>0
        labels = arrayfun(@(x)num2str([x.TrackID]), tracks, 'UniformOutput', false);
        trackP.plotTrack(pos, vel, cov, labels);
    end

    drawnow;
end


%==========================================================================
% FUNCTION : get_clusters
%==========================================================================
function [is_success, labels, unique_labels, centroids, max_cluster_points, min_cluster_points] = get_clusters(tracks_snapshot, measurement_noise, max_cluster_points, min_cluster_points)

    % Get only the tracks which are dynamic
    tracks_coordinate_snapshot = tracks_snapshot;

    if numel(tracks_coordinate_snapshot) > 0

        labels = get_dbscan_clustering(tracks_coordinate_snapshot, diag(flip(diag(measurement_noise))), 1);
        %labels = get_grid_dbscan_clustering(dynamic_tracks_snapshot);
        
        % Find the centroids of the clusters
        unique_labels = unique(labels);
        centroids = zeros(length(unique_labels)-1, 4); % -1 to ignore noise

        j = 1;
        for i=1:length(unique_labels)
            if unique_labels(i) ~= -1 % Ignore noise points
                cluster_points = tracks_snapshot(labels == unique_labels(i), :);
                
                % Weighted Mean of the points in the cluster
                centroids(j, 1:3) = sum(cluster_points(:, 4).*cluster_points(:, 1:3), 1)/sum(cluster_points(:, 4));

                % Update the doppler of the cluster, as the one with the
                % max power
                [max_power_val, ind] = max(cluster_points(:, 4));
                centroids(j, 2) = cluster_points(ind, 2);
                centroids(j, 4) = max_power_val;


                if length(cluster_points(:, 4)) > max_cluster_points
                    max_cluster_points = length(cluster_points(:, 4));
                elseif length(cluster_points(:, 4)) < min_cluster_points
                    min_cluster_points = length(cluster_points(:, 4));
                end
                
                j = j + 1;
            end
        end

        is_success = true;
    else
        is_success = false;
        % Set default values for the return arguments
        labels = [];
        unique_labels = [];
        centroids = [];
    end
end

%==========================================================================
% FUNCTION : get_clustered_detection_object 
%==========================================================================
function detections = get_clustered_detection_object(frame, centroids, measurement_noise)

    detections = {};

    % Set the measurement parameters for detection
    mp = struct(Frame="Spherical", ...
    OriginPosition = zeros(1,3), ...
    OriginVelocity = zeros(1,3), ...
    Orientation = eye(3),...
    HasAzimuth = true,...
    HasElevation = false,...
    HasRange = true,...
    HasVelocity = true,...
    IsParentToChild = true);

    centroids_a_r_d = zeros(size(centroids)); 

    % Re-formatted into azimuth-range-doppler
    centroids_a_r_d(:, 1) = centroids(:, 3);
    centroids_a_r_d(:, 2) = centroids(:, 1);
    centroids_a_r_d(:, 3) = centroids(:, 2);

    measurement_noise_3_3 = eye(3);
    %measurement_noise_3_3(1:2, 1:2) = 4*measurement_noise;
    measurement_noise_3_3(1:2, 1:2) = measurement_noise;
    measurement_noise_3_3(3, 3) = (0.3614)^2;

    for index=1:length(centroids_a_r_d(:, 1))
        detection = objectDetection(frame, centroids_a_r_d(index, :), ...
             MeasurementParameters=mp, MeasurementNoise=measurement_noise_3_3);
        detections(end+1) = {detection};
    end
end

%==========================================================================
% FUNCTION : get_dynamic_tracks
%==========================================================================
function dynamic_tracks_snapshot = get_dynamic_tracks(tracks_snapshot, ...
                                                      min_range_rate)

    dynamic_tracks_snapshot = [];
    for index=1:length(tracks_snapshot(:, 1))
        if abs(tracks_snapshot(index, 2)) > min_range_rate
            dynamic_tracks_snapshot = [dynamic_tracks_snapshot; tracks_snapshot(index, :)];
        end
    end
end

%==========================================================================
% FUNCTION : filter_based_on_power
%==========================================================================
function filtered_tracks_coordinate_snapshot = filter_based_on_power(tracks_snapshot, ...
                                                      min_power_val)
    filtered_tracks_coordinate_snapshot = [];
    for index=1:length(tracks_snapshot(:, 1))
        if tracks_snapshot(index, 4) > min_power_val
            filtered_tracks_coordinate_snapshot = [filtered_tracks_coordinate_snapshot; tracks_snapshot(index, 1:3)];
        end
    end
end

%==========================================================================
% FUNCTION : get_target_tracks
%==========================================================================
function [TargetTrack] = get_target_tracks(detection_log)

    TargetTrack = cell(numel(detection_log), 1);
    
    for i=1:numel(detection_log)
        frame_idx = detection_log{i}{1}.Time;

        detections_per_frame = detection_log{i};

        detection_coordinates = [];

        for index=1:numel(detections_per_frame)
            azimuth = detections_per_frame{index}.Measurement(1);
            range = detections_per_frame{index}.Measurement(2);
            doppler = detections_per_frame{index}.Measurement(3);
            
            % Incorporating power
            power = detections_per_frame{index}.Measurement(4);

            measurement = [range doppler azimuth power];
            detection_coordinates = [detection_coordinates; measurement];
        end

        TargetTrack{frame_idx} = detection_coordinates;
    end
end

%==========================================================================
% FUNCTION : get_dbscan_clustering
% Performs DBSCAN clustering on only the X-Y coordinates of the point cloud
% INPUT - tracks_snapshot - Format - (RANGE, DOPPLER, ANGLE)
%==========================================================================
function labels = get_dbscan_clustering(tracks_snapshot, measurement_noise, ...
                                        distance_metric)
    
    tracks_x = tracks_snapshot(:, 1).*cos(deg2rad(tracks_snapshot(:, 3)));
    tracks_y = tracks_snapshot(:, 1).*sin(deg2rad(tracks_snapshot(:, 3)));
    tracks_snapshot_cartesian = [tracks_x tracks_y];

    tracks_snapshot_ra = [tracks_snapshot(:, 1) tracks_snapshot(:, 3)];

    minPts = 10; % Choose a reasonable value

    % For Debugging

    % Values of epsilon (Need to tune for specific radars)
    % Radar 1 - 0.18/0.23/0.20
    % Radar 2 - 0.75/0.50

    if distance_metric == 1
        epsilon = get_epsilon_value(tracks_snapshot_ra, minPts, measurement_noise, distance_metric);
    elseif distance_metric == 2
        epsilon = get_epsilon_value(tracks_snapshot_cartesian, minPts, measurement_noise, distance_metric);
    end

    epsilon = 3;

    % To be considered in a cluster, minpts must be atleast 2

    if distance_metric == 1
        labels = dbscan(tracks_snapshot_ra, epsilon, minPts, ...
                        'Distance', 'mahalanobis', 'Cov', measurement_noise);
    elseif distance_metric == 2
        labels = dbscan(tracks_snapshot_cartesian, epsilon, minPts, ...
                        'Distance', 'euclidean');
    end
end

%==========================================================================
% FUNCTION : get_epsilon_value
%==========================================================================
function epsilon = get_epsilon_value(points, minPts, cov_matrix, distance_metric)
    % Initialize distance matrix
    n = size(points, 1);
    distance_matrix = zeros(n, n);
    
    if distance_metric == 1
        % Inverse of covariance matrix
        inv_cov_matrix = inv(cov_matrix);
        % Compute pairwise distances
        for i = 1:n
            for j = 1:n
                distance_matrix(i, j) = mahalanobis_distance(points(i, :), points(j, :), inv_cov_matrix);
            end
        end
    elseif distance_metric == 2
        for i = 1:n
            for j = 1:n
                distance_matrix(i, j) = pdist2(points(i, :), points(j, :));
            end
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

%==========================================================================
% FUNCTION : mahalanobis_distance
%==========================================================================
function d = mahalanobis_distance(x, y, inv_cov_matrix)
    delta = x - y;
    d = sqrt(delta * inv_cov_matrix * delta');
end

%==========================================================================
% FUNCTION : plot_data
% Plots the detections, cluster centroids and tracks
% INPUT - detections, centroids, tracks, frame id
%==========================================================================
function [prev_plot_dict] = plot_data(prev_plot_dict, detections, ...
                                      centroids, tracks, ...
                                      history, frame_idx, plot_detections, ...
                                      plot_centroids, plot_tracks)

    % Format of prev_plot_dict
    % {frame_idx : {'detections' : detections, 'centroids' : centroids, 
    %               'tracks' : tracks}

    % Populate data from previous dictionary based on history
    start_frame_idx = frame_idx - history + 1;

    detections_to_plot = [];
    centroids_to_plot = [];
    tracks_to_plot = dictionary;

    % First fill all the data to plot from the history dict
    for idx = start_frame_idx:(frame_idx-1)
        if isConfigured(prev_plot_dict) && idx >= 1
            item = lookup(prev_plot_dict, idx, "FallbackValue", dictionary);
        else
            item = dictionary;
        end
        if isConfigured(item)
            detections_per_frame = cell2mat(lookup(item, 'detections'));
            detections_to_plot = [detections_to_plot; 
                                  detections_per_frame];

            centroids_per_frame = cell2mat(lookup(item, 'centroids'));
            centroids_to_plot = [centroids_to_plot; 
                                 centroids_per_frame];

            tracks_per_frame = lookup(item, 'tracks');
            tracks_per_frame = tracks_per_frame{1};
            tracks_to_plot = add_tracks_to_dict(tracks_to_plot, ...
                                                tracks_per_frame, idx);
        end
    end

    % Now fill all the data to plot from the current frame
    detections_to_plot = [detections_to_plot; detections];
    centroids_to_plot = [centroids_to_plot; centroids];
    tracks_to_plot = add_tracks_to_dict(tracks_to_plot, ...
                                        tracks, frame_idx);

    % Populate new data in prev_plot_dict
    dict = dictionary;
    dict = insert(dict, 'detections', {detections});
    dict = insert(dict, 'centroids', {centroids});
    dict = insert(dict, 'tracks', {tracks});

    prev_plot_dict = insert(prev_plot_dict, frame_idx, dict);

    % Plot all data

    % 1. Detections

    detections_legend = [];
    centroids_legend = [];
    tracks_legend = [];

    if plot_detections
        x_coord_detection = (detections_to_plot(:,1).*cos(deg2rad(detections_to_plot(:,3))));
        y_coord_detection = (detections_to_plot(:,1).*sin(deg2rad(detections_to_plot(:,3))));
    
        for coord_index=1:numel(x_coord_detection)
            scatter(x_coord_detection(coord_index), y_coord_detection(coord_index), 'black');
            hold on;
        end
        detections_legend = sprintf('Detections');
    end

    % 2. Centroids

    if plot_centroids
        x_coord_centroid = (centroids_to_plot(:,1).*cos(deg2rad(centroids_to_plot(:,3))));
        y_coord_centroid = (centroids_to_plot(:,1).*sin(deg2rad(centroids_to_plot(:,3))));
    
        for coord_index=1:numel(x_coord_centroid)
            scatter(x_coord_centroid(coord_index), y_coord_centroid(coord_index), 'red', 'filled');
            hold on;
        end
        centroids_legend = sprintf('Centroids');
    end

    % 3. Tracks

    if plot_tracks
        if isConfigured(tracks_to_plot)
            track_ids_array = keys(tracks_to_plot);
        
            for idx=1:length(track_ids_array)
                track_dict_per_id = tracks_to_plot(track_ids_array(idx));
                frame_ids_array_per_track_id = keys(track_dict_per_id);
        
                x_coord_track = [];
                y_coord_track = [];
        
                for frame_ids_idx=1:length(frame_ids_array_per_track_id)
                    track_per_track_id = cell2mat(track_dict_per_id(frame_ids_array_per_track_id(frame_ids_idx)));
                    x_coord_track = [x_coord_track; track_per_track_id(1)];
                    y_coord_track = [y_coord_track; track_per_track_id(3)];
                end
    
                
                for lineidx=1:(length(x_coord_track)-1)
                    plot([x_coord_track(lineidx) x_coord_track(lineidx+1)], ...
                         [y_coord_track(lineidx) y_coord_track(lineidx+1)],  ...
                         '*');
                    line([x_coord_track(lineidx) x_coord_track(lineidx+1)], ...
                         [y_coord_track(lineidx) y_coord_track(lineidx+1)],  ...
                         'Color', 'blue', 'LineWidth', 2, 'LineStyle', '-');

                    text_string = sprintf('%d', track_ids_array(idx));
                    text(x_coord_track(length(x_coord_track)), ...
                         y_coord_track(length(x_coord_track))+0.25, ...
                         text_string, 'FontSize', 8);
                    hold on;
                end
            end
            tracks_legend = sprintf('Tracks');
        end
    end

    xlabel("X-Axis");
    ylabel("Y-Axis");
    title_string = sprintf('');

    if plot_detections
        title_string = strcat(title_string, ' Detections, ');
    end

    if plot_centroids
        title_string = strcat(title_string, ' Centroids, ');
    end

    if plot_tracks
        title_string = strcat(title_string, ' Tracks, ');
    end

    title_string = strcat(title_string, ' Frame - ', num2str(frame_idx));

    title(title_string);
    grid on;
    %legend(['Detections', 'Centroids', 'Tracks']);
    axis([0 12 -10 10]);

    hold off;
end