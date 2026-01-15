clc; clear; close all;

load('x_dict.mat', 'x_dict');
load('y_dict.mat', 'y_dict');

frame_list = keys(x_dict);

x_detection_r1_arr = [];
x_detection_r2_r1_arr = [];
x_ekf_r1_arr = [];
x_ekf_r2_r1_arr = [];

y_detection_r1_arr = [];
y_detection_r2_r1_arr = [];
y_ekf_r1_arr = [];
y_ekf_r2_r1_arr = [];

for frame_idx=1:length(frame_list)
    x_info_dict_per_frame = x_dict(frame_list(frame_idx));
    y_info_dict_per_frame = y_dict(frame_list(frame_idx));

    x_detection_r1_arr = [x_detection_r1_arr; x_info_dict_per_frame('R1-Centroid')];
    x_detection_r2_r1_arr = [x_detection_r2_r1_arr; x_info_dict_per_frame('R2-Centroid-R1')];
    x_ekf_r1_arr = [x_ekf_r1_arr; x_info_dict_per_frame('R1-EKF')];
    x_ekf_r2_r1_arr = [x_ekf_r2_r1_arr; x_info_dict_per_frame('R2-EKF-R1')];

    y_detection_r1_arr = [y_detection_r1_arr; y_info_dict_per_frame('R1-Centroid')];
    y_detection_r2_r1_arr = [y_detection_r2_r1_arr; y_info_dict_per_frame('R2-Centroid-R1')];
    y_ekf_r1_arr = [y_ekf_r1_arr; y_info_dict_per_frame('R1-EKF')];
    y_ekf_r2_r1_arr = [y_ekf_r2_r1_arr; y_info_dict_per_frame('R2-EKF-R1')];
end

figure;
hold on;
h1 = plot(frame_list, x_detection_r1_arr, 'o-', 'MarkerSize', 8, 'LineWidth', 1);
h2 = plot(frame_list, x_detection_r2_r1_arr, 'r-', 'MarkerSize', 8, 'LineWidth', 1);
h3 = plot(frame_list, x_ekf_r1_arr, 'o--', 'MarkerSize', 8, 'LineWidth', 1);
h4 = plot(frame_list, x_ekf_r2_r1_arr, 'r--', 'MarkerSize', 8, 'LineWidth', 1);
grid on;
title('X estimates vs frames');
xlabel('Frame');
ylabel('X');

legend([h1, h2, h3, h4], {'X from R1 centroid', ...
                          'X from R2 centroid transformed to R1', ...
                          'X from R1 EKF', ...
                          'X from R2 EKF transformed to R1'}, ...
                          'Location', 'best');
hold off;

figure;
hold on;
h1 = plot(frame_list, y_detection_r1_arr, 'o-', 'MarkerSize', 8, 'LineWidth', 1);
h2 = plot(frame_list, y_detection_r2_r1_arr, 'r-', 'MarkerSize', 8, 'LineWidth', 1);
h3 = plot(frame_list, y_ekf_r1_arr, 'o--', 'MarkerSize', 8, 'LineWidth', 1);
h4 = plot(frame_list, y_ekf_r2_r1_arr, 'r--', 'MarkerSize', 8, 'LineWidth', 1);
grid on;
title('Y estimates vs frames');
xlabel('Frame');
ylabel('Y');

legend([h1, h2, h3, h4], {'Y from R1 centroid', ...
                          'Y from R2 centroid transformed to R1', ...
                          'Y from R1 EKF', ...
                          'Y from R2 EKF transformed to R1'}, ...
                          'Location', 'best');
hold off;
