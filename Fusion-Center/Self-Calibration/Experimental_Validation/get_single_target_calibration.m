% FUNCTION - get_single_target_calibration
% Get single target calibration result for a two radar setup

function [relative_position, relative_orientation, track_mapping, normalized_residual] = get_single_target_calibration(trajectory_combination_dict)
    complex_trajectory_estimate_array = cell2mat(values(trajectory_combination_dict));

    track_mapping = cell2mat(keys(trajectory_combination_dict));

    trajectory_size = size(complex_trajectory_estimate_array);
    num_radars = trajectory_size(1);
    num_iterations = trajectory_size(2);

    [P_optimal_array, theta_optimal_array, residual_array] = get_closed_form_solution(complex_trajectory_estimate_array, ...
                                               num_radars, num_iterations);

    relative_position = P_optimal_array(1, 2);
    relative_orientation = theta_optimal_array(1, 2);
    normalized_residual = residual_array(1, 2)/num_iterations;

    disp('Relative position and orientation of the radar network');
    disp(P_optimal_array);
    disp(theta_optimal_array);
    disp(residual_array/num_iterations);
end