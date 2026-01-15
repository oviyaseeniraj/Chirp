function filter = ekf_custom(detection)
    filter_3D = initcvekf(detection);

    state = filter_3D.State(1:4);

    state_covariance = filter_3D.StateCovariance(1:4, 1:4);

    % Reduce doppler uncertainty

    %{
    vel_cov = state_covariance([2 4],[2 4]);
    [v, d] = eig(vel_cov);
    D = diag(d);
    D(2) = 1;
    state_covariance([2 4],[2 4]) = v*diag(D)*v';
    %}

    Q = eye(4) * 0.025;

    % Dont trust the measurements in Y, trust only the measurements in X
    % Therefore, decrease process noise in Y, and increase it in X
    
    %{
    % Use X-0.3,Y-0.1 for straight trajectories, and X-0.2, Y-0.2 for
    % random trajectories
    sigma_acc_x = 0.25;
    sigma_acc_y = 0.25;
    var_acc_x = sigma_acc_x^2;
    var_acc_y = sigma_acc_y^2;
    Q = [1/4*var_acc_x,  1/2*var_acc_x,   0,       0;
         1/2*var_acc_x,  1*var_acc_x,     0,       0;
         0,      0,   1/4*var_acc_y,     1/2*var_acc_y;
         0,      0,   1/2*var_acc_y,     1*var_acc_y];
    %}

    filter = trackingEKF(State = state,...
    StateCovariance = state_covariance,...
    StateTransitionFcn = @constvel,...
    StateTransitionJacobianFcn = @constveljac,...
    HasAdditiveProcessNoise = true,...
    MeasurementFcn = @cvmeas,...
    MeasurementJacobianFcn = @cvmeasjac,...
    ProcessNoise = Q,...
    MeasurementNoise = detection.MeasurementNoise, ...
    EnableSmoothing=true);

end