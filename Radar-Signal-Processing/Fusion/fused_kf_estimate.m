clear; clc; close all;

load('x_opt_dict.mat', 'x_opt_dict');
load('y_opt_dict.mat', 'y_opt_dict');
load('vel_x_opt_dict.mat', 'vel_x_opt_dict');
load('vel_y_opt_dict.mat', 'vel_y_opt_dict');

fused_kf_dict = dictionary;

frame_list = keys(x_opt_dict);
measurement = [];

prev_plot_dict = dictionary;

tracks = [];

initial_frame = frame_list(1);
final_frame = frame_list(length(frame_list));

i = 1;

for index=initial_frame:final_frame
    if frame_list(i) ~= index
        meas = [NaN NaN NaN NaN];
    else
        x_val = x_opt_dict(frame_list(i));
        v_x_val = vel_x_opt_dict(frame_list(i));
        y_val = y_opt_dict(frame_list(i));
        v_y_val = vel_y_opt_dict(frame_list(i));
        meas = [x_val v_x_val y_val v_y_val];

        i = i + 1;
    end
    measurement = [measurement; meas];
end

dt = 1; % Time step
stateTransitionModel = [1 dt 0 0;
                        0 1  0 0;
                        0 0  1 dt;
                        0 0  0 1];

measurementModel = eye(4);

% Define process noise and measurement noise
% Keep the same process noise as in the individual EKFs
processNoise = 0.1 * eye(4);  % Process noise covariance

% Keep the same noise variance as the one set for the optimization
measurementNoise = [1 0 0 0; 0 100 0 0; 0 0 1 0; 0 0 0 100]; % Measurement noise covariance

% Initialize state and covariance
initialState = [0; 0; 0; 0]; % Initial state [x; v_x; y; v_y]
initialCovariance = eye(4);

% Create trackingKF object
kf = trackingKF('StateTransitionModel', stateTransitionModel, ...
                'MeasurementModel', measurementModel, ...
                'ProcessNoise', processNoise, ...
                'MeasurementNoise', measurementNoise, ...
                'State', initialState, ...
                'StateCovariance', initialCovariance);


output_video_path = strcat('Videos/', 'Fused_Tracks.avi');
% 
figure();
vw = VideoWriter(output_video_path);
vw.Quality = 100;
vw.FrameRate = 20;
open(vw);

frame_idx = 0;

% Loop through measurements and update the Kalman filter
for i = 1:size(measurement, 1)

    % Predict the state
    predict(kf);
    
    % Check if measurement is available
    if all(~isnan(measurement(i, :)))
        % Correct the state with the available measurement
        correctedState = correct(kf, measurement(i, :)');

        frame_idx = frame_idx + 1;
        fused_kf_dict(frame_list(frame_idx)) = mat2cell(correctedState, 4);

    else
        % If measurement is missing, use predicted state as estimate
        correctedState = kf.State;
        disp(['No measurement for Step ', num2str(i), '. Using prediction.']);
    end

    stateCovariance = kf.StateCovariance;
    disp(['StateCovariance', mat2str(stateCovariance')]);
    
    % Display the estimated state
    disp(['Estimated State at Step ', num2str(i), ': ', mat2str(correctedState')]);

    track = struct('State', correctedState', 'StateCovariance', stateCovariance', 'TrackID', 1, 'Age', i, 'UpdateTime', 1);

    objTrack = objectTrack(...
        'TrackID', track.TrackID, ...
        'State', track.State, ...
        'StateCovariance', track.StateCovariance, ...
        'ObjectClassID', 0, ... % Set to 0 if class is unknown
        'SourceIndex', 1, ...
        'Age', track.Age, ...
        'UpdateTime', track.UpdateTime ...
    );

    prev_plot_dict = plot_tracks(prev_plot_dict, track, 10, i, true);

    Frame = getframe(gcf);
    writeVideo(vw,Frame);
    pause(0.001);
end

hold off;
close(vw);

save('fused_kf_dict.mat', 'fused_kf_dict');