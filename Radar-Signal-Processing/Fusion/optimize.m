clc; clear; close all;

output_video_file_name = '02232025_ExpD_Single.avi';

load('Data/02232025_expd_single_l_Raw_0_noRangeFT_detection_data.mat', 'prev_plot_dict');
r1_detection_dict = prev_plot_dict;

load('Data/02232025_ExpD_Single_R_Raw_0_noRangeFT_detection_data.mat', 'prev_plot_dict');
r2_detection_dict = prev_plot_dict;

load('Data/02232025_ExpD_Single_Fused.mat', 'prev_plot_dict');
track_fusion_dict = prev_plot_dict;


% Calibration dicts contain the relative calibration data
% calibration_dict_2_1.mat - Radar 2 w.r.t Radar 1
% calibration_dict_1_2.mat - Radar 1 w.r.t Radar 2

load('calibration_dict_Exp_1_2_1_0.mat', 'calibration_dict_Exp_1_2_1_0');

load('calibration_dict_Exp_1_1_2_0.mat', 'calibration_dict_Exp_1_1_2_0');

calibration_dict_2_1 = calibration_dict_Exp_1_2_1_0;
calibration_dict_1_2 = calibration_dict_Exp_1_1_2_0;

common_frames = intersect(keys(r1_detection_dict), keys(r2_detection_dict));

common_frames = intersect(common_frames, keys(track_fusion_dict));

range_resolution = 0.035*2;
spatial_angle_resolution = 2*pi/4;
doppler_resolution = 0.3614; %0.3654*2;

association_threshold = 0.5;

% All data dictionaries
x_opt_dict_r_a = dictionary;
x_opt_dict_r_d_a = dictionary;

rmse_position = 0;
rmse_velocity = 0;

position_error_dict = dictionary;
velocity_error_dict = dictionary;

v_x_dict = dictionary;
v_y_dict = dictionary;
x_dict = dictionary;
y_dict = dictionary;

vel_x_opt_dict = dictionary;
vel_y_opt_dict = dictionary;
x_opt_dict = dictionary;
y_opt_dict = dictionary;

pos_gaussian_dict = dictionary;
velocity_gaussian_dict = dictionary;

filtered_plot_dict = dictionary;

%Check the number of frames reqd for RMSE calculation
rmse_frames = 0;

output_video_path = strcat('Videos/', output_video_file_name);
% 
figure();
vw = VideoWriter(output_video_path);
vw.Quality = 100;
vw.FrameRate = 20;
open(vw);

