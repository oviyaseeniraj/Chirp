# Chirp: UCSB ECE Capstone (2025 - 2026)

**Abstract:** Object tracking using mmWave MIMO radar is well-established, but sensing performance degrades in cluttered environments. We present a time-synchronized distributed radar network that fuses detections across spatially separated nodes, enabling continuous tracking through multiple fields of view and line-of-sight obstructions. This architecture extends spatial coverage and maintains track continuity in scenarios where single-node radar systems fail.

**Team Members:** William Ni, Oivya Seeniraj, Andrey Otvagin, Vihan Jayaraman, Jason Wang  
**Adivsors:** Anirban Banik (Grad Student), Tien Nguyen (Capstone TA), Prof. Isukapalli, Prof. Madhow

[Final Presentation](docs/Final_Slides.pdf) | [Final Poster](docs/Final_Poster.pdf) | [Demo Video](add link when vid is edited)

## Dependencies
With `apt` on Linux (run this command on the Jetson Orin Nano devices):
1. `sudo apt install libfftw3-dev libopencv-dev libeigen3-dev libfmt-dev`  
    a. use `dpkg -L <package>` to find the location for include errors

## Understanding the Distributed Setup
Since we are working with devices in a distributed setup, it can confusing figuring out what programs need to be run on which devices. Hopefully this gives you a better idea of how our network is connected.

The network consists of:
1. server node (aka Fusion Center), with dashboard for orchestrating nodes.
2. individual radar node(s)
3. external laptop that operators can use to trigger all radar nodes to capture frames at the same time. 


# Tailscale VPN and Network Setup
When installing node or server for the first time, it's possible to register the device inside a tailnet. Then, through the tailscale admin console, you can assign a name to the device. The name can be used to address the machine through DNS resolution, avoiding the need to find out the assigned IP address, whenever the node connects to a Wi-Fi network (such as UCSB Wireless Web). 

It will also be necessary to register devices using the UCSB Resnet form. Without doing this step, it's entirely possible that the DHCP lease expires within days, requiring you to repeatedly open a GUI on the Jetson and connect to a UCSB Wireless network. Tailscale only works once a device has access to the Internet, so you may need to complete this step as well to ensure seamless connectivity. (It's unknown whether the same IP 169.231.X.X is assigned to a device once registered using the ResNet form.)

Communication across devices is orchestrated with the MQTT protocol. Without Tailscale, it's important to know that every device in the network needs to know one central IP address: the server node IP
- This is important, because the server node IP acts as a rendezvous point for all nodes to connect with each other. 
- This IP address needs to be changed under `Node/.env` (for radar nodes) and `Fusion-Center/MQTT-Broker/.env` (for the Fusion Center and Laptop; they source environment variables from the same file)

For detailed information about how to set up the Fusion Center, please refer to this [README](Fusion-Center/README.md).

# Deprecated, use server dashboard at fusion-center:5002
The laptop trigger should be run in someone's terminal under the `Fusion-Center/Laptop` directory, using this command: `sudo ./start_laptop_trigger.sh --group-id default --calibration --calibration-frames 400`
- the `--calibration` tag tells the shell script to perform auto-calibration across the network
- the `--calibration-frames 400` tag tells the script to use 400 frames from each radar node to feed into the auto-calibration algorithm; this number can be changed as a parameter


## `run_tests.sh` CLI
- A CLI is provided under the directory `Node/test/run_tests.sh` (remember to run this as `sudo` because our hardware trigger C scripts need sudo access to control GPIO of the Jetson device). 
- This interface allows a user to automatically set up the radar boards, display the range-Doppler map, capture raw ADC sample data, and reset the radar boards. Resetting the radar boards and/or power cycling the AWR2243 is useful in the case where nothing is working; this should be your first option to see if things get fixed.

### Details about how the AWR2243 and DCA1000EVM are set up in the script:

#### AWR Board:
1. Change into `Node/setup_radar/build` directory
2. Run `./setup_radar`  
Note: if running into an issue when setting up AWR board, just power cycle it  (setup_radar executable was giving me some error) 

#### DCA Board:
1. Change into `Node/DCA1000/SourceCode/Release` directory
2. Run `./DCA1000EVM_CLI_Control fpga DCAconfig.json`
3. Run `./DCA1000EVM_CLI_Control record DCAconfig.json`  
    STOP HERE: Have you run `./setup_radar` yet? If not, run that first, then continue.
4. Run `./DCA1000EVM_CLI_Control start_record DCAconfig.json`

When we inherited the codebase from the previous capstone group, all of these commands were run manually to get the radar board ready for frame capture. Now with the `run_tests.sh` shell script, users have a CLI that performs the setup automatically. 

## How to Modify Radar Parameters
Before collecting data on the radar, you probably want to configure settings such as the max range, max Doppler (radial velocity), range resolution, and Doppler resolution that the radar can detect.  

Under `Chirp/Node/setup_radar`, there’s a file called mmwaveconfig.txt; this file contains a bunch of parameters that modify C-style structs in the mmWaveAPI (this API basically just sends data to the radar board to configure settings). These structs are called rlProfileCfg_t, rlChirpCfg_t, etc.  

More in-depth definitions are at this [link](https://astroa.net/fmcw-RADAR/mmwave_sdk/packages/ti/control/mmwavelink/docs/doxygen/html/annotated.html). Under the ‘Data Structures’ tab, look for the struct that you want to modify. Inside of this struct, there are data fields that tell you how to set bits to get the final value that you type into the mmwaveconfig.txt parameter.  

## Overview of Matlab Radar Processing Pipeline
Contains the original codebase for the end-to-end mmSnap Pipeline containing the blocks for:

- [Range-Doppler-Angle Processing](#range-doppler-angle-processing)
- [Tracking](#tracking)
- [Self-Calibration](#self-calibration)
- [One-Shot Fusion](#one-shot-fusion)

Much of our existing pipeline in Node/src is adapted from this code. 

### (1) Range-Doppler-Angle Processing

- Input : 5D Radar Cube Data (Format : Frames X Chirps per Frame X Num_Rx X Num_Tx X ADC Samples)
- Output : (Range, Doppler, Angle) for detections
- Summary : The raw ADC data is converted from its original radar cube format 
into Range-Doppler-Angle point clouds for each frame by applying Fast Fourier Transforms (FFTs) 
along the relevant dimensions. To concentrate on moving targets, 
static clutter removal is conducted, followed by the application of a 
two-dimensional Ordered-Statistics Constant False Alarm Rate (2D OS-CFAR) 
detection across the frames for additional refinement.

### (2) Tracking 

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

### (3) Self-Calibration

- Input : Tracks from both radar perspectives
- Output : Relative Optimal Pose Estimates (Calibration)
- Summary : We integrate target tracking with pose estimation by “matching” 
each node’s observation of a common target in a least-squares sense, 
yielding a closed-form calibration solution. 

### (4) One-Shot Fusion

- Input : Centroids from both Radar Perspectives, Calibration
- Output : Instantaneous Fused State and State Covariance estimates of targets
- Summary : We firstly match the centroids from both radar perspectives using 
the Hungarian Algorithm. Then we perform a Regularized Non-Linear Least Squares 
Optimization to obtain the Bayesian one-shot fused estimate using suitable 
priors for human motion.


## Link to Paper

Arxiv Link : [mmSnap](https://arxiv.org/abs/2505.00857)