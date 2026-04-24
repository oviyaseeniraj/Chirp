function [x_opt, resnorm] = optimization_range_angle(detected_centroid_r1, ...
                      detected_centroid_r2, r_res, w_res, calibration_dict_2_1, calibration_dict_1_2)
    relative_position_2_1 = calibration_dict_2_1('Relative Position');
    relative_orientation_2_1 = calibration_dict_2_1('Relative Orientation');

    relative_position_1_2 = calibration_dict_1_2('Relative Position');
    relative_orientation_1_2 = calibration_dict_1_2('Relative Orientation');

    % Check if points to correct value;
    R_1 = detected_centroid_r1(1);
    R_2 = detected_centroid_r2(1);
    W_1 = pi*sin(deg2rad(detected_centroid_r1(3)));
    W_2 = pi*sin(deg2rad(detected_centroid_r2(3)));

    sigma_r = r_res/2;
    sigma_w = w_res/2;

    [x_initial_r1, y_initial_r1] = pol2cart(deg2rad(detected_centroid_r1(3)), ...
                                      detected_centroid_r1(1));

    [x_initial_r2, y_initial_r2] = pol2cart(deg2rad(detected_centroid_r2(3)), ...
                                      detected_centroid_r2(1));

    [x_initial_r2_r1, y_initial_r2_r1] = rotate_coordinates_to_radar_frame(x_initial_r2, y_initial_r2, ...
                          relative_orientation_2_1, relative_position_2_1);

    x_initial = (x_initial_r1 + x_initial_r2_r1)/2;
    y_initial = (y_initial_r1 + y_initial_r2_r1)/2;

    x_0 = [x_initial; y_initial];

    options = optimoptions('lsqnonlin', 'Algorithm', 'levenberg-marquardt');

    [x_opt, resnorm] = lsqnonlin(@(x) combined_residuals_range_angle(x, ...
                            R_1, R_2, W_1, W_2, sigma_r, sigma_w, ...
                            relative_position_2_1, relative_orientation_2_1, ...
                            relative_position_1_2, relative_orientation_1_2), x_0, ...
                            [], [], options);

end


function residuals = combined_residuals_range_angle(x, R_1, R_2, W_1, W_2, ...
                        sigma_r, sigma_w, relative_position_2_1, relative_orientation_2_1, ...
                        relative_position_1_2, relative_orientation_1_2)

    % Here 1_2 means for Radar 1 relative to Radar 2 and vice versa
    % TO check for correctness
    phi_1_2 = deg2rad(relative_orientation_1_2);
    phi_2_1 = deg2rad(relative_orientation_2_1);

    x_2_1 = [real(relative_position_2_1) imag(relative_position_2_1)];
    x_1_1 = [0 0];

    x_1_2 = [real(relative_position_1_2) imag(relative_position_1_2)];
    x_2_2 = [0 0];

    r_1 = pdist2([x(1) x(2)], x_1_1);
    r_2 = pdist2([x(1) x(2)], x_2_1);
    w_1 = pi*(x(2) - x_1_1(2))/r_1;
    %w_2 = pi*(x(2)*cos(phi_1_2) + x(1)*sin(phi_1_2) + x_1_2(2))/r_2;
    w_2 = pi*((x(1)-x_2_1(1))*sin(phi_2_1) + (x(2)-x_2_1(2))*cos(phi_2_1))/r_2;

    f_1 = (R_1 - r_1)/sigma_r;
    f_2 = (R_2 - r_2)/sigma_r;
    f_3 = (W_1 - w_1)/sigma_w;
    f_4 = (W_2 - w_2)/sigma_w;

    residuals = [f_1; f_2; f_3; f_4];
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