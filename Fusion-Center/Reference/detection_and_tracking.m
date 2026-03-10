clear; clc; close all;

experiment_name = 'Exp_Chirp_128_Radar_node_4_adc_data_noRangeFT';
%experiment_name = 'radar_data';
%data_path = strcat('D:\Research\Dist-Radar\Radar_Pipeline_Output\Data\Hann\', experiment_name, '_RF_CFAR_Angle.mat');
data_path = strcat('C:\Users\anirb\Downloads\Radar_Data\', experiment_name, '_RF_CFAR_Angle.mat');

load(data_path, 'detection_log');

% Use this for selective cases
detectionLog = detection_log;
%detectionLog = detection_log(100:600);

% Set the measurement noise parameters
sigma_azimuth = pi/4;
sigma_range = 0.035;
%sigma_doppler = 0.1534; % For 64 chirps per frame
%sigma_doppler = 0.1637; % For 60 chirps per frame
sigma_doppler = 0.0767; % For 128 chirps per frame

measurement_noise = [sigma_range^2 0 0; 0 sigma_doppler^2 0; 0 0 sigma_azimuth^2];

%{
for k = 1:numel(detectionLog)
    detections = detectionLog{k};
    for j = 1:numel(detections)
        detections{j}.MeasurementNoise(1:2, 1:2) = measurement_noise;
    end
    detectionLog{k} = detections;
end
%}

num_frames = numel(detection_log);

[TargetTrack] = get_target_tracks(detectionLog);


%==========================================================================
% Tracking parameters
%==========================================================================
min_range_rate = 0.1;
min_power_val = 0;

min_cluster_points = 1000;
max_cluster_points = 0;

% Track dictionary
track_dict = dictionary;
track_history_dict = dictionary;

output_video_path = strcat('Videos/', experiment_name, '_Detected_Tracks.avi');
% 
figure();
vw = VideoWriter(output_video_path);
vw.Quality = 100;
vw.FrameRate = 20;
open(vw);

prev_plot_dict = dictionary;

for frame_idx=1:numel(TargetTrack)

    tracks_snapshot = TargetTrack{frame_idx};

    fprintf('Frame %d \n', frame_idx);

    if frame_idx == 41
        disp('41');
    end

    % Normalize the powers
    %tracks_snapshot(:, 4) = normalize_weights(tracks_snapshot(:, 4));

    [is_success, labels, unique_labels, centroids] = get_clusters(tracks_snapshot, measurement_noise);

    if is_success == true

        % Get only the centroids which have doppler above bare minimum
        if numel(centroids) > 0
            centroids = get_dynamic_tracks(centroids, min_range_rate);
            tracks_snapshot = get_dynamic_tracks(tracks_snapshot, min_range_rate);
        end

        centroids_omega_r_d = zeros(size(centroids)); 

        if ~isempty(centroids)
            % Re-formatted into omega-range-doppler
            centroids_omega_r_d(:, 1) = pi*sind(centroids(:, 3));
            centroids_omega_r_d(:, 2) = centroids(:, 1);
            centroids_omega_r_d(:, 3) = centroids(:, 2);
        end
    
        % Track centroid returns
        [confirmed_tracks, tentative_tracks, track_history_dict] = get_tracks_from_detections_jpda(centroids_omega_r_d, frame_idx, track_history_dict);
    
        % Plot for specific frame ids (Currently set to all frames)
        if rem(frame_idx, 1) == 0
            prev_plot_dict = plot_data(prev_plot_dict, tracks_snapshot, ...
                                      centroids, confirmed_tracks, ...
                                      1, frame_idx, false, true, false);
        end

        track_dict = add_tracks_to_dict(track_dict, confirmed_tracks, frame_idx);

        Frame = getframe(gcf);
        writeVideo(vw,Frame);
        pause(0.001);
    end
end

hold off;
close(vw);

close all;

output_path = strcat('Data/New_Tracking_Data_Feb_2026/', experiment_name, '_Track_Dict.mat');
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
% FUNCTION : get_clusters
%==========================================================================
function [is_success, labels, unique_labels, centroids] = get_clusters(tracks_snapshot, measurement_noise)

    % Get only the tracks which are dynamic
    tracks_coordinate_snapshot = tracks_snapshot;

    if numel(tracks_coordinate_snapshot) > 0

        labels = get_dbscan_clustering(tracks_coordinate_snapshot, measurement_noise);
        %labels = get_grid_dbscan_clustering(dynamic_tracks_snapshot);
        
        % Find the centroids of the clusters
        unique_labels = unique(labels);
        centroids = zeros(length(unique_labels)-1, 3); % -1 to ignore noise

        j = 1;
        for i=1:length(unique_labels)
            if unique_labels(i) ~= -1 % Ignore noise points
                cluster_points = tracks_snapshot(labels == unique_labels(i), :);
                
                % Weighted Mean of the points in the cluster
                centroids(j, 1:3) = sum(cluster_points(:, 4).*cluster_points(:, 1:3), 1)/sum(cluster_points(:, 4));

                % Update the doppler of the cluster, as the one with the
                % max power
                [~, ind] = max(cluster_points(:, 4));
                centroids(j, 2) = cluster_points(ind, 2);

                if abs(centroids(j, 2)) > 0
                    % Only display centroids with non-zero Doppler
                    fprintf('Centroid using Method 1: Range - %0.5f m, Doppler - %0.5f m/s, Angle - %0.5f degrees \n', ...
                            centroids(j, 1), centroids(j, 2), centroids(j, 3));
                end

                centroids(j, :) = get_cluster_centroid_simple(cluster_points);

                if abs(centroids(j, 2)) > 0
                    fprintf('Centroid using Method 2: Range - %0.5f m, Doppler - %0.5f m/s, Angle - %0.5f degrees \n', ...
                            centroids(j, 1), centroids(j, 2), centroids(j, 3));
                end

                if abs(centroids(j, 2)) <= 0.1637
                    disp(centroids(j, 2));
                    disp('Debug Doppler');
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
% get_cluster_centroid
% cluster - [range, doppler, angle, power]
% opts - Options struct
% -----------------------
%   .k_trim            (default: 2.0)    % trim width in robust-sigma
%   .alpha_w           (default: 0.75)   % weight exponent
%==========================================================================
function [centroid] = get_cluster_centroid(cluster, opts)

    if nargin < 3, opts = struct; end

    opts = set_default(opts, 'k_trim', 2.0);
    opts = set_default(opts, 'alpha_w', 0.75);

    cluster_range = cluster(:, 1);
    cluster_doppler = cluster(:, 2);
    cluster_angle = cluster(:, 3);
    cluster_power = 10.^(cluster(:, 4)/10);
    %  Sub-Linear, builds robustness
    cluster_power_robust = cluster_power.^opts.alpha_w + eps;

    N = length(cluster_power);

    % 1) Robust spread (MAD) and trim around v_median
    median_doppler = weighted_median(cluster_doppler, cluster_power_robust);
    MAD_doppler = median(abs(cluster_doppler - median_doppler));
    rob_sig = 1.4826 * (MAD_doppler + eps);  % std-like
    keep = abs(cluster_doppler - median_doppler) <= opts.k_trim * max(rob_sig, eps);

    % Fallback
    if numel(keep) == 0
        keep = true(size(cluster_doppler));
    end
    
    cluster_range_trimmed = cluster_range(keep); 
    cluster_angle_trimmed = cluster_angle(keep); 
    cluster_doppler_trimmed = cluster_doppler(keep); 
    cluster_power_robust_trimmed = cluster_power_robust(keep);

    weights = cluster_power_robust_trimmed;

    % 4) Weighted centroid
    centroid_range = sum(weights .* cluster_range_trimmed) / sum(weights);
    
    C = sum(weights .* cosd(cluster_angle_trimmed));
    S = sum(weights .* sind(cluster_angle_trimmed));
    centroid_angle = atan2d(S, C);
    
    % Doppler: weighted median inside kept set (robust)
    centroid_doppler = weighted_median(cluster_doppler_trimmed, weights);

    centroid(:, 1) = centroid_range;
    centroid(:, 2) = centroid_doppler;
    centroid(:, 3) = centroid_angle;
