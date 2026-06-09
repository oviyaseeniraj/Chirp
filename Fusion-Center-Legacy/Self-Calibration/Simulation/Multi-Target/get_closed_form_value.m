function [P_array, theta_array, P_optimal_array, theta_optimal_array, residual_array] = get_closed_form_value(complex_radar_position_array, ...
            radar_orientation_array, complex_trajectory_estimate_array, ...
            num_radars, num_iterations)

    % Get the actual relative positions and orientations of the Radars wrt each
    % other
    P_array = zeros([num_radars num_radars]);
    theta_array = zeros([num_radars num_radars]);
    
    for i=1:num_radars
        for k=1:num_radars
            P_array(i, k) = (complex_radar_position_array(k) - complex_radar_position_array(i))*exp(-1j*deg2rad(radar_orientation_array(i)));
            theta_array(i, k) = radar_orientation_array(k) - radar_orientation_array(i);
        end
    end
    
    P_optimal_array = zeros([num_radars num_radars]);
    theta_optimal_array = zeros([num_radars num_radars]);
    residual_array = zeros([num_radars num_radars]);
    
    for i=1:num_radars
        for k=1:num_radars
            z_i_hat_t = complex_trajectory_estimate_array(i, :);
            z_k_hat_t = complex_trajectory_estimate_array(k, :);
            z_i_hat_t_mean = mean(z_i_hat_t);
            z_k_hat_t_mean = mean(z_k_hat_t);
    
            val = 0;
            for t=1:num_iterations
                val = val + (z_k_hat_t(t) - z_k_hat_t_mean)*(conj(z_i_hat_t(t) - z_k_hat_t_mean));
            end
    
            phi = atan2(imag(val), real(val));
            theta_optimal_array(i, k) = rad2deg(-phi);
            P_optimal_array(i, k) = z_i_hat_t_mean - exp(-1j*phi)*z_k_hat_t_mean;
    
            sum = 0;
            for t=1:num_iterations
                sum = sum + (abs(z_k_hat_t(t) - z_k_hat_t_mean))^2 + (abs(z_i_hat_t(t) - z_i_hat_t_mean))^2;
            end
    
            sum = sum - 2*abs(val);
            residual_array(i, k) = sum;
        end
    end

end