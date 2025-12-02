# Jetson Configuration Reference

## Your Jetsons

| Name | IP | Role | Notes |
|------|-------|------|-------|
| **Master** | `169.231.217.90` | Chrony time server, MQTT broker | Primary node |
| **Slave** | `169.231.22.160` | Chrony time client | Secondary node |

## Quick Commands

### Test Without Jetsons (Simulated)
```bash
cd Backend
docker-compose up -d
python3 services/test_publisher.py --broker localhost --radars 2 --frames 100
docker logs -f calibration_processor
```

### Trigger All Jetsons Simultaneously
```bash
cd /Users/oseeniraj/Chirp
./scripts/trigger_all_jetsons.sh
```

### Manual Testing on Single Jetson
```bash
# SSH to Master
ssh fusionsense@169.231.217.90

# Collect data
cd ~/Documents/Chirp/Node/test/non_thread
./test 100

# Publish to MQTT (Master has the broker)
cd ~/Documents/Chirp/Node
./scripts/mqtt_publish_frames.sh
```

### Check Time Synchronization
```bash
# On Master (time server)
ssh fusionsense@169.231.217.90
chronyc clients

# On Slave (time client)
ssh fusionsense@169.231.22.160
chronyc tracking
# Look for: "System time: 0.000XXX seconds" (should be < 1ms offset)
```

## Network Architecture

```
Master (169.231.217.90)
├── Chrony Server (port 123)
├── MQTT Broker (port 1883)
└── Radar Data Collection

Slave (169.231.22.160)
├── Chrony Client → Master
└── Radar Data Collection

Your Mac
├── Backend Services (Docker)
│   ├── MQTT Broker (optional, for local testing)
│   ├── PostgreSQL
│   └── Calibration Processor
└── SSH → Jetsons
```

## Environment Setup

All configuration is in `.jetson_config`:
```bash
MASTER_IP="169.231.217.90"
SLAVE_IP="169.231.22.160"
SSH_USER="fusionsense"
MQTT_BROKER="169.231.217.90"
```

## Common Tasks

### Deploy New Code to Jetsons
```bash
# Copy MQTT publisher
scp Node/src/rpl/mqtt_publisher.py fusionsense@169.231.217.90:~/
scp Node/src/rpl/mqtt_publisher.py fusionsense@169.231.22.160:~/

# Copy publish script
scp Node/scripts/mqtt_publish_frames.sh fusionsense@169.231.217.90:~/Documents/Chirp/Node/scripts/
scp Node/scripts/mqtt_publish_frames.sh fusionsense@169.231.22.160:~/Documents/Chirp/Node/scripts/
```

### Check Jetson Status
```bash
# Verify all Jetsons are reachable
for ip in 169.231.217.90 169.231.22.160; do
    echo -n "Testing $ip: "
    ssh -o ConnectTimeout=3 fusionsense@$ip "echo OK" || echo "FAILED"
done
```

### View Jetson Logs
```bash
# SSH to Jetson
ssh fusionsense@169.231.217.90

# View test output
cat ~/Documents/Chirp/Node/test/non_thread/test_output.log

# Check frame data
ls ~/Documents/Chirp/Node/test/non_thread/frame_data/*.json | wc -l
```

### Clean Old Data
```bash
# On Jetson
ssh fusionsense@169.231.217.90
rm -f ~/Documents/Chirp/Node/test/non_thread/frame_data/*.json

# Or from Mac (all Jetsons)
for ip in 169.231.217.90 169.231.22.160; do
    ssh fusionsense@$ip "rm -f ~/Documents/Chirp/Node/test/non_thread/frame_data/*.json"
done
```

## MQTT Broker Location

The MQTT broker runs on the **Master node** (169.231.217.90).

All Jetsons publish to: `mqtt://169.231.217.90:1883`

## Time Synchronization Notes

- **Master** runs chrony in **server mode**
- **Slave** syncs time from Master
- Target accuracy: < 1ms offset
- Verify with: `chronyc tracking` on Slave

## Calibration Data Flow

```
Master Jetson                      Slave Jetson
     │                                  │
     ├─ Collect frame #1                ├─ Collect frame #1
     ├─ Publish to MQTT                 ├─ Publish to MQTT
     │   (Master's broker)              │   (Master's broker)
     │        │                         │        │
     │        └─────────┬───────────────┘        │
     │                  ▼                        │
     │           MQTT Broker (Master)            │
     │                  │                        │
     │                  ▼                        │
     │         Backend Ingest Service            │
     │                  │                        │
     │                  ▼                        │
     │            PostgreSQL Database            │
     │                  │                        │
     │                  ▼                        │
     │       Calibration Processor               │
     │       (Waits for frame #50                │
     │        from both radars)                  │
     │                  │                        │
     ├─ Frame #50 ──────┤                        │
     │                  │                        │
     │                  ├────────────── Frame #50│
     │                  │                        │
     │                  ▼                        │
     │          ✓ TRIGGER! Calibrate             │
     │                                           │
```

## Troubleshooting

### SSH Connection Failed
```bash
# Check network
ping 169.231.217.90

# Check SSH key
ssh-add -l

# Try with password
ssh -o PreferredAuthentications=password fusionsense@169.231.217.90
```

### Time Sync Issues
```bash
# On Slave, check sync status
ssh fusionsense@169.231.22.160
chronyc sources -v

# Should show Master as current time source
```

### MQTT Connection Failed
```bash
# Check if broker is running on Master
ssh fusionsense@169.231.217.90
sudo systemctl status nanomq

# Or if running in Docker:
docker ps | grep nanomq
```

### No Calibration Trigger
```bash
# Check database for frames
docker exec -it postgres psql -U user -d mqttdata -c "
SELECT radar_name, MAX(frame_number) 
FROM radar_frames 
WHERE processed = FALSE 
GROUP BY radar_name;"
```