end

%==========================================================================
% Weighted Centroid Simplified function
%==========================================================================
function centroid = get_cluster_centroid_simple(cluster, alpha)
% cluster: [range, doppler, angle_deg, power_db]
% alpha: 0.3–0.8 typical (0.5 is a good default)

    if nargin < 2 || isempty(alpha), alpha = 0.75; end

    r  = cluster(:,1);
    d  = cluster(:,2);
    th = cluster(:,3);
    p_db = cluster(:,4);

    % dB -> linear power weights (robustly compressed)
    w = (10.^(p_db/10)).^alpha + eps;

    % Range: weighted mean
    centroid_range = sum(w .* r) / sum(w);

    % Angle: circular weighted mean (degrees)
    C = sum(w .* cosd(th));
    S = sum(w .* sind(th));
    centroid_angle = atan2d(S, C);

    % Doppler: weighted median (robust for humans)
    centroid_doppler = weighted_median(d, w);

    centroid = [centroid_range, centroid_doppler, centroid_angle];

    %{
    if abs(centroid_doppler) <= 0.1637 && abs(centroid_doppler) > 0
        disp('Debug Doppler');
    end
    %}
end


%==========================================================================
% FUNCTION : set_default
%==========================================================================
function opts = set_default(opts, k, v)
if ~isfield(opts, k) || isempty(opts.(k)), opts.(k) = v; end
end

