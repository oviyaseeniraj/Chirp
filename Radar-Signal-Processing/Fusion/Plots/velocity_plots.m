clc; clear; close all;

load('v_x_dict.mat', 'v_x_dict');
load('v_y_dict.mat', 'v_y_dict');

frame_list = keys(v_x_dict);

v_x_ekf_r1_arr = [];
v_x_ekf_r2_r1_arr = [];

v_y_ekf_r1_arr = [];
v_y_ekf_r2_r1_arr = [];

for frame_idx=1:length(frame_list)
    v_x_info_dict_per_frame = v_x_dict(frame_list(frame_idx));
    v_y_info_dict_per_frame = v_y_dict(frame_list(frame_idx));

    v_x_ekf_r1_arr = [v_x_ekf_r1_arr; v_x_info_dict_per_frame('R1-EKF')];
    v_x_ekf_r2_r1_arr = [v_x_ekf_r2_r1_arr; v_x_info_dict_per_frame('R2-EKF-R1')];

    v_y_ekf_r1_arr = [v_y_ekf_r1_arr; v_y_info_dict_per_frame('R1-EKF')];
    v_y_ekf_r2_r1_arr = [v_y_ekf_r2_r1_arr; v_y_info_dict_per_frame('R2-EKF-R1')];
end

figure;
hold on;
h3 = plot(frame_list(1:19), v_x_ekf_r1_arr(1:19), 'o--', 'MarkerSize', 8, 'LineWidth', 1);
h4 = plot(frame_list(1:19), v_x_ekf_r2_r1_arr(1:19), 'r--', 'MarkerSize', 8, 'LineWidth', 1);
grid on;
title('V_X estimates vs frames');
xlabel('Frame');
ylabel('V_X');

legend([h3, h4], {'V_X from R1 EKF', ...
                          'V_X from R2 EKF transformed to R1'}, ...
                          'Location', 'best');
hold off;

figure;
hold on;
h3 = plot(frame_list(1:19), v_y_ekf_r1_arr(1:19), 'o--', 'MarkerSize', 8, 'LineWidth', 1);
h4 = plot(frame_list(1:19), v_y_ekf_r2_r1_arr(1:19), 'r--', 'MarkerSize', 8, 'LineWidth', 1);
grid on;
title('V_Y estimates vs frames');
xlabel('Frame');
ylabel('V_Y');

legend([h3, h4], {'V_Y from R1 EKF', ...
                          'V_Y from R2 EKF transformed to R1'}, ...
                          'Location', 'best');
hold off;
