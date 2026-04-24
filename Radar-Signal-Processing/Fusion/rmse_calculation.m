clc; clear; close all;

load('x_dict.mat', 'x_dict');
load('y_dict.mat', 'y_dict');
load('v_x_dict.mat', 'v_x_dict');
load('v_y_dict.mat', 'v_y_dict');

frame_list = keys(x_dict);

rmse_velocity_r1 = 0;
rmse_velocity_r2_r1 = 0;
rmse_position_r1 = 0;
rmse_position_r2_r1 = 0;

fusion_rmse = false;

for frame_index = 1:length(frame_list)

    x_dict_per_frame = x_dict(frame_list(frame_index));
    y_dict_per_frame = y_dict(frame_list(frame_index));
    v_x_dict_per_frame = v_x_dict(frame_list(frame_index));
    v_y_dict_per_frame = v_y_dict(frame_list(frame_index));

    x_ekf_r1 = x_dict_per_frame('EKF-State-R1');
    x_ekf_r2_r1 = x_dict_per_frame('EKF-State-R2-R1');
    x_fused = x_dict_per_frame('Track-To-Track-Fusion');
    y_ekf_r1 = y_dict_per_frame('EKF-State-R1');
    y_ekf_r2_r1 = y_dict_per_frame('EKF-State-R2-R1');
    y_fused = y_dict_per_frame('Track-To-Track-Fusion');

    v_x_ekf_r1 = v_x_dict_per_frame('EKF-State-R1');
    v_x_ekf_r2_r1 = v_x_dict_per_frame('EKF-State-R2-R1');
    v_x_fused = v_x_dict_per_frame('Track-To-Track-Fusion');
    v_y_ekf_r1 = v_y_dict_per_frame('EKF-State-R1');
    v_y_ekf_r2_r1 = v_y_dict_per_frame('EKF-State-R2-R1');
    v_y_fused = v_y_dict_per_frame('Track-To-Track-Fusion');

    x_opt = x_dict_per_frame('Optimized');
    y_opt = y_dict_per_frame('Optimized');
    v_x_opt = v_x_dict_per_frame('Optimized');
    v_y_opt = v_y_dict_per_frame('Optimized');

    if fusion_rmse
        position_error_r1 = sqrt((x_ekf_r1 - fused_track(1))^2 + (y_ekf_r1 - fused_track(3))^2);
        position_error_r2_r1 = sqrt((x_ekf_r2_r1 - fused_track(1))^2 + (y_ekf_r2_r1 - fused_track(3))^2);
    
        velocity_error_r1 = sqrt((v_x_ekf_r1 - fused_track(2))^2 + (v_y_ekf_r1 - fused_track(4))^2);
        velocity_error_r2_r1 = sqrt((v_x_ekf_r2_r1 - fused_track(2))^2 + (v_y_ekf_r2_r1 - fused_track(4))^2);

    else
        position_error_r1 = sqrt((x_ekf_r1 - x_opt)^2 + (y_ekf_r1 - y_opt)^2);
        position_error_r2_r1 = sqrt((x_ekf_r2_r1 - x_opt)^2 + (y_ekf_r2_r1 - y_opt)^2);
    
        velocity_error_r1 = sqrt((v_x_ekf_r1 - v_x_opt)^2 + (v_y_ekf_r1 - v_y_opt)^2);
        velocity_error_r2_r1 = sqrt((v_x_ekf_r2_r1 - v_x_opt)^2 + (v_y_ekf_r2_r1 - v_y_opt)^2);
    end

    rmse_position_r1 = rmse_position_r1 + position_error_r1^2;
    rmse_position_r2_r1 = rmse_position_r2_r1 + position_error_r2_r1^2;
    rmse_velocity_r1 = rmse_velocity_r1 + velocity_error_r1^2;
    rmse_velocity_r2_r1 = rmse_velocity_r2_r1 + velocity_error_r2_r1^2;
end

rmse_position_r1 = sqrt(rmse_position_r1/length(frame_list));
rmse_position_r2_r1 = sqrt(rmse_position_r2_r1/length(frame_list));
rmse_velocity_r1 = sqrt(rmse_velocity_r1/length(frame_list));
rmse_velocity_r2_r1 = sqrt(rmse_velocity_r2_r1/length(frame_list));

disp(['RMSE Position w.r.t R1 EKF : ', num2str(rmse_position_r1)]);
disp(['RMSE Position w.r.t R2 EKF transformed to R1 : ', num2str(rmse_position_r2_r1)]);
disp(['RMSE Velocity w.r.t R1 EKF : ', num2str(rmse_velocity_r1)]);
disp(['RMSE Velocity w.r.t R2 EKF rotated to R1 : ', num2str(rmse_velocity_r2_r1)]);