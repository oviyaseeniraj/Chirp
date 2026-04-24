clc; clear; close all;

load('Data/apr0325_expb2_left_noRangeFT_detection_data.mat', 'prev_plot_dict');
r1_detection_dict = prev_plot_dict;

load('Data/apr0325_expb2_right_noRangeFT_detection_data.mat', 'prev_plot_dict');
r2_detection_dict = prev_plot_dict;

output_file_name = 'Data/apr0325_expb2_Single_Fused.mat';

prev_plot_dict = dictionary;

% Calibration dicts contain the relative calibration data
% calibration_dict_2_1.mat - Radar 2 w.r.t Radar 1
% calibration_dict_1_2.mat - Radar 1 w.r.t Radar 2

load('calibration_dict_Exp_1_2_1_90.mat', 'calibration_dict_Exp_1_2_1_90');

load('calibration_dict_Exp_1_1_2_90.mat', 'calibration_dict_Exp_1_1_2_90');

calibration_dict_2_1 = calibration_dict_Exp_1_2_1_90;
calibration_dict_1_2 = calibration_dict_Exp_1_1_2_90;

relative_position = calibration_dict_2_1('Relative Position');
relative_orientation = calibration_dict_2_1('Relative Orientation');

common_frames = intersect(keys(r1_detection_dict), keys(r2_detection_dict));

sigma_acc_x = 0.2;
sigma_acc_y = 0.2;
var_acc_x = sigma_acc_x^2;
var_acc_y = sigma_acc_y^2;
Q = [1/4*var_acc_x,  1/2*var_acc_x,   0,       0;
     1/2*var_acc_x,  1*var_acc_x,     0,       0;
     0,      0,   1/4*var_acc_y,     1/2*var_acc_y;
     0,      0,   1/2*var_acc_y,     1*var_acc_y];

figure();
vw = VideoWriter('Videos/Track-Track-Fusion-EA.avi');
vw.Quality = 100;
vw.FrameRate = 20;
open(vw);

for i = 1:length(common_frames)

    if common_frames(i) == 198
        disp('198');
    end

    r1_dict = r1_detection_dict(common_frames(i));
    r2_dict = r2_detection_dict(common_frames(i));
    tracks_1 = r1_dict('tracks');
    tracks_2 = r2_dict('tracks');
    
    if(~isempty(tracks_1{1}) & ~isempty(tracks_2{1}))

        % TO-DO change this for Multi-target tracks
        tracks_1 = {tracks_1{1}(1)};
        tracks_2 = {tracks_2{1}(1)};

        tracks_1_temp = tracks_1{1};
        tracks_2_temp = tracks_2{1};

        tracks_1_state = tracks_1{1}.State;
        tracks_2_state = tracks_2{1}.State;
        tracks_1_covariance = tracks_1{1}.StateCovariance;
        tracks_2_covariance = tracks_2{1}.StateCovariance;

        tracks_2_state_position = tracks_2_state([1 3]);
        tracks_2_state_velocity = tracks_2_state([2 4]);

        rotation = [cos(deg2rad(relative_orientation)) -sin(deg2rad(relative_orientation)); 
            sin(deg2rad(relative_orientation)) cos(deg2rad(relative_orientation))];

        translation = [real(relative_position); imag(relative_position)];

        tracks_2_state_position_transformed = rotation * tracks_2_state_position + translation;
        tracks_2_state_velocity_transformed = rotation * tracks_2_state_velocity;

        tracks_2_state_transformed = [tracks_2_state_position_transformed(1); 
                                      tracks_2_state_velocity_transformed(1); 
                                      tracks_2_state_position_transformed(2); 
                                      tracks_2_state_velocity_transformed(2)];

        % Position Covariance
        P_xx = tracks_2_covariance([1 3], [1 3]);
        P_vv = tracks_2_covariance([2 4], [2 4]);
        P_xv = tracks_2_covariance([1 3], [2 4]);

        P_xx_rotated = rotation * P_xx * rotation';
        P_vv_rotated = rotation * P_vv * rotation';
        P_xv_rotated = rotation * P_xv * rotation';

        tracks_2_covariance_rotated = [P_xx_rotated P_xv_rotated; P_xv_rotated' P_vv_rotated];

        tracks_2_temp.State = tracks_2_state_transformed;
        tracks_2_temp.StateCovariance = tracks_2_covariance_rotated;

        tracks_2_temp.SourceIndex = 2;
        tracks_1_temp.SourceIndex = 1;

        all_tracks = [tracks_1_temp, tracks_2_temp];

        source_1 = fuserSourceConfiguration(1, 'IsInternalSource', true);
        source_2 = fuserSourceConfiguration(2, 'IsInternalSource', true);

        fuser = trackFuser('FuserIndex', 3, ...
                            'MaxNumSources', 2, ...
                            'SourceConfigurations', {source_1; source_2}, ...
                            'StateFusion', 'Intersection', ...
                            'StateFusionParameters', 'trace', ...
                            StateTransitionFcn = @constvel,...
                            StateTransitionJacobianFcn = @constveljac,...
                            HasAdditiveProcessNoise = true,...
                            ProcessNoise = 0.025*eye(4), ...
                            Assignment='Munkres');
        
        % Fuse tracks
        [fused_tracks, ~, ~, info] = fuser(all_tracks, common_frames(i));

        if common_frames(i) == 434
            disp('434');
        end

        if ~isempty(fused_tracks)
            fused_tracks.TrackID = (tracks_1_temp.TrackID + tracks_2_temp.TrackID);
            
            % Display fused track
            disp('Fused Track:');
            disp(fused_tracks);
    
            all_tracks = [all_tracks, fused_tracks];
        end
        prev_plot_dict = plot_tracks(prev_plot_dict, all_tracks, 10, common_frames(i), true);

        Frame = getframe(gcf);
        writeVideo(vw,Frame);
        pause(0.001);
    end
end

hold off;
close(vw);

save(output_file_name, 'prev_plot_dict');