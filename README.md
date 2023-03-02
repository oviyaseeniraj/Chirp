# mmSnap
Codebase for mmSnap: Bayesian One-Shot Fusion in a Self-Calibrated mmWave Radar Network (Accepted for publication at RadarConf 2025)

## How to Set Up Range-Doppler Map Visualizer
This setup is split into 2 parts: one for the AWR2243 radar board, and one for the DCA1000EVM board. Then, run the visualizer test program. 

### AWR Board:
1. Change into `Documents/JetsonHardwareSetup/setup_radar/build` directory
2. Run `./setup_radar`  
Note: if running into an issue when setting up AWR board, just power cycle it  (setup_radar executable was giving me some error) 

### DCA Board:
1. Change into `Documents/JetsonHardwareSetup/DCA1000/SourceCode/Release` directory
2. Run `./DCA1000EVM_CLI_Control fpga DCAconfig.json`
3. Run `./DCA1000EVM_CLI_Control record DCAconfig.json`  
    STOP HERE: Have you run `./setup_radar` yet? If not, run that first, then continue.
4. Run `./DCA1000EVM_CLI_Control start_record DCAconfig.json`

### Run the Visualizer:
1. Change into `Multi-Node-App/RadarPipeline/test/non_threads`  
    Note: this Multi-Node-App folder is from Percept's capstone -- we will probably need to change these directions when our Chirp codebase is finalized and built on the Jetsons  
2. Run `./test`

## How to Modify Radar Parameters
Before collecting data on the radar, you probably want to configure settings such as the max range, max Doppler (radial velocity), range resolution, and Doppler resolution that the radar can detect.  

Under `Chirp/Node/setup_radar`, there’s a file called mmwaveconfig.txt; this file contains a bunch of parameters that modify C-style structs in the mmWaveAPI (this API basically just sends data to the radar board to configure settings). These structs are called rlProfileCfg_t, rlChirpCfg_t, etc.  

More in-depth definitions are at this [link](https://astroa.net/fmcw-RADAR/mmwave_sdk/packages/ti/control/mmwavelink/docs/doxygen/html/annotated.html). Under the ‘Data Structures’ tab, look for the struct that you want to modify. Inside of this struct, there are data fields that tell you how to set bits to get the final value that you type into the mmwaveconfig.txt parameter.  

## Overview
Contains the codebase for the end-to-end mmSnap Pipeline containing the blocks for :

- [Range-Doppler-Angle Processing](#range-doppler-angle-processing)
- [Tracking](#tracking)
- [Self-Calibration](#self-calibration)
- [One-Shot Fusion](#one-shot-fusion)

### Range-Doppler-Angle Processing

- Input : 5D Radar Cube Data (Format : Frames X Chirps per Frame X Num_Rx X Num_Tx X ADC Samples)
- Output : (Range, Doppler, Angle) for detections
- Summary : The raw ADC data is converted from its original radar cube format 
into Range-Doppler-Angle point clouds for each frame by applying Fast Fourier Transforms (FFTs) 
along the relevant dimensions. To concentrate on moving targets, 
static clutter removal is conducted, followed by the application of a 
two-dimensional Ordered-Statistics Constant False Alarm Rate (2D OS-CFAR) 
detection across the frames for additional refinement.

### Tracking 

- Input : RDA Map
- Output : Detection Centroids and corresponding Tracks
- Summary : In the tracking stage, DBSCAN clustering extracts the centroids 
of point clouds, which are subsequently processed by an Extended Kalman Filter (EKF) 
for continuous tracking. For human targets within a distance of 10 meters, 
the point cloud exhibits significant Doppler variation due to limb movements. 
We have developed a variant of DBSCAN to extract a cluster center that 
represents the torso's position and motion. This approach enables the 
self-calibration and one-shot fusion algorithms, which are based on point 
target models, to remain straightforward and effective.

### Self-Calibration

- Input : Tracks from both radar perspectives
- Output : Relative Optimal Pose Estimates (Calibration)
-Summary : We integrate target tracking with pose estimation by “matching” 
each node’s observation of a common target in a least-squares sense, 
yielding a closed-form calibration solution. 

### One-Shot Fusion

- Input : Centroids from both Radar Perspectives, Calibration
- Output : Instantaneous Fused State and State Covariance estimates of targets
- Summary : We firstly match the centroids from both radar perspectives using 
the Hungarian Algorithm. Then we perform a Regularized Non-Linear Least Squares 
Optimization to obtain the Bayesian one-shot fused estimate using suitable 
priors for human motion.


## Link to Paper

Arxiv Link : [mmSnap](https://arxiv.org/abs/2505.00857)