for i=1:length(common_frames)

    if common_frames(i) == 165 || common_frames(i) == 212
        disp('Frame');
    end

    disp(['Frame : ', num2str(common_frames(i))]);

    r1_dict = r1_detection_dict(common_frames(i));
    r2_dict = r2_detection_dict(common_frames(i));

    centroids_r1 = cell2mat(r1_dict('centroids'));
    centroids_r2 = cell2mat(r2_dict('centroids'));

    [centroids_r1_matched, centroids_r2_matched, centroids_r2_transformed_matched] = get_centroid_associations(centroids_r1, ...
                centroids_r2, calibration_dict_2_1, association_threshold);

    for index=1:size(centroids_r1_matched, 1)

        % Firstly optimize x and y

        [x_opt, resnorm] = optimization_range_angle(centroids_r1_matched(index, :), ...
                                        centroids_r2_matched(index, :), ...
                                        range_resolution, spatial_angle_resolution, ...
                                        calibration_dict_2_1, calibration_dict_1_2);

        x_opt_dict_r_a(common_frames(i)) = mat2cell(x_opt, 2);

        % Then using the optimized x and y estimates, optimize for velocity
        [x_opt_final, v_x_initial_suboptimal, v_y_initial_suboptimal, resnorm_final] = optimization_range_doppler_angle(true, centroids_r1_matched(index, :), ...
                                                   centroids_r2_matched(index, :), range_resolution, ...
                                                   spatial_angle_resolution, ...
                                                   doppler_resolution, x_opt(1), x_opt(2), ...
                                                   calibration_dict_2_1, calibration_dict_1_2);

        x_opt_dict_r_d_a(common_frames(i)) = mat2cell(x_opt_final, 4);

        % Visualize Posterior Distribution for range angle
        [x_mean, y_mean, cov_matrix] = visualize_range_angle_posterior_monte_carlo(x_opt_final, centroids_r1_matched(index, :), ...
                                    centroids_r2_matched(index, :), range_resolution, spatial_angle_resolution, doppler_resolution, ...
                                    calibration_dict_2_1, calibration_dict_1_2, common_frames(i));

        dict = dictionary;
        dict('Mean') = mat2cell([x_mean; y_mean], 2);
        dict('Covariance') = mat2cell(cov_matrix, 2);

        pos_gaussian_dict(common_frames(i)) = dict;

        disp('One-Shot position fusion estimates');
        disp(['X : ', num2str(x_mean), ' Y : ', num2str(y_mean)]);
        disp('Covariance Matrix : ');
        disp(cov_matrix);

        % Visualize Doppler Posterior 
        [v_x_mean, v_y_mean, cov_matrix] = visualize_doppler_posterior_monte_carlo(x_opt_final, centroids_r1_matched(index, :), ...
                                    centroids_r2_matched(index, :), range_resolution, spatial_angle_resolution, doppler_resolution, ...
                                    calibration_dict_2_1, calibration_dict_1_2, common_frames(i));

        dict = dictionary;
        dict('Mean') = mat2cell([v_x_mean; v_y_mean], 2);
        dict('Covariance') = mat2cell(cov_matrix, 2);

        velocity_gaussian_dict(common_frames(i)) = dict;

        disp('One-Shot velocity fusion estimates');
        disp(['X : ', num2str(v_x_mean), ' Y : ', num2str(v_y_mean)]);
        disp('Covariance Matrix : ');
        disp(cov_matrix);

        dict_1 = r1_detection_dict(common_frames(i));
        tracks_1 = dict_1('tracks');

        dict_2 = r2_detection_dict(common_frames(i));
        tracks_2 = dict_2('tracks');

        %% Plot Overlayed Centroids after doing Hungarian Matching 
        %% (Ghost Target Elimination check)
        %{
        overlayed_plot_dict = plot_overlayed_centroids(overlayed_plot_dict, ...
                                            centroids_r1_matched(index, :), ...
                                            centroids_r2_transformed_matched(index, :), ...
                                            5, common_frames(i), true);
        %}

        Frame = getframe(gcf);
        writeVideo(vw,Frame);
        pause(0.001);

        vel_x_opt_dict(common_frames(i)) = x_opt_final(3);
        vel_y_opt_dict(common_frames(i)) = x_opt_final(4);
        x_opt_dict(common_frames(i)) = x_opt_final(1);
        y_opt_dict(common_frames(i)) = x_opt_final(2);

        if ~isempty(tracks_1{1}) & ~isempty(tracks_2{1})

            rmse_frames = rmse_frames + 1;

            tracks_state_1 = tracks_1{1}.State;

            tracks_state_2 = tracks_2{1}.State;

            [v_x_r2_rotated, v_y_r2_rotated] = rotate_velocity_to_radar_frame(tracks_state_2(2), tracks_state_2(4), ...
                                                     calibration_dict_2_1('Relative Orientation'));

            dict_fused = track_fusion_dict(common_frames(i));
            tracks_list = dict_fused('tracks');
    
            tracks_fused = tracks_list{1}(end);
            
            tracks_state_fused = tracks_fused.State;

            % Calculate RMSE errors for both position and velocity

            % X optimized - (x, y, v_x, v_y)
            % EKF estimates - (x, v_x, y, v_y)
            position_error = sqrt((tracks_state_1(1) - x_opt_final(1))^2 + (tracks_state_1(3) - x_opt_final(2))^2);
            rmse_position = rmse_position + position_error^2;
            velocity_error = sqrt((tracks_state_1(2) - x_opt_final(3))^2 + (tracks_state_1(4) - x_opt_final(4))^2);

            rmse_velocity = rmse_velocity + velocity_error^2;


            % Populate to dictionaries
            position_error_dict(common_frames(i)) = position_error;
            velocity_error_dict(common_frames(i)) = velocity_error;

            % Velocities

            velocity_x_dict = dictionary;
            velocity_y_dict = dictionary;

            velocity_x_dict('Optimized') = x_opt_final(3);
            velocity_x_dict('EKF-State-R1') = tracks_state_1(2);
            velocity_x_dict('EKF-State-R2-R1') = v_x_r2_rotated;
            velocity_x_dict('Suboptimal-Estimate') = v_x_initial_suboptimal;
            velocity_x_dict('Track-To-Track-Fusion') = tracks_state_fused(2);

            velocity_y_dict('Optimized') = x_opt_final(4);
            velocity_y_dict('EKF-State-R1') = tracks_state_1(4);
            velocity_y_dict('EKF-State-R2-R1') = v_y_r2_rotated;
            velocity_y_dict('Suboptimal-Estimate') = v_y_initial_suboptimal;
            velocity_y_dict('Track-To-Track-Fusion') = tracks_state_fused(4);

            v_x_dict(common_frames(i)) = velocity_x_dict;
            v_y_dict(common_frames(i)) = velocity_y_dict;

            % Positions

            position_x_dict = dictionary;
            position_y_dict = dictionary;

            [x_r2_transformed, y_r2_transformed] = rotate_coordinates_to_radar_frame(tracks_state_2(1), tracks_state_2(3), ...
                                 calibration_dict_2_1('Relative Orientation'), ...
                                 calibration_dict_2_1('Relative Position'));

            position_x_dict('Optimized') = x_opt_final(1);
            position_x_dict('EKF-State-R1') = tracks_state_1(1);
            position_x_dict('EKF-State-R2-R1') = x_r2_transformed;
            position_x_dict('Track-To-Track-Fusion') = tracks_state_fused(1);

            position_y_dict('Optimized') = x_opt_final(2);
            position_y_dict('EKF-State-R1') = tracks_state_1(3);
            position_y_dict('EKF-State-R2-R1') = y_r2_transformed;
            position_y_dict('Track-To-Track-Fusion') = tracks_state_fused(3);

            x_dict(common_frames(i)) = position_x_dict;
            y_dict(common_frames(i)) = position_y_dict;
            
        end
    end
