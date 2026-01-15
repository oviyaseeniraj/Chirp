%==========================================================================
% FUNCTION : plot_centroids_tracks
% Plots the cluster centroids and tracks
% INPUT - centroids, tracks, frame id
%==========================================================================
function [prev_plot_dict] = plot_centroids_tracks(prev_plot_dict, centroids, tracks, ...
                                      history, frame_idx, plot_centroids, plot_tracks)

    % Format of prev_plot_dict
    % {frame_idx : {'detections' : detections, 'centroids' : centroids, 
    %               'tracks' : tracks}

    % Populate data from previous dictionary based on history
    start_frame_idx = frame_idx - history + 1;

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
    centroids_to_plot = [centroids_to_plot; centroids];
    tracks_to_plot = add_tracks_to_dict(tracks_to_plot, ...
                                        tracks, frame_idx);

    % Populate new data in prev_plot_dict
    dict = dictionary;
    dict = insert(dict, 'centroids', {centroids});
    dict = insert(dict, 'tracks', {tracks});

    prev_plot_dict = insert(prev_plot_dict, frame_idx, dict);

    % Plot all data

    centroids_legend = [];
    tracks_legend = [];

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