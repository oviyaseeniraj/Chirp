clc; clear; close all;

output_video_file_name = 'May17_cfg1_straight_noRangeFT.avi';

load('Data/May17_cfg1_radar1_straight_noRangeFT_detection_data.mat', 'prev_plot_dict');
r1_detection_dict = prev_plot_dict;

load('Data/may17_cfg1_radar2_straight_noRangeFT_detection_data.mat', 'prev_plot_dict');
r2_detection_dict = prev_plot_dict;

% Calibration dicts contain the relative calibration data
% calibration_dict_2_1.mat - Radar 2 w.r.t Radar 1
% calibration_dict_1_2.mat - Radar 1 w.r.t Radar 2

load('calibration_dict_cfg_1_2_1_new.mat', 'calibration_cfg_1_2_1_new');

calibration_dict_2_1 = calibration_cfg_1_2_1_new;

common_frames = intersect(keys(r1_detection_dict), keys(r2_detection_dict));

association_threshold = 0.25;

overlayed_plot_dict = dictionary;

output_video_path = strcat('Videos/', output_video_file_name);
% 
figure();
vw = VideoWriter(output_video_path);
vw.Quality = 100;
vw.FrameRate = 20;
open(vw);

for i=1:length(common_frames)
    r1_dict = r1_detection_dict(common_frames(i));
    r2_dict = r2_detection_dict(common_frames(i));

    centroids_r1 = cell2mat(r1_dict('centroids'));
    centroids_r2 = cell2mat(r2_dict('centroids'));

    [centroids_r1_matched, centroids_r2_matched, centroids_r2_transformed_matched] = get_centroid_associations(centroids_r1, ...
                centroids_r2, calibration_dict_2_1, association_threshold);

    for index=1:size(centroids_r1_matched, 1)
        overlayed_plot_dict = plot_overlayed_centroids(overlayed_plot_dict, ...
                                            centroids_r1_matched(index, :), ...
                                            centroids_r2_transformed_matched(index, :), ...
                                            10, common_frames(i), true);

        Frame = getframe(gcf);
        writeVideo(vw,Frame);
        pause(0.001);
    end

    if common_frames(i) == 64
        disp('Debug')
    end
end

hold off;
close(vw);

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