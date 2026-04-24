clear; clc;

experiment_name = 'May17_cfg1_radar1_random_noRangeFT';

output_path = 'Data/New_Tracking_Data_May/';

data_path = strcat(output_path, experiment_name, '_Track_Dict.mat');
load(data_path, 'track_dict');

min_frames = 30;

track_ids = keys(track_dict);
filtered_track_dict = dictionary;

%% Only keep those Tracks which are present for >= min_frames
for index=1:length(track_ids)
    track_info_per_frame = track_dict(track_ids(index));
    if numEntries(track_info_per_frame) < min_frames
        track_dict = remove(track_dict, track_ids(index));
    end
end

track_ids = keys(track_dict);
for index=1:length(track_ids)
    track_info_per_frame = track_dict(track_ids(index));
    frame_ids = keys(track_info_per_frame);

    for i=1:length(frame_ids)
        if isConfigured(filtered_track_dict)
            dict = lookup(filtered_track_dict, frame_ids(i), "FallbackValue", dictionary);
        else
            dict = dictionary;
        end
        dict = insert(dict, track_ids(index), track_info_per_frame(frame_ids(i)));
        filtered_track_dict = insert(filtered_track_dict, frame_ids(i), dict);
    end
end

output_path = strcat(output_path, experiment_name, '_Filtered_Track_Dict.mat');
save(output_path, 'filtered_track_dict');

% Display frames where multiple tracks occur
frame_ids = keys(filtered_track_dict);
for index=1:length(frame_ids)
    if numEntries(filtered_track_dict(frame_ids(index))) >= 2
        disp(frame_ids(index));
    end
end