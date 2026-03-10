Data flow: 
1. Nodes start up all processes and continuously ping the arbitrator waiting for it to start up and gives the node a deadline to start on. 
2. Fusion Node fires up the arbitrator which collects the proposed deadlines. 
3. Nodes start collecting data and processing them generating a directory of processed data per frame. 
4. Data is sent to the Fusion Node through port 5001, which the Fusion node is able to sort via each ip address receieved in step 2. This Data is then stored in a Database.
    1. Maybe we should just store the centroid and timestamp so we might need to sent that on a separate port
5. Once a minimal consecutive number of frames recieved is reached, the Fusion Node will start the tracking process, running EKF on each to generate one trajectory per node, then run the spatial calibration. 

Vision:
Visualizer running on Fusion Node, home page is a fleet manager page that can start up all the Nodes by giving the ip addresses. 
Typing in the ip address should build a device that is identified by the hostname (obtained somehow or through bash command `hostname`). 
Fusion Center needs to generate a ssh key that is copied onto each Jetson then we just store the private key somewhere to create new fusion centers easily. 
We can then push some button to activate all the Nodes, then the Fusion center will start up and run the arbitrator and collect the data. 

trajectory_gen_playback.py: 
builds ontop of playback_test.py for a bigger integration test. 
Add a database.py to Fusion Node to store the data. Currently data should just be written to a temporary folder or something. 
Add a calibration.py to Fusion Node that reads from the database and runs EKF to generate a trajectory with infrastructure to support spatial calibration dictated in `four_node_calibration.py`.

Update Playback Test: 
- Playback test should be triggering on a local simulated trigger that playback DAQ should send frames on receiving. 
 