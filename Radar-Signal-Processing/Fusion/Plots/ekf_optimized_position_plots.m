clc; clear; close all;

load('../x_dict.mat', 'x_dict');
load('../y_dict.mat', 'y_dict');

frame_list = keys(x_dict);

x_state_info_opt_arr = [];
y_state_info_opt_arr = [];

x_state_info_ekf_r1_arr = [];
y_state_info_ekf_r1_arr = [];

x_state_info_ekf_r2_r1_arr = [];
y_state_info_ekf_r2_r1_arr = [];

x_state_info_fused_arr = [];
y_state_info_fused_arr = [];

for frame_idx=1:length(frame_list)
    x_info_dict_per_frame = x_dict(frame_list(frame_idx));
    y_info_dict_per_frame = y_dict(frame_list(frame_idx));

    x_state_info_ekf_r1_arr = [x_state_info_ekf_r1_arr; x_info_dict_per_frame('EKF-State-R1')];
    x_state_info_ekf_r2_r1_arr = [x_state_info_ekf_r2_r1_arr; x_info_dict_per_frame('EKF-State-R2-R1')];
    x_state_info_opt_arr = [x_state_info_opt_arr; x_info_dict_per_frame('Optimized')];
    x_state_info_fused_arr = [x_state_info_fused_arr; x_info_dict_per_frame('Track-To-Track-Fusion')];
    
    y_state_info_ekf_r1_arr = [y_state_info_ekf_r1_arr; y_info_dict_per_frame('EKF-State-R1')];
    y_state_info_ekf_r2_r1_arr = [y_state_info_ekf_r2_r1_arr; y_info_dict_per_frame('EKF-State-R2-R1')];
    y_state_info_opt_arr = [y_state_info_opt_arr; y_info_dict_per_frame('Optimized')];
    y_state_info_fused_arr = [y_state_info_fused_arr; y_info_dict_per_frame('Track-To-Track-Fusion')];
end

figure;

hold on;
%h1 = errorbar(frame_list, v_x_state_info_ekf_arr, v_x_cov_info_ekf_arr, 'o-', 'MarkerSize', 8, 'LineWidth', 1);
h1 = plot(frame_list, x_state_info_ekf_r1_arr, '-', 'MarkerSize', 8, 'LineWidth', 1);
grid on;
title('X estimates from EKF/One-shot Fusion');
xlabel('Frame');
ylabel('X(m)');

%h2 = plot(frame_list, x_state_info_fused_arr, 'cx-', 'MarkerSize', 8, 'LineWidth', 1);

h3 = plot(frame_list, x_state_info_ekf_r2_r1_arr, 'ro-', 'MarkerSize', 8, 'LineWidth', 1);

h4 = plot(frame_list, x_state_info_opt_arr, 'g-', 'MarkerSize', 8, 'LineWidth', 1);


legend([h1, h3, h4], {'X from S1 EKF', 'X from S2 EKF transformed to S1', 'X from one-shot fusion'}, ...
                                                       'Location', 'best');
hold off;

figure;

hold on;
%h1 = errorbar(frame_list(1:19), v_y_state_info_ekf_arr(1:19), v_y_cov_info_ekf_arr(1:19), 'o-', 'MarkerSize', 8, 'LineWidth', 1);
h1 = plot(frame_list, y_state_info_ekf_r1_arr, '-', 'MarkerSize', 8, 'LineWidth', 1);
grid on;
title('Y estimates from EKF/One-shot Fusion');
xlabel('Frame');
ylabel('Y(m)');

%h2 = plot(frame_list, y_state_info_fused_arr, 'cx-', 'MarkerSize', 8, 'LineWidth', 1);

h3 = plot(frame_list, y_state_info_ekf_r2_r1_arr, 'ro-', 'MarkerSize', 8, 'LineWidth', 1);

h4 = plot(frame_list, y_state_info_opt_arr, 'g-', 'MarkerSize', 8, 'LineWidth', 1);

legend([h1, h3, h4], {'Y from S1 EKF', 'Y from S2 EKF transformed to S1', 'Y from one-shot fusion'}, ...
                                                       'Location', 'best');
hold off;