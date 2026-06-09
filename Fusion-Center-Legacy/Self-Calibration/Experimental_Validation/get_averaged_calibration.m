%==========================================================================
% Get averaged calibration info for multi-radar scenario
function [P_optimal_avg_array, theta_optimal_avg_array] = get_averaged_calibration(num_radars, P_optimal_array, theta_optimal_array)

    P_optimal_avg_array = zeros([num_radars num_radars]);
    theta_optimal_avg_array = zeros([num_radars num_radars]);
    for ref_radar_index=1:num_radars
        for i=1:num_radars
            for k=1:num_radars
                P_optimal_avg_array(ref_radar_index, i) = P_optimal_avg_array(ref_radar_index, i) + (P_optimal_array(k, i)*exp(1j*deg2rad(theta_optimal_array(ref_radar_index, k)))) + P_optimal_array(ref_radar_index, k);
                theta_optimal_avg_array(ref_radar_index, i) = theta_optimal_avg_array(ref_radar_index, i) + theta_optimal_array(k, i) + theta_optimal_array(ref_radar_index, k);
            end
            P_optimal_avg_array(ref_radar_index, i) = P_optimal_avg_array(ref_radar_index, i)/num_radars;
            theta_optimal_avg_array(ref_radar_index, i) = theta_optimal_avg_array(ref_radar_index, i)/num_radars;
        end
    end
end