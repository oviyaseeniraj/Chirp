function [v_x_opt, v_y_opt] = linear_lsq_velocity_opt(theta_array, relative_orientation_array, y)
    %{
    [sin theta1 cos theta1;
     sin theta2 cos theta2];

    Changed to 
    [sin theta1-phi1_1 cos theta1-phi1_1;
     sin theta2-phi2_1 cos theta2-phi2_1];
    %}

    A_angles = theta_array - relative_orientation_array;
    A = [sin(deg2rad(A_angles)) cos(deg2rad(A_angles))];

    [x_opt, ~] = lsqlin(A, y, [], []);

    v_x_opt = x_opt(1);
    v_y_opt = x_opt(2);
end