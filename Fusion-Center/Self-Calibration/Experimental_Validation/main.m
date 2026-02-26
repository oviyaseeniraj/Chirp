clc; clear; close all;

data_path = 'New_Tracking_Data_May/';
trajectory_combinations_path = strcat(data_path, 'trajectory_combinations.mat');

frames_threshold = 100;
residual_threshold = 2;

load(trajectory_combinations_path, 'trajectory_combinations_dict');

avg_P_optimal_value = 0;
avg_theta_optimal_value = 0;
avg_residual_value = 0;
total_track_frames = 0;

for combination_idx = 1:length(keys(trajectory_combinations_dict))
    per_combination_dict = lookup(trajectory_combinations_dict, combination_idx);

    disp(combination_idx);

    if length(keys(per_combination_dict)) == 1
        [P_optimal_array, theta_optimal_array, track_mapping, normalized_residual] = get_single_target_calibration(per_combination_dict);
        disp('Data :');
        disp(keys(per_combination_dict));
        disp(values(per_combination_dict));
        disp(theta_optimal_array);
        disp(P_optimal_array);

        length_frames = size(cell2mat(values(per_combination_dict)));
        length_frames = length_frames(2);

        get_weighted_residual(normalized_residual, length_frames);

        if length_frames > frames_threshold & normalized_residual < residual_threshold 
            avg_P_optimal_value = avg_P_optimal_value + length_frames*P_optimal_array;
            avg_theta_optimal_value = avg_theta_optimal_value + length_frames*theta_optimal_array;

            avg_residual_value = avg_residual_value + length_frames*normalized_residual;
    
            total_track_frames = total_track_frames + length_frames;
        end

    % TO-DO Fix Multi-Target Calibration
    else
        [P_optimal_array, theta_optimal_array, track_mapping, normalized_residual] = get_multi_target_calibration(per_combination_dict);
        disp('Data :');
        disp(keys(per_combination_dict));
        disp(values(per_combination_dict));
        disp(theta_optimal_array);
        disp(P_optimal_array);
        disp(normalized_residual);

        disp('Optimal Track Mappings');
        disp(track_mapping);

        length_frames = size(cell2mat(values(per_combination_dict)));
        length_frames = length_frames(2);

        get_weighted_residual(normalized_residual, length_frames);

        if length_frames > frames_threshold & normalized_residual < residual_threshold
            avg_P_optimal_value = avg_P_optimal_value + length_frames*P_optimal_array;
            avg_theta_optimal_value = avg_theta_optimal_value + length_frames*theta_optimal_array;

            avg_residual_value = avg_residual_value + length_frames*normalized_residual;
    
            total_track_frames = total_track_frames + length_frames;
        end
    end
end

avg_P_optimal_value = avg_P_optimal_value/total_track_frames;
avg_theta_optimal_value = avg_theta_optimal_value/total_track_frames;

avg_residual_value = avg_residual_value/total_track_frames;

disp('Averaged Result :');
disp(avg_P_optimal_value);
disp(avg_theta_optimal_value);
disp(avg_residual_value);

function [] = get_weighted_residual(normalized_residual, num_frames)
    residual = normalized_residual*num_frames;

    A = -log(num_frames)/(1+residual);
    disp(['Weighted Residual - ', num2str(A)]);
end