clc; clear; close all;

% Load Data Paths

output_path = 'Data/New_Tracking_Data_May/';

data_path_radar_1_frame_level = strcat(output_path, 'May17_cfg1_radar1_random_noRangeFT', ...
                                '_Filtered_Track_Dict.mat');

data_path_radar_2_frame_level = strcat(output_path, 'may17_cfg1_radar2_random_noRangeFT', ...
                                '_Filtered_Track_Dict.mat');

load(data_path_radar_1_frame_level, 'filtered_track_dict');
radar_1_frame_level_dict = filtered_track_dict;
load(data_path_radar_2_frame_level, 'filtered_track_dict');
radar_2_frame_level_dict = filtered_track_dict;

%==========================================================================
% Get Frame Dict
%% Combine both frame level dicts from two radar perspectives
%% {Frame Idx : {1: [t_1, ..., t_m], 2: [T_1, ..., T_n]}}

num_frames = 600;
frame_dict = dictionary;

for frame_idx=1:num_frames
    frame_data_radar_1 = lookup(radar_1_frame_level_dict, frame_idx, ...
                                FallbackValue=dictionary);
    frame_data_radar_2 = lookup(radar_2_frame_level_dict, frame_idx, ...
                                FallbackValue=dictionary);

    if isConfigured(frame_data_radar_1) && isConfigured(frame_data_radar_2)
        dict = dictionary;
        dict = insert(dict, 1, {keys(frame_data_radar_1)});
        dict = insert(dict, 2, {keys(frame_data_radar_2)});
        frame_dict = insert(frame_dict, frame_idx, dict);
    end
end

% Get track combinaion dictionary
track_combination_dict = get_track_combinations(frame_dict);

output_path = strcat(output_path, 'May17_cfg1_random_noRangeFT', ...
                     '_Track_Combination_Dict.mat');
save(output_path,"track_combination_dict");

%==========================================================================
% FUNCTION - Get Track Combinations
% For getting the corresponding track combinations and the frame numbers
% for use in the calibration code

% FORMAT - {1 : {'R1' : [t_1, ..., t_m], 'R2' : [T_1, ..., T_2], 
% 'Frames' : [f_1, ..., f_k]}

function track_combination_dict = get_track_combinations(frame_dict)
    
    track_combination_dict = dictionary;
    frame_indices_arr = keys(frame_dict);

    init_idx = 1;
    idx = 1;
    combination_idx = 1;

    while init_idx < length(frame_indices_arr)

        frames_in_combination = [];

        % Check for all consecutive frames, for which the track lists are
        % the same for both radars. These will be part of a single
        % track combination.
        while isequal(frame_dict(frame_indices_arr(init_idx)), ...
              frame_dict(frame_indices_arr(idx))) && idx < length(frame_indices_arr)
            frames_in_combination = [frames_in_combination frame_indices_arr(idx)];
            idx = idx+1;
        end

        % Add Info
        dict = dictionary;
        frame_info = frame_dict(frame_indices_arr(init_idx));
        dict = insert(dict, 'R1', frame_info(1));
        dict = insert(dict, 'R2', frame_info(2));
        dict = insert(dict, 'Frames', {frames_in_combination});
        track_combination_dict = insert(track_combination_dict, combination_idx, dict);

        % Go to the next combination
        init_idx = idx;
        combination_idx = combination_idx+1;
    end

end

