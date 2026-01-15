clc; clear; close all;
load('Data/121324_R1_E3_Raw_0_noRangeFT_Track_Dict.mat', 'track_dict');

track_ids = keys(track_dict);

track_id = 0;
start_frame = 0;
end_frame = 0;

for track_id_idx = 1:length(track_ids)
    tracks_by_frame_dict = track_dict(track_ids(track_id_idx));
    frames_list = keys(tracks_by_frame_dict);
    if length(frames_list) > 100
        start_frame = frames_list(1);
        end_frame = frames_list(100);
        track_id = track_ids(track_id_idx);
        break;
    end
end

load('../R1-E3_final.mat', 'prev_plot_dict');

detection_dict = prev_plot_dict;

v_x_array = [];
v_y_array = [];
cov_v_x_array = [];
cov_v_y_array = [];

x_array = [];
y_array = [];
cov_x_array = [];
cov_y_array = [];

for frame_idx = start_frame:end_frame
    if isKey(detection_dict, frame_idx)
        detection_dict_per_frame = detection_dict(frame_idx);
        tracks_per_frame = detection_dict_per_frame('tracks');
        tracks_per_frame = tracks_per_frame{1};
    
        if numel(tracks_per_frame) == 1 && tracks_per_frame.TrackID == track_id
            track_state = tracks_per_frame.State;
            track_covariance = tracks_per_frame.StateCovariance;
    
            v_x_array = [v_x_array track_state(2)];
            v_y_array = [v_y_array track_state(4)];
            cov_v_x_array = [cov_v_x_array track_covariance(2, 2)];
            cov_v_y_array = [cov_v_y_array track_covariance(4, 4)];

            x_array = [x_array track_state(1)];
            y_array = [y_array track_state(3)];
            cov_x_array = [cov_x_array track_covariance(1, 1)];
            cov_y_array = [cov_y_array track_covariance(3, 3)];
        end
    end
end

i = 1:length(v_x_array);


figure;
hold on;
h1 = errorbar(i, v_x_array, cov_v_x_array, 'o-', 'MarkerSize', 8, 'LineWidth', 1.5);
grid on;
title('V_X from EKF estimates for Radar 1');
xlabel('Frame');
ylabel('V_X');
legend(h1, 'V_X estimates with uncertainities');
hold off;

figure;
hold on;
h2 = errorbar(i, v_y_array, cov_v_y_array, 'o-', 'MarkerSize', 8, 'LineWidth', 1.5);
grid on;
title('V_Y from EKF estimates for Radar 1');
xlabel('Frame');
ylabel('V_Y');
legend(h2, 'V_Y estimates with uncertainities');
hold off;

figure;
errorbar(i, x_array, cov_x_array, 'o-', 'MarkerSize', 8, 'LineWidth', 1.5);
grid on;
axis([0 length(x_array) 1 6]);
figure;
errorbar(i, y_array, cov_y_array, 'o-', 'MarkerSize', 8, 'LineWidth', 1.5);
axis([0 length(y_array) -3 3]);
grid on;