end

rmse_position = sqrt(rmse_position / rmse_frames);
rmse_velocity = sqrt(rmse_velocity / rmse_frames);

disp(['RMSE - Position : ', num2str(rmse_position)]);
disp(['RMSE - Velocity : ', num2str(rmse_velocity)]);

hold off;
close(vw);

save('v_x_dict.mat', 'v_x_dict');
save('v_y_dict.mat', 'v_y_dict');

save('x_dict.mat', 'x_dict');
save('y_dict.mat', 'y_dict');

save('vel_x_opt_dict.mat', 'vel_x_opt_dict');
save('vel_y_opt_dict.mat', 'vel_y_opt_dict');

save('x_opt_dict.mat', 'x_opt_dict');
save('y_opt_dict.mat', 'y_opt_dict');

save('position_error_dict.mat', 'position_error_dict');
save('velocity_error_dict.mat', 'velocity_error_dict');

save('pos_gaussian_dict.mat', 'pos_gaussian_dict');
save('velocity_gaussian_dict.mat', 'velocity_gaussian_dict');

close all;

%==========================================================================
% FUNCTION : get_centroid_associations
% Get the best matching pairs between centroids from R1 and R2 perspectives
%==========================================================================
function [centroids_r1_matched, centroids_r2_matched, centroids_r2_transformed_matched] = get_centroid_associations(centroids_r1, centroids_r2, ...
                                    calibration_dict, association_threshold)
    cost_matrix = zeros(size(centroids_r1, 1), size(centroids_r2, 1));

    centroids_r1_matched = [];
    centroids_r2_matched = [];
    centroids_r2_transformed_matched = [];
    centroids_r2_transformed = centroids_r2;

    relative_position = calibration_dict('Relative Position');
    relative_orientation = calibration_dict('Relative Orientation');

    for i=1:size(centroids_r1, 1)
        centroid_r1 = centroids_r1(i, :);
        [x_r1, y_r1] = pol2cart(deg2rad(centroid_r1(3)), centroid_r1(1));
        for j=1:size(centroids_r2, 1)
            centroid_r2 = centroids_r2(j, :);
            [x_r2, y_r2] = pol2cart(deg2rad(centroid_r2(3)), centroid_r2(1));

            [x_r2_transformed, y_r2_transformed] = rotate_coordinates_to_radar_frame(x_r2, y_r2, ...
                                  relative_orientation, relative_position);

            [theta_r2_transformed, r_r2_transformed] = cart2pol(x_r2_transformed, y_r2_transformed);
            theta_r2_transformed = rad2deg(theta_r2_transformed);

            centroids_r2_transformed(j, 1) = r_r2_transformed;
            centroids_r2_transformed(j, 3) = theta_r2_transformed;

            cost_matrix(i, j) = pdist2([x_r1, y_r1], ...
                                     [x_r2_transformed, y_r2_transformed]);
        end
    end

    % Use Hungarian Algorithm
    [assignments, ~, ~] = assignmunkres(cost_matrix, association_threshold);

    for i=1:size(assignments, 1)
        centroids_r1_matched = [centroids_r1_matched; centroids_r1(assignments(i, 1), :)];
        centroids_r2_matched = [centroids_r2_matched; centroids_r2(assignments(i, 2), :)];
        centroids_r2_transformed_matched = [centroids_r2_transformed_matched; centroids_r2_transformed(assignments(i, 2), :)];
    end
end

%==========================================================================
% FUNCTION : rotate_coordinates_to_radar_frame
% Rotate the coordinates of a point between radar perspectives
%==========================================================================
function [x_transformed, y_transformed] = rotate_coordinates_to_radar_frame(x, y, ...
                                                     rotation, translation)
    complex_coordinate = x + 1j*y;
    transformed_complex_coordinate = complex_coordinate*exp(1j*deg2rad(rotation)) + translation;
    x_transformed = real(transformed_complex_coordinate);
    y_transformed = imag(transformed_complex_coordinate);
end

%==========================================================================
% FUNCTION : rotate_velocity_to_radar_frame
% Rotate the velocity of a point between radar perspectives
%==========================================================================
function [v_x_transformed, v_y_transformed] = rotate_velocity_to_radar_frame(v_x, v_y, ...
                                                     rotation)
    complex_velocity = v_x + 1j*v_y;
    transformed_complex_velocity = complex_velocity*exp(1j*deg2rad(rotation));
    v_x_transformed = real(transformed_complex_velocity);
    v_y_transformed = imag(transformed_complex_velocity);
end