This directory should contain everything required for a node (Jetson + AWR2243 + DCA1000EVM)

Most code has been taken from Percept ([Multi-Node-App](https://github.com/Percept-2023-24/Multi-Node-App)), which built on top of Fusionsense ([Radar Pipeline](https://github.com/FusionSense/RadarPipeline) & [JetsonHardwareSetup](https://github.com/FusionSense/JetsonHardwareSetup)), and been refactored to be more readable and compatible with CMake.


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

## Testing & Data Capture
For running the radar, capturing data, and performing offline analysis, see the [test/README.md](test/README.md).
- **Test Runner**: Use `sudo ./test/run_tests.sh` for an interactive menu of live tests, capture, and data conversion.
- **Conversion**: Option **4** in the test runner converts raw radar data to MATLAB `.mat` files with automated complex conversion.
