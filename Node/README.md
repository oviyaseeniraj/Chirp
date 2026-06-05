This directory should contain everything required for a node (Jetson + AWR2243 + DCA1000EVM)


EXTRA STUFF:
added a launch service so that we dont need to ssh to the nodes to start the pipeline. chirp-launcher automatically pings the fusion-center if the network setup is correctly completed. 

added a pull listener service - can probably be turned into a full server listener to manage fpga, pipeline, and pull updates from github. 

# Flashing the Jetson Orin Nano

tough luck buddy


# First Time getting into a Jetson
1. Without connecting the Jetson to the Internet, you have two options for interacting.
- connect to the HDMI port and display to a monitor (recommended)
- use a usb-c cable and connect to the serial port on the Jetson. Use a serial monitor to interact (the screen command on macOS is convenient
    1. ls /dev | grep usb - allows you to find the name of the new serial port (ex. cu.usbmodemXXXXXX)
    2. screen <port_name> 115200 - default baudrate is 115200

2. Enter credentials for the node (default user=chirp, default password=chirp)

# Copy pipeline launcher to systemd
sudo cp /home/chirp/Chirp/Node/scripts/chirp-launcher.service /etc/systemd/system/

# Set up pull listener
Again, the current organization can be cleaned up into separate directories. 

For setup, copy .pull_listener_env.example into .pull_listener_env. 
Add the github pull token (that authenticates your request) to this environment file. 

cd Chirp/Node/scripts 
./pull_listener_setup.sh

# Reload, enable at boot, start now
sudo systemctl daemon-reload
sudo systemctl enable chirp-launcher
sudo systemctl start chirp-launcher

# Check it's running
sudo systemctl status chirp-launcher

# Follow logs
sudo journalctl -u chirp-launcher -f


# Testing pipeline manually using /test
1. Run the following commands
```
cd test
source .venv/bin/activate
sudo ./run_tests.sh
```

2. Select test 1 (Full Integration Test)
3. Then select your choice of trigger:
 1) local trigger
 2) mqtt trigger

# Node Web Processes
Visualizer: 5001 - displays the data from each stage of the radar pipeline in a Range-Doppler plot and Range-Angle plot including
    - Range-Doppler bins with magnitude
    - CFAR detections
    - Centroids
    - Confirmed and Tentative Tracks
Logger: 5003 - displays log messages from the chirp-launcher and chirp_pull_listener services through a web interface. 

To view these processes, simply use the DNS name (ex. node1) if Tailscale is setup, or find the node IP to use as the address. In your web browser, type:
\<address\>:\<port\> to view the desired process. 

# Legacy Code

Most code has been adapted from Percept ([Multi-Node-App](https://github.com/Percept-2023-24/Multi-Node-App)), which built on top of Fusionsense ([Radar Pipeline](https://github.com/FusionSense/RadarPipeline) & [JetsonHardwareSetup](https://github.com/FusionSense/JetsonHardwareSetup)), and been refactored to be more readable and compatible with CMake.

#
## Inherited Work from Fusionsense
The fusionsense include the following components:
* A parent Radar Block Class
* Data Acquisition, which inherit from the Radar Block Class
    * 
* Visualizer, which inherit from the Radar Block Class
    * 
* Range Doppler, which inherit from the Radar Block Class
    * 
* JSON TCP
    * TBH I have no idea what the high level of this is doing

Design Doc:
We should have Data Acquisition produce frames for the Range Doppler to consume, which then produces both the doppler map and the point cloud, and the Visualizer to consume and produce a visualizer. There should be some sort of static dequeue between all of them. The visualizer is a little more complicated, it might be a list of point clouds which is not a constant size. These can technically be all run in parallel with the queue being the inter process communication scheme used. We might need a mutex for them to be thread safe. 

We use the library in the following way:

My current best guess is that each Radar Block iteration represents getting/processing a frame
 <!--TODO: include a block diagram of how they play into each other  -->


