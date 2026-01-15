clc; clear; close all;

load('x_dict.mat', 'x_dict');
load('y_dict.mat', 'y_dict');
load('v_x_dict.mat', 'v_x_dict');
load('v_y_dict.mat', 'v_y_dict');

frame_list = keys(x_dict);

rmse_velocity = 0;
rmse_position = 0;

fusion_rmse = true;

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
        position_error = sqrt((x_opt - x_fused)^2 + (y_opt - y_fused)^2);
        
        velocity_error = sqrt((v_x_opt - v_x_fused)^2 + (v_y_opt - v_y_fused)^2);
    else
        position_error = sqrt((x_ekf_r1 - x_ekf_r2_r1)^2 + (y_ekf_r1 - y_ekf_r2_r1)^2);
        
        velocity_error = sqrt((v_x_ekf_r1 - v_x_ekf_r2_r1)^2 + (v_y_ekf_r1 - v_y_ekf_r2_r1)^2);
    end

    rmse_position = rmse_position + position_error^2;
    rmse_velocity = rmse_velocity + velocity_error^2;
end

rmse_position = sqrt(rmse_position/length(frame_list));
rmse_velocity = sqrt(rmse_velocity/length(frame_list));

if fusion_rmse
    disp(['RMSE Position w.r.t Track-To-Track Fusion Estimates : ', num2str(rmse_position)]);
    disp(['RMSE Velocity w.r.t Track-To-Track Fusion Estimates : ', num2str(rmse_velocity)]);
else
    disp(['RMSE Position EKF R1/R2 : ', num2str(rmse_position)]);
    disp(['RMSE Velocity EKF R1/R2 : ', num2str(rmse_velocity)]);
end