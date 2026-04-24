%==========================================================================
% FUNCTION : plot_overlayed_centroids
% Plots the cluster centroids and tracks
% INPUT - centroids, tracks, frame id
%==========================================================================
function [prev_plot_dict] = plot_overlayed_centroids(prev_plot_dict, centroids_r1, centroids_r2, ...
                                      history, frame_idx, plot_centroids)

    % Format of prev_plot_dict
    % {frame_idx : {'detections' : detections, 'centroids' : centroids, 
    %               'tracks' : tracks}

    % Populate data from previous dictionary based on history
    start_frame_idx = frame_idx - history + 1;

    centroids_to_plot_r1 = [];
    centroids_to_plot_r2 = [];

    % First fill all the data to plot from the history dict
    for idx = start_frame_idx:(frame_idx-1)
        if isConfigured(prev_plot_dict) && idx >= 1
            item = lookup(prev_plot_dict, idx, "FallbackValue", dictionary);
        else
            item = dictionary;
        end
        if isConfigured(item)

            centroids_per_frame_r1 = cell2mat(lookup(item, 'centroids_r1'));
            centroids_per_frame_r2 = cell2mat(lookup(item, 'centroids_r2'));
            centroids_to_plot_r1 = [centroids_to_plot_r1; 
                                    centroids_per_frame_r1];
            centroids_to_plot_r2 = [centroids_to_plot_r2; 
                                    centroids_per_frame_r2];
        end
    end

    % Now fill all the data to plot from the current frame
    centroids_to_plot_r1 = [centroids_to_plot_r1; centroids_r1];
    centroids_to_plot_r2 = [centroids_to_plot_r2; centroids_r2];

    % Populate new data in prev_plot_dict
    dict = dictionary;
    dict = insert(dict, 'centroids_r1', {centroids_r1});
    dict = insert(dict, 'centroids_r2', {centroids_r2});

    prev_plot_dict = insert(prev_plot_dict, frame_idx, dict);

    % Plot all data

    % 2. Centroids

    if plot_centroids
        x_coord_centroid_r1 = (centroids_to_plot_r1(:,1).*cos(deg2rad(centroids_to_plot_r1(:,3))));
        y_coord_centroid_r1 = (centroids_to_plot_r1(:,1).*sin(deg2rad(centroids_to_plot_r1(:,3))));
    
        for coord_index=1:numel(x_coord_centroid_r1)
            scatter(x_coord_centroid_r1(coord_index), y_coord_centroid_r1(coord_index), 'red', 'filled');
            hold on;
        end

        x_coord_centroid_r2 = (centroids_to_plot_r2(:,1).*cos(deg2rad(centroids_to_plot_r2(:,3))));
        y_coord_centroid_r2 = (centroids_to_plot_r2(:,1).*sin(deg2rad(centroids_to_plot_r2(:,3))));
    
        for coord_index=1:numel(x_coord_centroid_r2)
            scatter(x_coord_centroid_r2(coord_index), y_coord_centroid_r2(coord_index), 'blue', 'filled');
            hold on;
        end
    end

    xlabel("X-Axis");
    ylabel("Y-Axis");
    title_string = sprintf('');

    if plot_centroids
        title_string = strcat(title_string, ' Centroids, R1 - Red, R2 - Blue');
    end

    title_string = strcat(title_string, ' Frame - ', num2str(frame_idx));

    title(title_string);
    grid on;
    %legend(['Detections', 'Centroids', 'Tracks']);
    axis([0 12 -10 10]);

    hold off;
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