%==========================================================================
% FUNCTION : weighted_median
%==========================================================================
function m = weighted_median(x, w)
    % returns weighted median of x with positive weights w
    [xs, idx] = sort(x(:));
    ws = w(idx);
    cw = cumsum(ws);
    half = 0.5 * sum(ws);
    j = find(cw >= half, 1, 'first');
    if isempty(j) 
        m = xs(end);
    else
        m = xs(j);
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
function labels = get_dbscan_clustering(tracks_snapshot, measurement_noise)

    tracks_snapshot_rda = tracks_snapshot(:, 1:3);
    tracks_snapshot_r_d_omega = [tracks_snapshot_rda(:, 1) tracks_snapshot_rda(:, 2) pi*sind(tracks_snapshot_rda(:, 3))];

    minPts = 10; % Choose a reasonable value
    epsilon = 3;

    % To be considered in a cluster, minpts must be atleast 2
    labels = dbscan(tracks_snapshot_r_d_omega, epsilon, minPts, ...
                    'Distance', 'mahalanobis', 'Cov', measurement_noise);
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
        if numel(detections_to_plot) > 0
            x_coord_detection = (detections_to_plot(:,1).*cos(deg2rad(detections_to_plot(:,3))));
            y_coord_detection = (detections_to_plot(:,1).*sin(deg2rad(detections_to_plot(:,3))));
        
            for coord_index=1:numel(x_coord_detection)
                scatter(x_coord_detection(coord_index), y_coord_detection(coord_index), 'black');
                hold on;
            end
            detections_legend = sprintf('Detections');
        end
    end

    % 2. Centroids

    if plot_centroids
        if numel(centroids_to_plot) > 0
            x_coord_centroid = (centroids_to_plot(:,1).*cos(deg2rad(centroids_to_plot(:,3))));
            y_coord_centroid = (centroids_to_plot(:,1).*sin(deg2rad(centroids_to_plot(:,3))));
        
            for coord_index=1:numel(x_coord_centroid)
                scatter(x_coord_centroid(coord_index), y_coord_centroid(coord_index), 'red', 'filled');
                hold on;
            end
            centroids_legend = sprintf('Centroids');
        end
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