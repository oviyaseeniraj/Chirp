clear, clc; close all;

% Load Experiment Radar Cube Data
experiment_name = 'May17_cfg1_radar1_random_noRangeFT';
experiment_data_path = strcat('D:\Research\Dist-Radar\Radar_Data\May17_2025\May17_2025\', experiment_name, '.mat');
load(experiment_data_path);

output_folder_path = 'D:\Research\Dist-Radar\Radar_Pipeline_Output\'; 

num_frames = size(Data_PostBPM_noFFT, 1);
num_chirps_per_frame = size(Data_PostBPM_noFFT, 2);
num_rx_channels = size(Data_PostBPM_noFFT, 3);
num_tx_channels = size(Data_PostBPM_noFFT, 4);
num_adc_samples = size(Data_PostBPM_noFFT, 5);

num_range_bins = num_adc_samples; 
num_doppler_bins = num_chirps_per_frame; 

%==========================================================================
% Configured Parameters

c = 3e8; % speed of light
f_s = 10e6; % RX ADC Sampling Rate % for 75ms make it twice 10e6
BW = 4.2492e9;%4.98e9; %5e9; % Bandwidth
f_carrier = 76e9; % Carrier Frequency
lambda = c/f_carrier; % Carrier Wavelength
T_f = 150e-3;%75e-3; % Frame duration
N_chirps_per_frame_tdm = num_chirps_per_frame*num_tx_channels; % TDM
S = 83e12; % Slope % for 75ms make it twice 83e12

% Have a choice of Hann, Blackman or Hamming
windowing_choice = 'Hann';

% Calculations

T_chirp_ramp = BW/S;
T_f_effective = T_chirp_ramp*N_chirps_per_frame_tdm; % Effective Frame Time
D = T_f_effective/T_f; % Duty Cycle
T_c = T_f/num_chirps_per_frame;%T_chirp_ramp*num_tx_channels; % Chirp time for a TDM MIMO Radar

range_resolution = c/(2*BW);
max_range = f_s*c/(2*S);
max_velocity = lambda/(4*T_c); % Need to confirm
doppler_resolution = lambda/(2*T_f_effective);

%==========================================================================
% Range FFT (across ADC sampples)

Data_PostBPM_Range_FFT = Data_PostBPM_noFFT;

for frame_idx = 1:num_frames
    for chirp_idx = 1:num_chirps_per_frame
        for rx_idx = 1:num_rx_channels
            for tx_idx = 1:num_tx_channels
                range_sample = Data_PostBPM_noFFT(frame_idx, chirp_idx, rx_idx, tx_idx, :);

                % Add Hann Window for Range
               window = windowing(windowing_choice, num_adc_samples);
               windowed_range_sample = reshape(reshape(range_sample, num_adc_samples, 1).*window, 1, 1, 1, 1, num_adc_samples);
              

                range_sample_fft = fft(windowed_range_sample, num_range_bins);
                Data_PostBPM_Range_FFT(frame_idx, chirp_idx, rx_idx, tx_idx, :) = range_sample_fft;
            end
        end
    end
end

RDMap_PostBPM = Data_PostBPM_Range_FFT;

% Doppler FFT (Across chirps)
for frame_idx = 1:num_frames
    for rx_idx = 1:num_rx_channels
        for tx_idx = 1:num_tx_channels
            for adc_sample_idx = 1:num_adc_samples
                doppler_sample = Data_PostBPM_Range_FFT(frame_idx, :, rx_idx, tx_idx, adc_sample_idx);

                % Add Hann Window for Doppler
                window = windowing(windowing_choice, num_chirps_per_frame);
                windowed_doppler_sample = reshape(reshape(doppler_sample, num_chirps_per_frame, 1).*window, 1, num_chirps_per_frame, 1, 1, 1);
                
                doppler_sample_fft = fft(windowed_doppler_sample, num_doppler_bins);
                doppler_sample_fft = fftshift(doppler_sample_fft);
                RDMap_PostBPM(frame_idx, :, rx_idx, tx_idx, adc_sample_idx) = doppler_sample_fft;
            end
        end
    end
end


%==========================================================================
% Implementing scene subtraction to get clearer peaks (removing the static objects that are of no interest to us)

% staying in complex domain-> Setting avg value across frames for each RD cell as the static threshold 

% Compute static threshold by averaging across frames
static_threshold = mean(RDMap_PostBPM, 1); % Mean across frames (size: 1 x num_chirps_per_frame x num_rx_channels x num_tx_channels x num_adc_samples)

% Subtract the static threshold
clean_RDMap_PostBPM = RDMap_PostBPM - static_threshold;

% Taking abs value of RD Map
%abs_RDMap_PostBPM = 10*log10(abs(RDMap_PostBPM)/2^10);
abs_RDMap_PostBPM = 10*log10(abs(clean_RDMap_PostBPM)/2^10);

range_axis = range_resolution*(1:num_adc_samples);
doppler_axis = doppler_resolution*linspace(-(num_chirps_per_frame/num_tx_channels)/2, (num_chirps_per_frame/num_tx_channels)/2, num_chirps_per_frame);

%==========================================================================
% Implementing 2D OS-CFAR

% Note -> just a rough implementation from 2-year old code. Need to clean
% up and optimize based on current experiments (can comment out this block
% to save complie time

% To-Dos: Save in a different folder, Play with threshold and window sizes
% for more accurate tracking

Pfa = 10^-4; % Need to update the correct Pfa after experimental analysis of Noise floor
M = 8;
N = 4;
Ref_win = M * N; % Reference window dimension
K = 18; % kth ordered statistic taken using approximation K = ((3*ref_win) / 4); %18
T = 6.1; % scaling factor value for given Pfa and K 6.1, 5.7
CFARMatrix = zeros(num_frames,num_chirps_per_frame,num_adc_samples);
countNonZeroFrames =[];
for frame_idx = 1: num_frames   
sizeDimensions = [num_adc_samples,num_chirps_per_frame];
for im = 1:1:sizeDimensions(1) -M
    for in = 1:1:sizeDimensions(2) - N 
        sample_RD = clean_RDMap_PostBPM(frame_idx,:,1,1,:); % 512 x 60 (?)
        sample_RD = squeeze(sample_RD);
       % sample_RD(columnsToDelete,:) = [];
       % sample_RD = sample_RD - MeanClutter_RD; % Subtracting the mean clutter value 
        RD_data = sample_RD(in:in+N,im:im+M); % 5 x 9
        CUTIdx = ceil(size(RD_data)/2);
        RD_data_arr = RD_data';
        RD_data_arr = RD_data_arr(:)'; % Converting RD data matrix to array
        CUTIdx_arr = ceil(size(RD_data_arr)/2);
        RD_data_arr = [RD_data_arr(1:CUTIdx_arr(2)-1) RD_data_arr(CUTIdx_arr(2)+1:end)]; %Removing CUT cell
        sorted_RDdata = sort(abs(RD_data_arr));
        X_k  = sorted_RDdata(K); % Extracting Kth order statistic
        thresh = X_k * T; % Computing threshold
        if abs(RD_data(CUTIdx(1), CUTIdx(2))) >= thresh
            countNonZeroFrames = [countNonZeroFrames frame_idx];
            CFARMatrix(frame_idx,in+CUTIdx(1),im+CUTIdx(2)) = 1;  
        end
    end
end
end

figure();
vw = VideoWriter('cfar_RD.avi');
vw.Quality = 100;
vw.FrameRate = 10;
open(vw);
for a = 1:num_frames
    sample = abs_RDMap_PostBPM(a,:,1,1,:);
    sample = squeeze(sample);  
  %  surf(range_axis,doppler_axis,sample); hold on;
     imagesc(range_axis,doppler_axis,sample); hold on;
    CFARMatrix1 = squeeze(CFARMatrix(a,:,:));
    if find(countNonZeroFrames == a)
        [row, col] = find(CFARMatrix1 == 1);
        plot3(range_axis(col),doppler_axis(row),sample(row,col), 'rx','markersize',15,'LineWidth', 3); 
    end
   hold off;
    xlabel('Distance (m)');
    ylabel('Velocity (m/s)');
    zlabel('Magnitude');
    title(num2str(a));
    drawnow;
    Frame = getframe(gcf);
    writeVideo(vw,Frame);
    pause(0.0001);
end
close(vw);
%==========================================================================
% Configure output path for Plotting results

imagesc_path = strcat(output_folder_path, 'ImageSC/');
data_path = strcat(output_folder_path, 'Data/');
video_file_format = '.avi';

imagesc_window_path = strcat(imagesc_path, windowing_choice, '/');
data_window_path = strcat(data_path, windowing_choice, '/');

% Create Directories if not already done
mkdir(imagesc_path);
mkdir(data_path);
mkdir(imagesc_window_path);
mkdir(data_window_path);

output_path_range_doppler_imagesc = strcat(imagesc_window_path, experiment_name, '_Range_Doppler', video_file_format);
output_path_rd_cfar_angle_imagesc = strcat(imagesc_window_path, experiment_name, '_RF_CFAR_Angle', video_file_format);
output_path_ra_mvdr_imagesc = strcat(imagesc_window_path, experiment_name, '_Range_Angle_Map_MVDR', video_file_format);

output_path_rd_cfar_angle_detection_log = strcat(data_window_path, experiment_name, '_RF_CFAR_Angle', '.mat');

%==========================================================================
% Animation of Range-Doppler Map in ImageSC

figure();
vw = VideoWriter(output_path_range_doppler_imagesc);
vw.Quality = 100;
vw.FrameRate = 20;
open(vw);
for a = 1:num_frames
    sample = abs_RDMap_PostBPM(a,:,1,1,:);
    sample = squeeze(sample);
    imagesc(range_axis, doppler_axis, sample); hold off;
    xlabel('Distance (m)');
    ylabel('Velocity (m/s)');
    zlabel('Magnitude');
    title(num2str(a));
    drawnow;
    frame = getframe(gcf);
    writeVideo(vw, frame);
    pause(0.0001);
end
close(vw);
%==========================================================================

%% Angle FFT 
VirtualArray_noZeroPadding = zeros(2,8); %Based on AWR2243 Setup 
% Desired Format:  000000 000000 TX2RX1 TX2RX2 TX2TX3 TX2RX4 000000 000000
%                  TX3RX1 TX3RX2 TX3RX3 TX3RX4 TX1RX1 TX1RX2 TX1TX3 TX1RX4 
ZeroPadRows = 1; %One end
ZeroPadCols = 248/2; %one end (Effectively want a 128 point FFT so doing 120/2  since we arealdy have 8)
% angle_range = linspace(-pi,pi,2*ZeroPadCols+8);
% angle_range = (180/pi)*asin(angle_range/pi); % Mapping azimuth of angle FFT bins between [-90,90] --> FoV of the radar
angle_range = linspace(-1,1,2*ZeroPadCols+8);
%angle_range = (180/pi)*sin(angle_range); % Mapping azimuth of angle FFT bins between [-90,90] --> FoV of the radar
AngleMatrix = zeros(num_frames, num_chirps_per_frame, num_adc_samples);
for frame_idx = 1:num_frames
           CFARMatrix1 = squeeze(CFARMatrix(frame_idx,:,:));
          if find(countNonZeroFrames == frame_idx)
               [row_dop, col_range] = find(CFARMatrix1 == 1);
               row_len = length(row_dop);
               col_len = length(col_range);
               for rd_idx = 1:row_len
                    range_bin = col_range(rd_idx);
                    doppler_bin = row_dop(rd_idx);
                    sample_RD = squeeze(clean_RDMap_PostBPM(frame_idx,doppler_bin,:,:,range_bin));
                    VirtualArray_noZeroPadding = BuildVirtualArray(num_tx_channels,sample_RD);
                    zc = zeros(size(VirtualArray_noZeroPadding,1),ZeroPadCols);
                    VirtualArray_withZeroPadding = [VirtualArray_noZeroPadding, zc, zc];
                    %AngleFFT = fft2(VirtualArray_withZeroPadding);
                    AngleFFT = fft(VirtualArray_withZeroPadding(2, :), 256);
                    AngleFFT = fftshift(AngleFFT); % TO check whether giving correct results
                    [val,ind] = max(abs(AngleFFT(:))); %Looking for the max across only azimuth
                    ang_val = angle_range(ind);
                    %AngleMatrix(frame_idx,row_dop(rd_idx),col_range(rd_idx)) = ang_val;
                    AngleMatrix(frame_idx,row_dop(rd_idx),col_range(rd_idx)) = rad2deg(asin(ang_val));
               end
          end
end

figure();
vw = VideoWriter(output_path_rd_cfar_angle_imagesc);
vw.Quality = 100;
vw.FrameRate = 20;
open(vw);

detection_log = {};

for a = 1:num_frames
    sample = abs_RDMap_PostBPM(a,:,1,1,:);
    sample = squeeze(sample);  
  %  surf(range_axis,doppler_axis,sample); hold on;
     imagesc(range_axis,doppler_axis,sample); hold on;
    CFARMatrix1 = squeeze(CFARMatrix(a,:,:));
    if find(countNonZeroFrames == a)
        [row, col] = find(CFARMatrix1 == 1);
        ang = [];
        pwr = [];
        for rd_idx = 1:length(row)
            ang = [ang, AngleMatrix(a,row(rd_idx),col(rd_idx))];
            pwr = [pwr, sample(row(rd_idx),col(rd_idx))];
        end
        plot3(range_axis(col),doppler_axis(row),sample(row,col), 'rx','markersize',15,'LineWidth', 3); 
        hold on
        text(range_axis(col)+0.25,doppler_axis(row),num2str(ang(:)));

        % Format the measurement data as a detection object for easier
        % processing by the tracking pipeline
        detections = {};
        for rd_idx = 1:length(row)
            measurement = [ang(rd_idx); range_axis(col(rd_idx)); doppler_axis(row(rd_idx)); pwr(rd_idx)];
            detection = get_detection(a, measurement);
            detections(end+1) = {detection};
        end

        detection_log(end+1, :) = {detections};
    end
   hold off;
    xlabel('Distance (m)');
    ylabel('Velocity (m/s)');
    zlabel('Magnitude');
    title(num2str(a));
    drawnow;
    Frame = getframe(gcf);
    writeVideo(vw,Frame);
    pause(0.0001);

end
close(vw);

% Save radar detection info to mat file
save(output_path_rd_cfar_angle_detection_log, 'detection_log');

%==========================================================================
% Function to get the windowing type

function [window] = windowing(type, size)
    if type == "Hann"
        window = hamming(size);
    elseif type == "Hamming"
        window = hann(size);
    elseif type == "Blackman"
        window = blackman(size);
    else
        window = ones([size 1]);
    end
end

%==========================================================================
% Function to build the virtual array

function [varray] = BuildVirtualArray(num_tx_channels,sample_RD)
    varray = zeros(2,8);

    for tx_idx = 1:num_tx_channels
            if(tx_idx == 1)
                varray(2,5:8) = sample_RD(:,tx_idx);
            end
            if(tx_idx == 2)
                varray(1,3:6) = sample_RD(:,tx_idx);
            end
            if(tx_idx == 3)
                varray(2,1:4) = sample_RD(:,tx_idx);
            end
    end
   

end

%==========================================================================
%Function to calculate the MVDR power across various look angles

function [power_vec] = calc_power_across_FoV(R,steer_vec_12x1,FoV_angle_length)
power_vec = zeros(FoV_angle_length,1);
for ang_idx = 1:FoV_angle_length
    power_vec(ang_idx) = abs(1/(steer_vec_12x1(:,ang_idx)'*pinv(R)*steer_vec_12x1(:,ang_idx)));
end
end


%==========================================================================
% Create detection object
function detection = get_detection(frame, measurement)

    % Set the measurement parameters for detection
    mp = struct(Frame="Spherical", ...
    OriginPosition = zeros(1,3), ...
    OriginVelocity = zeros(1,3), ...
    Orientation = eye(3),...
    HasAzimuth = true,...
    HasElevation = false,...
    HasRange = true,...
    HasVelocity = true,...
    IsParentToChild = true);

    detection = objectDetection(frame, measurement, ...
                                MeasurementParameters=mp);
end