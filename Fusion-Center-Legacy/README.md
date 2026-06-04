# Overview

## What does the Fusion Center do?

The Fusion Center is the base station that connects to all the nodes, issues commands, and fuses the centroids/track data from each radar node into one coherent visualizer. The Fusion Center runs on the **Jetson Xavier** device, which we will use as our "server" node. 

**NOTE:** It will be important to note down the IP address of the "server" node in your network. If the IP address is changed, then communication within the network can break down. The IP address NEEDS to be changed in the `.env` file within the `MQTT-Broker/` directory if the IP address of the server node changes.

# PLEASE NOTE THIS IS LEGACY CODE. Please refer to Chirp/Server for the most recent implementation


## What does the Fusion Center run?

The server node will need to run two things:
1. An MQTT broker (Mosquitto) running on port 1883; this handles routing of messages sent across devices
2. `server_controller.py`, which is subscribed to certain topics that allow the server to listen for the laptop start command, and ACKs from each radar node in the network
  
In order to start up both of these services, you will need to follow these steps:
1. Start a Python virtual environment (.venv) in `Chirp/Fusion-Center`
2. Install dependencies within the .venv using `pip install -r requirements.txt`
3. Install Docker for Ubuntu using the [link](https://docs.docker.com/engine/install/ubuntu/) provided within the README.md located in `Chirp/Fusion-Center/MQTT-Broker`
4. Start up the MQTT broker by running the `./start_broker.sh` Bash script in the `Chirp/Fusion-Center/MQTT-Broker` path
5. Lastly, run `./start_server_controller.sh` in the `Chirp/Fusion-Center` path

An external laptop will need to run the code located in the `/Laptop` directory located within this folder (for the laptop trigger). 