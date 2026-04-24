function [x_opt, resnorm] = optimization_range_doppler(detected_centroid_r1, ...
                      detected_centroid_r2, r_res, doppler_res, calibration_dict_2_1, calibration_dict_1_2)

    relative_position_2_1 = calibration_dict_2_1('Relative Position');
    relative_orientation_2_1 = calibration_dict_2_1('Relative Orientation');

    relative_position_1_2 = calibration_dict_1_2('Relative Position');
    relative_orientation_1_2 = calibration_dict_1_2('Relative Orientation');

    phi_2_1 = deg2rad(relative_orientation_2_1);

    % Check if points to correct value;
    R_1 = detected_centroid_r1(1);
    R_2 = detected_centroid_r2(1);
    D_1 = detected_centroid_r1(2);
    D_2 = detected_centroid_r2(2);

    sigma_r = r_res/2;
    sigma_doppler = doppler_res/2;

    [x_initial_r1, y_initial_r1] = pol2cart(deg2rad(detected_centroid_r1(3)), ...
                                      detected_centroid_r1(1));

    [x_initial_r2, y_initial_r2] = pol2cart(deg2rad(detected_centroid_r2(3)), ...
                                      detected_centroid_r2(1));

    [x_initial_r2_r1, y_initial_r2_r1] = rotate_coordinates_to_radar_frame(x_initial_r2, y_initial_r2, ...
                          relative_orientation_2_1, relative_position_2_1);

    x_initial = (x_initial_r1 + x_initial_r2_r1)/2;
    y_initial = (y_initial_r1 + y_initial_r2_r1)/2;

    [x_initial_rotated_r2, y_initial_rotated_r2] = rotate_coordinates_to_radar_frame(x_initial, y_initial, ...
                                relative_orientation_1_2, relative_position_1_2);

    [theta_r1, ~] = cart2pol(x_initial, y_initial);
    [theta_r2, ~] = cart2pol(x_initial_rotated_r2, y_initial_rotated_r2);

    % Just some initial suboptimal estimate of the velocities
    v_x_initial = (D_2 * cos(phi_2_1 + theta_r2) + D_1 * cos(theta_r1))/2;
    v_y_initial = (D_1 * sin(theta_r1) + D_2 * sin(phi_2_1 + theta_r2))/2;

    x_0 = [x_initial; y_initial; v_x_initial; v_y_initial];

    options = optimoptions('lsqnonlin', 'Algorithm', 'levenberg-marquardt');

    % Keep velocity values between -3:3 m/s
    lb = [-inf; -inf; -4; -4];
    ub = [inf; inf; 4; 4];

    [x_opt, resnorm] = lsqnonlin(@(x) combined_residuals_range_doppler(x, ...
                            R_1, R_2, D_1, D_2, ...
                            sigma_r, sigma_doppler, ...
                            relative_position_2_1, relative_orientation_2_1, ...
                            relative_position_1_2, relative_orientation_1_2), x_0, ...
                            [], [], options);

end

function [x_transformed, y_transformed] = rotate_coordinates_to_radar_frame(x, y, ...
                                                     rotation, translation)
    complex_coordinate = x + 1j*y;
    transformed_complex_coordinate = complex_coordinate*exp(1j*deg2rad(rotation)) + translation;
    x_transformed = real(transformed_complex_coordinate);
    y_transformed = imag(transformed_complex_coordinate);
end

function residuals = combined_residuals_range_doppler(x, R_1, R_2, ...
                                        D_1, D_2, sigma_r, sigma_doppler,...
                                  relative_position_2_1, relative_orientation_2_1, ...
                                  relative_position_1_2, relative_orientation_1_2)

    phi_1_2 = deg2rad(relative_orientation_1_2);
    phi_2_1 = deg2rad(relative_orientation_2_1);

    sigma_x = 1;
    sigma_y = 1;
    sigma_v_x = 10;
    sigma_v_y = 10;

    x_2_1 = [real(relative_position_2_1) imag(relative_position_2_1)];
    x_1_1 = [0 0];

    x_1_2 = [real(relative_position_1_2) imag(relative_position_1_2)];
    x_2_2 = [0 0];

    r_1 = pdist2([x(1) x(2)], x_1_1);
    r_2 = pdist2([x(1) x(2)], x_2_1);

    % Doppler Calculations
    d_1 = (x(3)*(x(1) - x_1_1(1)) + x(4)*(x(2) - x_1_1(2)))/r_1;
    d_2 = (x(3)*(x(1) - x_2_1(1)) + x(4)*(x(2) - x_2_1(2)))/r_2;

    % Add regularizer
    reg_1 = x(1)/(sqrt(2));
    reg_2 = x(2)/(sqrt(2));

    reg_3 = x(3)/(sqrt(2));
    reg_4 = x(4)/(sqrt(2));

    % Functions
    f_1 = (R_1 - r_1)/sigma_r;
    f_2 = (R_2 - r_2)/sigma_r;
    f_3 = (D_1 - d_1)/sigma_doppler;
    f_4 = (D_2 - d_2)/sigma_doppler;
    f_5 = reg_1/sigma_x;
    f_6 = reg_2/sigma_y;
    f_7 = reg_3/sigma_v_x;
    f_8 = reg_4/sigma_v_y;

    residuals = [f_1; f_2; f_3; f_4; f_5; f_6; f_7; f_8];
end