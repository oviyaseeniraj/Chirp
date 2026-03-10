function [confirmed_tracks, tentative_tracks, track_history_dict] = get_tracks_from_detections_jpda(detection_centroids, frame_idx, track_history_dict)

    %{
    track_history_dict = {'frame_idx': {track_id: track_info}}
    %}

    prev_track_dict = get_prev_tracks(track_history_dict);

    % Parameters
    detection_probability = 0.9;
    % Volume of measurement space
    azSpan = 2*pi; %-pi->pi
    rSpan = 18.07;
    dopplerSpan = 10;
    V = azSpan*rSpan*dopplerSpan;

    clutter_density = 5/V;

    gating_threshhold = 12;

    % For Track initialization
    threshold_init = 0.05;

    % For Track confirmation/deletion
    %threshold_deletion = 0.1;
    %threshold_confirmation = 0.95;
    threshold_hit_miss = 0.3;

    threshold_merge = 7;

    % Get detection-track associations
    [associations] = get_soft_associations_and_marginals(detection_centroids, ...
                  prev_track_dict, detection_probability, clutter_density, gating_threshhold);
    
    current_track_dict = get_current_tracks(prev_track_dict, detection_centroids, ...
        associations, threshold_init, threshold_hit_miss, threshold_merge);

    track_history_dict(frame_idx) = current_track_dict;

    [confirmed_tracks, tentative_tracks] = get_confirmed_and_tentative_tracks(current_track_dict);

end

function [track_dict] = get_prev_tracks(track_history_dict)

    if ~isConfigured(track_history_dict)
        track_dict = dictionary;
    else
        frame_list = keys(track_history_dict);
        track_dict = track_history_dict(frame_list(end));
    end
end

