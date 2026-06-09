clear; clc; close all;

% Connect to the Mobile Device
m = mobiledev;

% Enable required sensors
m.PositionSensorEnabled = true;  % GPS for (lat, lon)
m.OrientationSensorEnabled = true; % Orientation for yaw
m.Logging = true;
pause(2); % Give time to gather initial sensor data


% Configure these values initially
% Reference Latitude, Reference Longitude, Reference Azimuth
lat_ref = 34.413972;
lon_ref = -119.841908;

azimuth_ref = 173.944;


while true

    azimuth = NaN;
    relative_orientation = NaN;
    theta = NaN;

    % Get Yaw (Heading) from Orientation Data
    [eul, ~] = orientlog(m);
    if isempty(eul)
        disp('Orientation data not available.');
        azimuth = NaN;
    else
        azimuth = eul(end, 1); % Format - Azimuth, Pitch, Roll

        relative_orientation = azimuth - azimuth_ref;
        fprintf('2D Orientation (Yaw): %.2f°\n', relative_orientation);
    end

    % Azimuth Ref - CW from N
    % Theta Ref - CCW from East
    theta_ref = 90 - azimuth_ref;
    if theta_ref < 0
        theta_ref = theta_ref + 360;
    end

    % Get GPS Data (Latitude, Longitude)
    [lat, lon, ~] = poslog(m);
    if isempty(lat) || isempty(lon)
        disp('Position data not available. Ensure GPS is enabled.');
        x = NaN; y = NaN;
    else
        % Convert lat/lon to approximate X, Y using a simple conversion
        earth_radius = 6371000; % Approximate Earth radius in meters
    
        % Convert latitude and longitude differences to meters
        x = (lon - lon_ref) * (pi/180) * earth_radius * cosd(lat_ref);
        y = (lat - lat_ref) * (pi/180) * earth_radius;
    
        % Get the latest position w.r.t. ground frame
        % X pointed towards East, Y pointed towards North
        x_east = x(end);
        y_north = y(end);

        if ~isnan(theta_ref)
            relative_position = exp(1j*deg2rad(-theta_ref)) * (x_east + 1j*y_north);
            
            fprintf('2D Position (Approximate in meters): X: %.2f, Y: %.2f\n', ...
                             real(relative_position), imag(relative_position));
        else
            disp('Theta Value not available');
        end
    end

    pause(2);
end

% Stop Logging
m.Logging = false;
