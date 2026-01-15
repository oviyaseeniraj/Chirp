function [v_x_mean, v_y_mean, covariance_matrix] = visualize_doppler_posterior_monte_carlo(x_opt, detected_centroid_r1, ...
                      detected_centroid_r2, r_res, w_res, doppler_res, calibration_dict_2_1, calibration_dict_1_2, frame_idx)

    relative_position_2_1 = calibration_dict_2_1('Relative Position');
    relative_orientation_2_1 = calibration_dict_2_1('Relative Orientation');

    relative_position_1_2 = calibration_dict_1_2('Relative Position');
    relative_orientation_1_2 = calibration_dict_1_2('Relative Orientation');

    phi_2_1 = deg2rad(relative_orientation_2_1);

    % Check if points to correct value;
    % Get the measurement values
    R_1 = detected_centroid_r1(1);
    R_2 = detected_centroid_r2(1);
    W_1 = pi*sin(deg2rad(detected_centroid_r1(3)));
    W_2 = pi*sin(deg2rad(detected_centroid_r2(3)));
    D_1 = detected_centroid_r1(2);
    D_2 = detected_centroid_r2(2);

    sigma_r = r_res/2;
    sigma_w = w_res/2;
    sigma_doppler = doppler_res/2;

    sigma_v_x = 3.5;
    sigma_v_y = 3.5;
    sigma_x = 3;
    sigma_y = 3;

    v_x_res = 0.01;
    v_y_res = 0.01;

    del_v_x_arr = -sigma_v_x:v_x_res:sigma_v_x;
    del_v_y_arr = -sigma_v_y:v_y_res:sigma_v_y;

    %======================================================================
    [v_y_mesh_grid, v_x_mesh_grid] = meshgrid(del_v_y_arr, del_v_x_arr);

    x = x_opt(1);
    y = x_opt(2);

    v_x = x_opt(3) + v_x_mesh_grid;
    v_y = x_opt(4) + v_y_mesh_grid;

    phi_1_2 = deg2rad(relative_orientation_1_2);
    phi_2_1 = deg2rad(relative_orientation_2_1);

    x_2_1 = [real(relative_position_2_1) imag(relative_position_2_1)];
    x_1_1 = [0 0];
        
    x_1_2 = [real(relative_position_1_2) imag(relative_position_1_2)];
    x_2_2 = [0 0];

    r_1 = pdist2([x y], x_1_1);
    r_2 = pdist2([x y], x_2_1);

    w_1 = pi*(y - x_1_1(2))/r_1;
    %w_2 = pi*(y*cos(phi_1_2) + x*sin(phi_1_2) + x_1_2(2))/r_2;
    w_2 = pi*((x-x_2_1(1))*sin(phi_2_1) + (y-x_2_1(2))*cos(phi_2_1))/r_2;

    % Doppler Calculations
    d_1 = (v_x*(x - x_1_1(1)) + v_y*(y - x_1_1(2)))/r_1;
    d_2 = (v_x*(x - x_2_1(1)) + v_y*(y - x_2_1(2)))/r_2;
        
    % Add regularizer
    reg_1 = x/(sqrt(2));
    reg_2 = y/(sqrt(2));
    reg_3 = v_x/(sqrt(2));
    reg_4 = v_y/(sqrt(2));

    % Functions
    f_1 = (R_1 - r_1)/sigma_r;
    f_2 = (R_2 - r_2)/sigma_r;
    f_3 = (W_1 - w_1)/sigma_w;
    f_4 = (W_2 - w_2)/sigma_w;
    f_5 = (D_1 - d_1)/sigma_doppler;
    f_6 = (D_2 - d_2)/sigma_doppler;
    f_7 = reg_1/sigma_x;
    f_8 = reg_2/sigma_y;
    f_9 = reg_3/sigma_v_x;
    f_10 = reg_4/sigma_v_y;

    visualization_arr = exp(-(f_1.^2 + f_2.^2 + f_3.^2 + f_4.^2 + f_5.^2 + f_6.^2 + f_7.^2 + f_8.^2 + f_9.^2 + f_10.^2));
    visualization_arr = visualization_arr/(sum(visualization_arr(:)));

    surf(del_v_x_arr, del_v_y_arr, visualization_arr);
    title(['Velocity Posterior, Frame - ', num2str(frame_idx)]);

    xlabel('V_x(m/s)');
    ylabel('V_y(m/s)');
    xlim([-sigma_v_x, sigma_v_x]);
    ylim([-sigma_v_y, sigma_v_y]);

    % Use a built-in colormap
    colormap(jet);
    %colorbar; % Add a colorbar to see the color scale
    
    % Control mesh style
    shading interp; % Smoothly shade colors

    pause(0.1);

    v_x_arr_mesh_flat = v_x_mesh_grid(:);
    v_y_arr_mesh_flat = v_y_mesh_grid(:);

    visualization_arr_flat = visualization_arr(:);
    visualization_arr_flat = visualization_arr_flat/sum(visualization_arr_flat);

    %% Draw Monte Carlo samples using randsample (with probability weights)
    N_MC = 1000;  % number of samples
    
    % randsample(k, n, true, w) samples n times from 1:k with replacement, 
    % using weights w. Indices returned are in idxSamples.
    idx_samples = randsample(numel(visualization_arr_flat), N_MC, true, visualization_arr_flat);

    %% Fetch the sampled X, Y in parallel (parfor)
    
    v_x_samples = v_x_arr_mesh_flat(idx_samples);
    v_y_samples = v_y_arr_mesh_flat(idx_samples);
    
    %% Compute the mean manually
    % (Population mean)
    v_x_mean = sum(v_x_samples) / N_MC;
    v_y_mean = sum(v_y_samples) / N_MC;
    
    %% Compute the covariance manually (population version: denominator = N_MC)
    % We'll do the centering in parallel to speed up large N_MC
    
    % First, compute the deviations in parallel

    delta_v_x = v_x_samples - v_x_mean;
    delta_v_y = v_y_samples - v_y_mean;
    
    % Sum of squares and cross-terms (single-threaded sum is fine here)
    sum_V_XX = sum(delta_v_x.^2);        % sum of (x - mean_x_est)^2
    sum_V_YY = sum(delta_v_y.^2);        % sum of (y - mean_y_est)^2
    sum_V_XY = sum(delta_v_x .* delta_v_y);     % sum of (x - mean_x_est)*(y - mean_y_est)
    
    cov_v_xx  = sum_V_XX / N_MC;
    cov_v_yy  = sum_V_YY / N_MC;
    cov_v_xy = sum_V_XY / N_MC;
    
    covariance_matrix = [cov_v_xx,  cov_v_xy;
                         cov_v_xy, cov_v_yy];

end