function [current_track_dict] = get_current_tracks(prev_track_dict, ...
                                         detection_centroids, associations, ...
                                         threshold_init, threshold_hit_miss, ...
                                         threshold_merge)
    
    probabilities_tracks_detections = associations.probabilities_tracks_detections;
    probabilities_effective_track_hit = associations.probabilities_effective_track_hit;
    probabilities_detections_non_clutter = associations.probabilities_detections_non_clutter;

    disp('Probabilities Track Detection');
    disp(probabilities_tracks_detections);

    disp('Probabilities Detection Non Clutter');
    disp(probabilities_detections_non_clutter);

    current_track_dict = prev_track_dict;

    if isConfigured(current_track_dict)
        track_ids_list = keys(current_track_dict);
    
        for track_id = 1:length(track_ids_list)
            track_info_dict_per_id = current_track_dict(track_ids_list(track_id));

            mp = struct("Frame", "Spherical", "HasAzimuth", true, ...
            "HasElevation", false, "HasRange", true, "HasVelocity", true);

            measFcn = @(x) meas_function_spatial(x, mp);      % returns [z,bounds]
            measJac = @(x) meas_jacobian_function_spatial(x, mp);

            % Set the value of dt as the time taken to reach next frame
            dt = 0.10; % Frame Time

            stateFcn = @(x) constvel(x, dt);
            stateJac = @(x) constveljac(x, dt);
                
            filter = trackingEKF(State = track_info_dict_per_id.State,...
                        StateCovariance = track_info_dict_per_id.State_Covariance,...
                        StateTransitionFcn = stateFcn,...
                        StateTransitionJacobianFcn = stateJac,...
                        HasAdditiveProcessNoise = true,...
                        MeasurementFcn = measFcn,...
                        MeasurementJacobianFcn = measJac,...
                        ProcessNoise = track_info_dict_per_id.Process_Noise,...
                        MeasurementNoise = track_info_dict_per_id.Measurement_Noise, ...
                        EnableSmoothing=true);
    
            predict(filter);

            % Populate predicted state and state covariance in current track_info
            track_info_dict_per_id.State = filter.State;
            track_info_dict_per_id.State_Covariance = filter.StateCovariance;

            track_info_dict_per_id.Frame_Count = track_info_dict_per_id.Frame_Count + 1;

            % If effective hit probability < threshold_hit_miss, then coast
            % track and register a miss, else register a hit
            if isempty(detection_centroids) || probabilities_effective_track_hit(track_id) < threshold_hit_miss
                track_info_dict_per_id.Consecutive_No_Association_Count = track_info_dict_per_id.Consecutive_No_Association_Count + 1;
                track_info_dict_per_id.Association_Bit_Vector = update_association_bit_vector(track_info_dict_per_id.Association_Bit_Vector, 0);
            
            elseif ~isempty(detection_centroids)
                correctjpda(filter, detection_centroids', probabilities_tracks_detections(track_id, :)'); % Soft Update

                % Populate predicted state and state covariance in current track_info
                track_info_dict_per_id.State = filter.State;
                track_info_dict_per_id.State_Covariance = filter.StateCovariance;

                track_info_dict_per_id.Association_Bit_Vector = update_association_bit_vector(track_info_dict_per_id.Association_Bit_Vector, 1);
                track_info_dict_per_id.Consecutive_No_Association_Count = 0;
            end

            % Populate effective track hit probability for integrated
            % probabilistic evaluations
            track_info_dict_per_id.Effective_Track_Hit_Probability_Vector = update_target_hit_probability_vector(track_info_dict_per_id.Effective_Track_Hit_Probability_Vector, probabilities_effective_track_hit(track_id));

            current_track_dict(track_ids_list(track_id)) = track_info_dict_per_id;
        end
    end

    if numel(detection_centroids) > 0
        for centroid_idx = 1:length(detection_centroids(:, 1))
            % If probability of associating the detection with all tracks
            % falls < threshold_init, spawn a new track with that detection'

            if isConfigured(prev_track_dict)
                claim = max(probabilities_tracks_detections(:, centroid_idx));
            else
                claim = 0;
            end

            if ~isConfigured(prev_track_dict) || ...
                    (claim < threshold_init)

                % Set the value of dt as the time taken to reach next frame
                dt = 0.10; % Frame Time

                k = sqrt(12); % Measurement Noise Scaling Factor
    
                Q = eye(4) * 0.10;
                %Q = process_noise(5, dt);
                sigma_azimuth = k*(pi/4)/sqrt(12);
                sigma_range = k*(0.035)/sqrt(12);
                sigma_doppler = k*(0.0767)/sqrt(12);
    
                measurement_noise = [sigma_azimuth^2 0 0; 0 sigma_range^2 0; 0 0 sigma_doppler^2];

                mp = struct("Frame", "Spherical", "HasAzimuth", true, ...
                "HasElevation", false, "HasRange", true, "HasVelocity", true);
    
                measFcn = @(x) meas_function_spatial(x, mp);      % returns [z,bounds]
                measJac = @(x) meas_jacobian_function_spatial(x, mp);
    
                stateFcn = @(x) constvel(x, dt);
                stateJac = @(x) constveljac(x, dt);
    
                filter = trackingEKF(State = [0; 0; 0; 0],...
                            StateCovariance = eye(4),...
                            StateTransitionFcn = stateFcn,...
                            StateTransitionJacobianFcn = stateJac,...
                            HasAdditiveProcessNoise = true,...
                            MeasurementFcn = measFcn,...
                            MeasurementJacobianFcn = measJac,...
                            ProcessNoise = Q,...
                            MeasurementNoise = measurement_noise, ...
                            EnableSmoothing=true);
    
                predict(filter);
                correct(filter, detection_centroids(centroid_idx, :)');
    
                if isConfigured(current_track_dict)
                    new_track_id = max(keys(current_track_dict)) + 1;
                else
                    new_track_id = 1;
                end
    
                track_info_dict_per_id = struct;
                track_info_dict_per_id.State = filter.State;
                track_info_dict_per_id.State_Covariance = filter.StateCovariance;
                track_info_dict_per_id.Type = "Tentative";
                track_info_dict_per_id.Process_Noise = filter.ProcessNoise;
                track_info_dict_per_id.Measurement_Noise = filter.MeasurementNoise;
    
                track_info_dict_per_id.Frame_Count = 1;
                track_info_dict_per_id.Association_Bit_Vector = [0 0 0 0 0 0 0 1];
                track_info_dict_per_id.Consecutive_No_Association_Count = 0;
                track_info_dict_per_id.Effective_Track_Hit_Probability_Vector = [0 0 0 0 0 0 0 1];
    
                current_track_dict(new_track_id) = track_info_dict_per_id;
            end
        end
    end

    % Operations on the current tracks
    if isConfigured(current_track_dict)
        track_ids_list = keys(current_track_dict);
    
        track_ids_to_delete = [];
        
        for track_id = 1:length(track_ids_list)
            track_info_dict_per_id = current_track_dict(track_ids_list(track_id));
            
            % Confirmation Check
            if track_info_dict_per_id.Type == "Tentative" && nnz(track_info_dict_per_id.Association_Bit_Vector) >= 5
                track_info_dict_per_id.Type = "Confirmed"; % Confirmed
            end
    
            % Deletion Check
            if track_info_dict_per_id.Consecutive_No_Association_Count >= 5
                track_ids_to_delete = [track_ids_to_delete track_ids_list(track_id)];
            end

            current_track_dict(track_ids_list(track_id)) = track_info_dict_per_id;
        end
    
        for del_track_idx = 1:length(track_ids_to_delete)
            current_track_dict(track_ids_to_delete(del_track_idx)) = [];
        end

        if isempty(keys(current_track_dict))
            current_track_dict = dictionary; % So that isConfigured is again False
        end

        current_track_dict = remove_duplicates(current_track_dict, threshold_merge);
    end
end

function [confirmed_tracks, tentative_tracks] = get_confirmed_and_tentative_tracks(current_track_dict)

    confirmed_tracks = [];
    tentative_tracks = [];

    if isConfigured(current_track_dict)
        track_ids_list = keys(current_track_dict);

        for track_id = 1:length(track_ids_list)
            track_info_dict_per_id = current_track_dict(track_ids_list(track_id));
    
            track_info_obj = objectTrack;
    
            % Filling info in Track Object
            track_info_obj.TrackID = track_ids_list(track_id);
            track_info_obj.State = track_info_dict_per_id.State;
            track_info_obj.StateCovariance = track_info_dict_per_id.State_Covariance;
            track_info_obj.Age = track_info_dict_per_id.Frame_Count;
    
            if track_info_dict_per_id.Type == "Tentative"
                track_info_obj.IsConfirmed = 0;
                tentative_tracks = [tentative_tracks; track_info_obj];
            elseif track_info_dict_per_id.Type == "Confirmed"
                confirmed_tracks = [confirmed_tracks; track_info_obj];
            end
        end
    end
end

function [updated_association_bit_vector] = update_association_bit_vector(association_bit_vector, new_association)

    updated_association_bit_vector = zeros(size(association_bit_vector));
    updated_association_bit_vector(1:7) = association_bit_vector(2:8);
    updated_association_bit_vector(8) = new_association;
end

function [updated_target_hit_probability_vector] = update_target_hit_probability_vector(target_hit_probability_vector, new_probability)

    updated_target_hit_probability_vector = zeros(size(target_hit_probability_vector));
    updated_target_hit_probability_vector(1:7) = target_hit_probability_vector(2:8);
    updated_target_hit_probability_vector(8) = new_probability;
end

function current_track_dict = remove_duplicates(current_track_dict, threshold_merge)

    track_ids_to_delete = [];

    if isConfigured(current_track_dict)
        track_ids_list = keys(current_track_dict);

        strength = zeros(size(track_ids_list));

        for track_id = 1:length(track_ids_list)
            track_info_dict_per_id = current_track_dict(track_ids_list(track_id));
            average_track_hit_probability = get_averaged_track_hit_probability(track_info_dict_per_id.Effective_Track_Hit_Probability_Vector, ...
                                       track_info_dict_per_id.Frame_Count);

            confirmation_score = 0;
            if track_info_dict_per_id.Type == "Confirmed"
                confirmation_score = 1;
            end

            strength(track_id) = 0.5*average_track_hit_probability + 0.5*confirmation_score;
        end

        for track_id_1 = 1:length(track_ids_list)-1

            if any(ismember(track_ids_to_delete, track_ids_list(track_id_1)))
                continue;
            end
            track_info_dict_per_id_1 = current_track_dict(track_ids_list(track_id_1));
            x_1 = track_info_dict_per_id_1.State;
            P_x_1 = track_info_dict_per_id_1.State_Covariance;

            for track_id_2 = track_id_1+1:length(track_ids_list)
                if any(ismember(track_ids_to_delete, track_ids_list(track_id_2)))
                    continue;
                end
                track_info_dict_per_id_2 = current_track_dict(track_ids_list(track_id_2));
                x_2 = track_info_dict_per_id_2.State;
                P_x_2 = track_info_dict_per_id_2.State_Covariance;

                % (B1) Mahalanobis distance using average covariance
                dist = maha2_avg(x_1, P_x_1, x_2, P_x_2);
        
                if dist >= threshold_merge
                    continue;  % far enough apart → not duplicates
                end

                keep_1 = strength(track_id_1) > strength(track_id_2);

                if keep_1
                    track_ids_to_delete = [track_ids_to_delete track_ids_list(track_id_2)];
                else
                    track_ids_to_delete = [track_ids_to_delete track_ids_list(track_id_1)];
                end

            end
        end
        for del_track_idx = 1:length(track_ids_to_delete)
            current_track_dict(track_ids_to_delete(del_track_idx)) = [];
        end

        if isempty(keys(current_track_dict))
            current_track_dict = dictionary; % So that isConfigured is again False
        end
    end
end

function average_track_hit_probability = get_averaged_track_hit_probability(track_hit_probability_vector, age)

    frame_count = 8;
    if age < 8
        frame_count = age;
    end

    average_track_hit_probability = mean(track_hit_probability_vector(end+1-frame_count:end));
end

function d2 = maha2_avg(x1, P1, x2, P2)
    % Mahalanobis^2 using average covariance, robust to ill-conditioning.
    Pavg = 0.5*(P1 + P2);
    dx   = x1 - x2;
    
    % Use Cholesky solve when possible; fallback to pinv if needed
    [U,flag] = chol(Pavg,'lower');
    if flag == 0
        y  = U \ dx;
        d2 = (y' * y);
    else
        d2 = dx' * pinv(Pavg) * dx;
    end
end

function [associations] = get_soft_associations_and_marginals(detection_centroids, ...
                        track_dict, detection_probability, clutter_density, gating_threshold)

    associations = struct;

    associations.probabilities_tracks_detections = [];
    associations.probabilities_detections_non_clutter = [];
    associations.probabilities_effective_track_hit = [];

    num_detections = 0;
    num_tracks = 0;
    
    if ~isempty(detection_centroids)
        disp('Detections:');
        disp(detection_centroids);
        num_detections = length(detection_centroids(:, 1));
    end

    if isConfigured(track_dict)
        track_ids_list = keys(track_dict);
        for track_id = 1:length(track_ids_list)
            fprintf('Track_ID %d, Status %s \n', track_ids_list(track_id), track_dict(track_ids_list(track_id)).Type);
        end
        num_tracks = length(keys(track_dict));
    end

    % Associations - Track - Detection, M X (N + 1) size
    % Needed for correctjpda function
    probabilities_tracks_detections = zeros(num_tracks, num_detections + 1); % Last column needed for track miss
    probabilities_detections_clutter = zeros(num_detections, 1);
    probabilities_track_miss = zeros(num_tracks, 1);
    probabilities_effective_track_hit = zeros(num_tracks, 1);

    max_num_feasible_joint_events = 3;

    % Tracks - M, Detections - N, Distance Matrix - N X M size
    distance_matrix = get_distance_matrix(detection_centroids, track_dict, gating_threshold);

    if ~isempty(distance_matrix)
        likelihood_matrix = get_likelihood_matrix(distance_matrix, detection_probability, clutter_density);
    
        % Get valid Hypotheses (Feasible Joint Events) (Now = 3)
        [FJE, FJE_Probs] = jpdaEvents(likelihood_matrix, max_num_feasible_joint_events);
    
        % Get marginal probabilities

        for k = 1:size(FJE, 3)
            event = FJE(:, :, k); % N X (M + 1)
            event_probability = FJE_Probs(k);

            for j=1:num_detections

                % Populate clutter
                if event(j, 1) == 1
                    probabilities_detections_clutter(j) = probabilities_detections_clutter(j) + event_probability;
                end

                % Populate track detection probabilities
                for i=1:num_tracks
                    if event(j, i + 1) == 1
                        probabilities_tracks_detections(i, j) = probabilities_tracks_detections(i, j) + event_probability;
                    end
                end
            end

            % Populate track misses
            for i=1:num_tracks
                if all(event(:, i + 1) == 0)
                    probabilities_tracks_detections(i, end) = probabilities_tracks_detections(i, end) + event_probability;
                    probabilities_track_miss(i) = probabilities_track_miss(i) + event_probability;
                end
            end
        end

        % Normalize the probabilities
        for i=1:num_tracks
            for j=1:num_detections+1
                probabilities_tracks_detections(i, j) = probabilities_tracks_detections(i, j)/sum(probabilities_tracks_detections(i, :));
            end
            probabilities_effective_track_hit(i) = sum(probabilities_tracks_detections(i, 1:num_detections));
        end
    end

    % Populate association struct

    associations.probabilities_tracks_detections = probabilities_tracks_detections;
    associations.probabilities_detections_non_clutter = 1 - probabilities_detections_clutter;
    associations.probabilities_effective_track_hit = probabilities_effective_track_hit;

end

function [likelihood_matrix] = get_likelihood_matrix(distance_matrix, detection_probability, clutter_density)

    likelihood_matrix = zeros(size(distance_matrix, 1) + 1, size(distance_matrix, 2) + 1);

    % Row 1 is corresponding to missed detection (A target assigned to no
    % detection). Column 1 is clutter (A detection assigned to no target)

    likelihood_matrix(1, :) = 1 - detection_probability;
    likelihood_matrix(:, 1) = clutter_density;

    for i=1:size(distance_matrix, 1)
        for j = 1:size(distance_matrix, 2)
            likelihood_matrix(i + 1, j + 1) = detection_probability * exp(-1/2*distance_matrix(i, j));
        end
    end
end

function [distance_matrix] = get_distance_matrix(detection_centroids, track_dict, gating_threshold)

    distance_matrix = [];

    if isConfigured(track_dict) && ~isempty(detection_centroids)
        track_ids_list = keys(track_dict);

        distance_matrix = zeros(length(detection_centroids(:, 1)), length(track_ids_list));

        distance_matrix_without_gating = zeros(size(distance_matrix));

        i = 1;
        j = 1;

        for centroids_idx = 1:length(detection_centroids(:, 1))
            for track_id = 1:length(track_ids_list)
                track_info_dict_per_id = track_dict(track_ids_list(track_id));
    
                mp = struct("Frame", "Spherical", "HasAzimuth", true, ...
                "HasElevation", false, "HasRange", true, "HasVelocity", true);
    
                measFcn = @(x) meas_function_spatial(x, mp);      % returns [z,bounds]
                measJac = @(x) meas_jacobian_function_spatial(x, mp);
    
                % Set the value of dt as the time taken to reach next frame
                dt = 0.10; % Frame Time
    
                stateFcn = @(x) constvel(x, dt);
                stateJac = @(x) constveljac(x, dt);
                
                filter = trackingEKF(State = track_info_dict_per_id.State,...
                            StateCovariance = track_info_dict_per_id.State_Covariance,...
                            StateTransitionFcn = stateFcn,...
                            StateTransitionJacobianFcn = stateJac,...
                            HasAdditiveProcessNoise = true,...
                            MeasurementFcn = measFcn,...
                            MeasurementJacobianFcn = measJac,...
                            ProcessNoise = track_info_dict_per_id.Process_Noise,...
                            MeasurementNoise = track_info_dict_per_id.Measurement_Noise, ...
                            EnableSmoothing=true);
            
                distance_matrix(i, j) = distance(filter, detection_centroids(centroids_idx, :));

                % Calculate squared distance
                [state_pred, state_cov_pred] = predict(filter);

                meas_pred = meas_function_spatial(state_pred, mp);
                H = meas_jacobian_function_spatial(state_pred, mp);

                S = track_info_dict_per_id.Measurement_Noise + H*state_cov_pred*H';

                % Innovation
                innovation = detection_centroids(centroids_idx, :)' - meas_pred;

                % Wrapping Spatial frequency values to Pi
                innovation(1) = wrapToPi(innovation(1));

                % Squared Mahalanobis distance: innovation' * inv(S) * innovation
                squared_distance = innovation' * (S \ innovation);

                distance_matrix_without_gating(i, j) = distance_matrix(i, j);

                % Gating Threshold Check
                if squared_distance > gating_threshold
                    distance_matrix(i, j) = inf;
                end
                j = j + 1;
            end
            j = 1;
            i = i + 1;
        end
        disp('Distance Matrix:');
        disp(distance_matrix_without_gating);
    end
end

function z = meas_function_spatial(x, measParams)
% z = [range; doppler(rangeRate); spatialFreq]

    zS = cvmeas(x, measParams);   % [az; r; rr] in 2D spherical
    azDeg = zS(1);
    r     = zS(2);
    rr    = zS(3);

    % IMPORTANT: cvmeas returns az in DEGREES.
    az = deg2rad(azDeg);

    u = pi*sin(az);

    z = [u; r; rr];
end

function H = meas_jacobian_function_spatial(x, measParams)
% H = d[r; rr; u]/dx

    zS = cvmeas(x, measParams);        % [az; r; rr]
    azDeg = zS(1);
    az    = deg2rad(azDeg);

    JS = cvmeasjac(x, measParams);     % rows: [daz; dr; drr] w.r.t state

    JazDeg = JS(1,:);                  % d(az in deg)/dx
    Jr     = JS(2,:);                  % d(r)/dx
    Jrr    = JS(3,:);                  % d(rr)/dx

    % Convert d(az)/dx from deg to rad:
    Jaz = (pi/180) * JazDeg;

    % u = pi*sin(az)  => du/dx = pi*cos(az) * daz/dx
    Hu = (pi*cos(az)) * Jaz;

    % Output order matches measRrdU: [ u; r; rr]
    H = [Hu; Jr; Jrr];
end