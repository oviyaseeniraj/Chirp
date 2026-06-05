This directory should contain everything required for a node (Jetson + AWR2243 + DCA1000EVM)


EXTRA STUFF:
added a launch service so that we dont need to ssh to the nodes to start the pipeline. chirp-launcher automatically pings the fusion-center if the network setup is correctly completed. 

added a pull listener service - can probably be turned into a full server listener to manage fpga, pipeline, and pull updates from github. 




# Copy to systemd
sudo cp /home/chirp/Chirp/Node/scripts/chirp-launcher.service /etc/systemd/system/

# Set up pull listener
Again, the current organization can be cleaned up into separate directories. 

For setup, copy .pull_listener_env.example into .pull_listener_env. 
Add the github pull token (that authenticates your request) to this environment file. 

cd scripts 
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


