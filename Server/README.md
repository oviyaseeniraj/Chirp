From the directory containing `docker-compose.yml`, run:

```bash
cd /home/chirp/Documents/Chirp/Server
docker compose up -d --build
```

## Docker Containers

It is important to note that this current organization is a prototype. There is probably a better way to organize the different processes for cleaner separation of responsibilites. In particular the MQTT broker logic can probably be cleaned up (it is split into bridge and nanomq).

There are also may be few missing steps, possibly continuous time-synchronization can be included in calibration logic. 

### bridge
MQTT message bridge that subscribes to topics and forwards data between services. Handles communication routing and data flow between different components of the system.

### calibration
Calibration service that processes radar calibration data. Includes a controller for managing calibration workflows and generating calibration results.

### dashboard
Web dashboard interface for monitoring and visualizing system data. Provides a user-friendly UI for system status and metrics.

### db
PostgreSQL database service that persists application data. Initialized with `init.sql` for schema setup and data seeding.

### nanomq
MQTT message broker that handles publish/subscribe messaging between services. Includes authentication configuration for multiple nodes (node1-node4) and a dedicated chirp user.

## Useful Commands

```
docker compose ps
docker compose logs -f
docker compose down
```
