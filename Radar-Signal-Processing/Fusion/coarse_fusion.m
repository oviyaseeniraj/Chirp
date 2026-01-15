function [position,velocity] = coarse_fusion(measurement1,measurement2,calibration)
%Fuse range,Doppler,angle measurements from two radars, given their
%calibration with respect to each other
%   measurement1 = [range,doppler,angle] for radar 1
%   measurement2=[range,doppler,angle] for radar 2
%range in meters, doppler in m/s, angle in radians
%calibration = [x,y,theta] (x,y) offset of radar 2 with respect to radar 1,
%in radar 1's frame
%theta = rotation of radar 2's frame with respect to that of radar 1
%%%
range1=measurement1(1); doppler1 = measurement1(2); angle1=measurement1(3);
range2=measurement2(1); doppler2 = measurement2(2); angle2=measurement2(3);
p= calibration(1)+j*calibration(2); %2d position offset of radar 2 from radar 1 expressed as a complex number
theta = calibration(3);
%%COARSE POSITION ESTIMATES IN EACH RADAR'S FRAME
Z1= range1*exp(j*angle1); %target position measurement by radar 1
Z2 = range2*exp(j*angle2); %target position measurement by radar 2
%%NOW COMPUTE POSITION AND VELOCITY ESTIMATES (BOTH EXPRESSED AS COMPLEX
%%NUMBERS)
%%COARSE POSITION ESTIMATE FUSION USING CALIBRATION INFO
position = (Z1 + Z2*exp(j*theta)+p)/2;
%%COARSE VELOCITY ESTIMATE USING RANGES, DOPPLERS, CALIBRATION, AND COARSE
%%POSITION ESTIMATE
velocity = (range2*doppler2*position - (position-p)*range1*doppler1)/(j*imag(position*conj(position-p)));
end