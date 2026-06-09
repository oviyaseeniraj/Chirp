clc; clear; close all;
% Loading Data

data_path = 'New_Tracking_Data_May/';

radar_1_per_frame_path = strcat(data_path, ...
       'May17_cfg1_radar1_straight_noRangeFT_Filtered_Track_Dict.mat');

radar_2_per_frame_path = strcat(data_path, ...
       'may17_cfg1_radar2_straight_noRangeFT_Filtered_Track_Dict.mat');

track_combination_path = strcat(data_path, ...
           'May17_cfg1_straight_noRangeFT_Track_Combination_Dict.mat');

load(radar_1_per_frame_path, 'filtered_track_dict');
radar_1_per_frame_dict = filtered_track_dict;

load(radar_2_per_frame_path, 'filtered_track_dict');
radar_2_per_frame_dict = filtered_track_dict;

load(track_combination_path, 'track_combination_dict');

%==========================================================================
% Prepare Trajectory Estimate Dict for all pairwise tracks

% FORMAT - { 1 : {[t_1, T_1] : [[p_1, ..., p_k]
%                               [q_1, ..., q_k]]}}
% Where p and q are the track trajectory estimates for the two radars

trajectory_combinations_dict = dictionary;

for track_combination_idx = 1:length(keys(track_combination_dict))
    radar_1_track_ids_arr = cell2mat(lookup(track_combination_dict(track_combination_idx), 'R1'));
    radar_2_track_ids_arr = cell2mat(lookup(track_combination_dict(track_combination_idx), 'R2'));
    frames_arr = cell2mat(lookup(track_combination_dict(track_combination_idx), ...
                         'Frames'));

    per_track_combination_dict = dictionary;

    for radar_1_track_idx = 1:length(radar_1_track_ids_arr)
        for radar_2_track_idx = 1:length(radar_2_track_ids_arr)
            trajectory_arr = zeros([2 length(frames_arr)]);
            for frame_idx = 1:length(frames_arr)
                radar_1_trajectory_estimate = cell2mat(lookup(radar_1_per_frame_dict(frames_arr(frame_idx)), ...
                                radar_1_track_ids_arr(radar_1_track_idx)));
                radar_2_trajectory_estimate = cell2mat(lookup(radar_2_per_frame_dict(frames_arr(frame_idx)), ...
                                radar_2_track_ids_arr(radar_2_track_idx)));

                % Taking only the X Y coordinates
                radar_1_trajectory_estimate = radar_1_trajectory_estimate([1 3]);
                radar_2_trajectory_estimate = radar_2_trajectory_estimate([1 3]);

                % Change 1 and 2 indices, to generate different orders
                trajectory_arr(1, frame_idx) = complex(radar_1_trajectory_estimate(1), ...
                                           radar_1_trajectory_estimate(2));
                trajectory_arr(2, frame_idx) = complex(radar_2_trajectory_estimate(1), ...
                                           radar_2_trajectory_estimate(2));
            end

            per_track_combination_dict = insert(per_track_combination_dict, ...
                {[radar_1_track_ids_arr(radar_1_track_idx) radar_2_track_ids_arr(radar_2_track_idx)]}, ...
                {trajectory_arr});
        end
    end

    trajectory_combinations_dict = insert(trajectory_combinations_dict, ...
                        track_combination_idx, per_track_combination_dict);
end

output_path = strcat(data_path, 'trajectory_combinations.mat');
save(output_path, "trajectory_combinations_dict");