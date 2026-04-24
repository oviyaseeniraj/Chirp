clc; clear; close all;

load('../v_x_dict.mat', 'v_x_dict');
load('../v_y_dict.mat', 'v_y_dict');

frame_list = keys(v_x_dict);

v_x_state_info_opt_arr = [];
v_y_state_info_opt_arr = [];

v_x_state_info_ekf_r1_arr = [];
v_y_state_info_ekf_r1_arr = [];

v_x_state_info_ekf_r2_r1_arr = [];
v_y_state_info_ekf_r2_r1_arr = [];

v_x_state_info_fused_arr = [];
v_y_state_info_fused_arr = [];

for frame_idx=1:length(frame_list)
    v_x_info_dict_per_frame = v_x_dict(frame_list(frame_idx));
    v_y_info_dict_per_frame = v_y_dict(frame_list(frame_idx));

    v_x_state_info_ekf_r1_arr = [v_x_state_info_ekf_r1_arr; v_x_info_dict_per_frame('EKF-State-R1')];
    v_x_state_info_ekf_r2_r1_arr = [v_x_state_info_ekf_r2_r1_arr; v_x_info_dict_per_frame('EKF-State-R2-R1')];
    v_x_state_info_opt_arr = [v_x_state_info_opt_arr; v_x_info_dict_per_frame('Optimized')];
    v_x_state_info_fused_arr = [v_x_state_info_fused_arr; v_x_info_dict_per_frame('Track-To-Track-Fusion')];

    v_y_state_info_ekf_r1_arr = [v_y_state_info_ekf_r1_arr; v_y_info_dict_per_frame('EKF-State-R1')];
    v_y_state_info_ekf_r2_r1_arr = [v_y_state_info_ekf_r2_r1_arr; v_y_info_dict_per_frame('EKF-State-R2-R1')];
    v_y_state_info_opt_arr = [v_y_state_info_opt_arr; v_y_info_dict_per_frame('Optimized')];
    v_y_state_info_fused_arr = [v_y_state_info_fused_arr; v_y_info_dict_per_frame('Track-To-Track-Fusion')];
end

figure;
hold on;
%h1 = errorbar(frame_list, v_x_state_info_ekf_arr, v_x_cov_info_ekf_arr, 'o-', 'MarkerSize', 8, 'LineWidth', 1);
h1 = plot(frame_list, v_x_state_info_ekf_r1_arr, '-', 'MarkerSize', 8, 'LineWidth', 1);
grid on;
title('V_X estimates from EKF/One-shot Fusion');
xlabel('Frame');
ylabel('V_X(m/s)');

h2 = plot(frame_list, v_x_state_info_opt_arr, 'g-', 'MarkerSize', 8, 'LineWidth', 1);

h3 = plot(frame_list, v_x_state_info_ekf_r2_r1_arr, 'r-', 'MarkerSize', 8, 'LineWidth', 1);

%h4 = plot(frame_list, v_x_state_info_fused_arr, 'c--', 'MarkerSize', 8, 'LineWidth', 1);

legend([h1, h2, h3], {'V_X from S1 EKF', 'V_X from one-shot fusion',...
                       'V_X from S2 EKF transformed to S1'}, ...
                                                       'Location', 'best');
hold off;

figure;
hold on;
%h1 = errorbar(frame_list(1:19), v_y_state_info_ekf_arr(1:19), v_y_cov_info_ekf_arr(1:19), 'o-', 'MarkerSize', 8, 'LineWidth', 1);
h1 = plot(frame_list, v_y_state_info_ekf_r1_arr, '-', 'MarkerSize', 8, 'LineWidth', 1);
grid on;
title('V_Y estimates from EKF/One-shot Fusion');
xlabel('Frame');
ylabel('V_Y(m/s)');

h2 = plot(frame_list, v_y_state_info_opt_arr, 'g-', 'MarkerSize', 8, 'LineWidth', 1);

h3 = plot(frame_list, v_y_state_info_ekf_r2_r1_arr, 'r-', 'MarkerSize', 8, 'LineWidth', 1);

%h4 = plot(frame_list, v_y_state_info_fused_arr, 'c--', 'MarkerSize', 8, 'LineWidth', 1);

legend([h1, h2, h3], {'V_Y from S1 EKF', 'V_Y from one-shot fusion', ...
                        'V_Y from S2 EKF transformed to S1'}, ...
                                                       'Location', 'best');
hold off;