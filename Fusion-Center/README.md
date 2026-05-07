The Fusion Center is the base station that connects to all the nodes, issues commands, and fuses the radar point clouds into one coherent map. It runs on the **Jetson Xavier** device, which we will use as our "server" node. 

The server node will need to run two things:
    1. an MQTT broker (Mosquitto)
    2. `server_controller.py`, which is subscribed to certain topics that allow the server to listen for the laptop start command, and ACKs from each radar node in the network
  
In order to start up both of these services, you will need to follow these steps:
    1. start a Python virtual environment (.venv) in `Chirp/Fusion-Center`
    2. install dependencies within the .venv using `pip install -r requirements.txt`
    3. install Docker for Ubuntu using the [link](https://docs.docker.com/engine/install/ubuntu/) provided within the README.md located in `Chirp/Fusion-Center/MQTT-Broker`
    4. start up the MQTT broker by running the `./start_broker.sh` Bash script in the `Chirp/Fusion-Center/MQTT-Broker` path
    5. lastly, run `./start_server_controller.sh` in the `Chirp/Fusion-Center` path


An external laptop will need to run the code located in the `/Laptop` directory located within this folder. 