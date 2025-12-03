# Real-Time Radar Calibration System

Event-driven spatial calibration for multi-radar networks using frame-number synchronization.

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│ JETSONS: Collect & Publish Frames                          │
│   Patrick: Frame 1, 2, 3, ..., 50 → MQTT                   │
│   Mike:    Frame 1, 2, 3, ..., 50 → MQTT                   │
│   John:    Frame 1, 2, 3, ..., 50 → MQTT                   │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│ DATABASE: Store with frame numbers                          │
│   radar_frames table (radar_name, frame_number, angle, ...) │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│ TRIGGER: When ALL radars reach frame #50                    │
│   ✓ Patrick has frames 1-50                                │
│   ✓ Mike has frames 1-50                                   │
│   ✓ John has frames 1-50                                   │
│   → Run calibration on frames 1-50                         │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│ CALIBRATION: Closed-form solution                           │
│   Position: P_patrick_to_mike = (40.0, 0.0)m               │
│   Orientation: θ = 90.0°                                    │
│   Residual: 0.234                                           │
└─────────────────────────────────────────────────────────────┘
```

## Key Innovation: Frame-Number-Based Triggering

**Old approach (timer-based):** Wait 60 seconds, grab whatever frames exist
- ❌ No guarantee of synchronization
- ❌ May use mismatched frames
- ❌ Arbitrary time delays

**New approach (frame-based):** Trigger when frame #X received from ALL radars
- ✅ Perfect synchronization (all radars observed same moment)
- ✅ Immediate triggering (no arbitrary wait)
- ✅ Uses frame numbers from JSON filenames

**Example:**
```
t=0s:    Patrick sends frame #1, Mike sends frame #1
t=0.1s:  Patrick sends frame #2, Mike sends frame #2
...
t=5.0s:  Patrick sends frame #50, Mike hasn't reached #50 yet
t=5.1s:  Mike sends frame #50
         → TRIGGER! Calibrate on frames 1-50
```

## Multi-Target Tracking with Kalman Filtering

The calibration processor now includes Extended Kalman Filter (EKF) tracking for robust multi-radar, multi-target scenarios.

**Key Features:**
- ✅ **Scales to N radars** - calibrates all pairwise relationships (2, 3, 4+ nodes)
- ✅ **Multi-target per scene** - handles multiple people/objects moving simultaneously
- ✅ **EKF for polar→Cartesian** - proper uncertainty propagation from measurements
- ✅ **DBSCAN clustering** - separates distinct targets in each frame
- ✅ **Track association** - maintains target identity using Mahalanobis gating
- ✅ **Best-fit selection** - tests all track combinations per radar pair

**Calibration Output:**
- 2 radars → 2 directed pairs (A→B, B→A)
- 3 radars → 6 directed pairs (all combinations)
- N radars → N×(N-1) directed pairs

**📖 See [KALMAN_FILTERING.md](KALMAN_FILTERING.md) for:**
- Quick start guide
- Debugging tips
- Parameter tuning
- 3-radar example output

**Example (2 radars, multi-target):**
```
Running Kalman filtering for multi-target tracking...
  Patrick: 3 valid tracks detected
  Mike: 2 valid tracks detected

Calibrating 2 radar pairs...
Best calibration for each radar pair:
  Patrick → Mike: P=(40.12, -0.23)m, θ=89.8°, residual=0.156
  Mike → Patrick: P=(-40.08, 0.21)m, θ=-90.2°, residual=0.148
Summary: Calibrated 2/2 radar pairs, Mean residual: 0.152
```

## Quick Start

### Option A: Test Without Jetsons (Recommended First)

```bash
# 1. Start backend
cd Backend
docker-compose up -d

# 2. Run test publisher (simulates 2 radars)
# Option 2a: Using helper script
./run_test.sh --broker localhost --radars 2 --frames 100

# Option 2b: Using venv directly
source venv/bin/activate
python3 services/test_publisher.py --broker localhost --radars 2 --frames 100

# 3. Watch calibration
docker logs -f calibration_processor
```

See [TEST_WITHOUT_JETSONS.md](TEST_WITHOUT_JETSONS.md) for details.

### Option B: With Real Jetsons

#### Manual (one Jetson at a time):
```bash
# On each Jetson - NOTE: pass the node name as 2nd argument!
ssh fusionsense@169.231.216.36
cd ~/Documents/Chirp/Node/test/non_thread
./test 100 Master          # Creates Master_Frame1.json, Master_Frame2.json, etc.

# On second Jetson
ssh fusionsense@169.231.22.160
cd ~/Documents/Chirp/Node/test/non_thread
./test 100 Slave           # Creates Slave_Frame1.json, Slave_Frame2.json, etc.

# Publish to MQTT
cd ~/Documents/Chirp/Node
./scripts/mqtt_publish_frames.sh
```

#### Automatic (all Jetsons simultaneously): ⭐
```bash
# From your Mac - triggers all Jetsons at once!
cd /Users/oseeniraj/Chirp
./scripts/trigger_all_jetsons.sh

# Your Jetsons:
#   Master: 169.231.216.36
#   Slave:  169.231.22.160
```

## Test Binary CLI Arguments

The `./test` binary supports configurable node naming via command-line arguments:

```bash
# Usage options:
./test                              # 100 frames, node name = "Node"
./test <num_frames>                 # Custom frame count, node name = "Node"
./test <num_frames> <node_name>     # Custom frames AND node name ⭐
./test <max_SNR> <min_SNR>          # SNR threshold mode

# Examples:
./test 100 Master     # Collect 100 frames, save as Master_Frame1.json, etc.
./test 50 Slave       # Collect 50 frames, save as Slave_Frame1.json, etc.
./test 200 Radar3     # Collect 200 frames, save as Radar3_Frame1.json, etc.
```

**Why this matters:** The node name is embedded in:
1. **JSON filename:** `{NodeName}_Frame{N}.json`
2. **JSON content:** `{"Node": "Master", "Frame Number": 1, ...}`
3. **MQTT topic:** `radar/{NodeName}/frame`
4. **Database:** `radar_name` column in `radar_frames` table

**How `trigger_all_jetsons.sh` uses this:**
```bash
# The script automatically passes the node name from JETSON_NAMES array:
JETSON_NAMES=("Master" "Slave")
JETSON_IPS=("169.231.216.36" "169.231.22.160")

# Results in these SSH commands:
ssh fusionsense@169.231.216.36 "xvfb-run -a ./test 100 Master"
ssh fusionsense@169.231.22.160 "xvfb-run -a ./test 100 Slave"
```

## C++ Implementation Details

The `JSON_TCP` class in `Node/src/rpl/implementation.cpp` was modified to support configurable node names:

```cpp
// Before (hardcoded):
const char *node = "Patrick";  // Always saved as Patrick_Frame1.json

// After (configurable):
class JSON_TCP {
    string node_name;
public:
    JSON_TCP(const string& name = "Node") : node_name(name) { }
    void setNodeName(const string& name) { node_name = name; }
    string getNodeName() const { return node_name; }
    // ...
};
```

**In `test.cpp`:**
```cpp
// Parse CLI arguments
std::string node_name = "Node";
if (argc >= 3) {
    node_name = argv[2];
}

// Pass to JSON_TCP
JSON_TCP tcp(node_name);
// or: tcp.setNodeName(node_name);
```

### 3. Monitor Calibration
```bash
docker logs -f calibration_processor
```

## `trigger_all_jetsons.sh` Quick Reference

### Usage
```bash
cd /path/to/Chirp
./scripts/trigger_all_jetsons.sh
```

### What It Does
1. ✅ Checks SSH connectivity to all Jetsons
2. ✅ Checks/installs `xvfb` (needed for headless GUI)
3. ✅ Optionally cleans old frame data
4. ✅ Triggers `./test <frames> <node_name>` on all Jetsons simultaneously
5. ✅ Optionally starts MQTT publishers

### Configuration (edit script lines 7-8)
```bash
JETSON_NAMES=("Master" "Slave")              # Names used in JSON files
JETSON_IPS=("169.231.216.36" "169.231.22.160")  # IP addresses
```

### What to Watch in Docker Logs

```bash
# Watch calibration processor
docker logs -f calibration_processor
```

**✅ Good signs:**
```
Radar status:
  Master: frame #50
  Slave: frame #50
TRIGGER: All 2 radars have reached frame #50
Running Kalman filtering...
  Master: 1 valid tracks detected
  Slave: 1 valid tracks detected
✓ Calibration complete!
```

**⚠️ Warning signs:**
```
# Only one radar has data
Radar status:
  Master: frame #50
  Slave: frame #0          # ← Slave not sending data

# Waiting for sync
Min frame across radars: 45 (need 50 for trigger)

# No tracks detected
Master: 0 valid tracks detected   # ← No motion/targets in FOV
```

**❌ Error signs:**
```
# Database connection failed
asyncpg.exceptions.ConnectionError

# Missing frames
Calibration failed - missing frames 23, 24, 25
```

### Verify Data in Database
```bash
# Check frame counts per radar
docker exec postgres psql -U user -d mqttdata -c "
SELECT radar_name, COUNT(*) as frames, MAX(frame_number) as max_frame 
FROM radar_frames 
GROUP BY radar_name;"

# Expected output:
#  radar_name | frames | max_frame
# ------------+--------+-----------
#  Master     |    100 |       100
#  Slave      |    100 |       100

# Check recent frames
docker exec postgres psql -U user -d mqttdata -c "
SELECT radar_name, frame_number, angle, range_m 
FROM radar_frames 
ORDER BY id DESC LIMIT 10;"

# Check calibration results
docker exec postgres psql -U user -d mqttdata -c "
SELECT ref_radar, target_radar, position_x, position_y, orientation_deg, residual 
FROM calibration_results 
ORDER BY timestamp DESC LIMIT 5;"
```

### Troubleshooting

| Problem | Check | Fix |
|---------|-------|-----|
| SSH fails | `ssh fusionsense@IP` | Check network/keys |
| xvfb error | Script offers to install | Say yes to install |
| No frames in DB | `docker logs ingest` | Check MQTT connection |
| Only 1 radar in DB | Check both Jetsons ran | Re-run trigger script |
| No calibration trigger | Need MIN_RADARS (default 2) | Wait for all radars |
| High residual (>1.0) | Poor calibration quality | More frames, better target motion |

Output:
```
============================================================
TRIGGER: All 2 radars have reached frame #50
============================================================
  Radar status:
    Mike: frame #50
    Patrick: frame #50
  Running calibration on frames 1-50...

  ✓ Calibration complete!
  Frames used: 1-50 (50 frames)
    Patrick → Mike: P=(40.12, -0.34)m, θ=89.8°, residual=0.234
```

### 4. Query Results
```bash
docker exec -it postgres psql -U user -d mqttdata -c "
SELECT ref_radar, target_radar, 
       position_x, position_y, 
       orientation_deg, 
       timestamp 
FROM calibration_results 
ORDER BY timestamp DESC 
LIMIT 5;"
```

## Configuration

Edit `docker-compose.yaml`:

```yaml
calibration_processor:
  environment:
    CALIBRATION_WINDOW: 50    # Use last 50 frames for each calibration
    CHECK_INTERVAL: 2.0       # Check for new frames every 2 seconds
    MIN_RADARS: 2             # Minimum radars required
```

**CALIBRATION_WINDOW:** Number of frames to use for calibration. More frames = more accurate.

**CHECK_INTERVAL:** How often to poll database. Lower = faster response, higher CPU.

**MIN_RADARS:** Minimum number of radars before calibration runs.

## Architecture

```
Backend/
├── services/                    # Service implementations
│   ├── calibration_processor.py # Frame-based calibration (NEW)
│   ├── ingest.py                # MQTT → Database (MODIFIED)
│   ├── test_publisher.py        # Simulated radar data for testing
│   ├── inject_real_frames.py    # Inject real JSON frames into MQTT
│   ├── keygen.py                # Node registration
│   └── publisher.py             # Demo publisher
│
├── sql/
│   └── init_db.sql              # Database schema
│
├── docker-compose.yaml          # Service orchestration
├── Dockerfile.*                 # Docker images
├── requirements.txt             # Python dependencies
└── README.md                    # This file

Node/
├── src/rpl/
│   ├── implementation.cpp       # JSON_TCP class with configurable node name
│   └── mqtt_publisher.py        # Jetson frame publisher
├── test/non_thread/
│   ├── test.cpp                 # Main binary (CLI: ./test <frames> <node_name>)
│   ├── test                     # Compiled binary
│   └── frame_data/              # Output JSON frames
└── scripts/
    └── mqtt_publish_frames.sh   # Bash wrapper

scripts/
└── trigger_all_jetsons.sh       # ⭐ Triggers all Jetsons with unique node names
```

## Database Schema

### radar_frames
Stores individual frame measurements:
```sql
CREATE TABLE radar_frames (
    radar_name VARCHAR(32),      -- 'Patrick', 'Mike', etc.
    frame_number INT,             -- From JSON filename
    angle FLOAT,                  -- Degrees
    range FLOAT,                  -- Meters
    timestamp_ns BIGINT,          -- Nanosecond timestamp
    processed BOOLEAN             -- Used in calibration?
);
```

### calibration_results
Stores computed calibration:
```sql
CREATE TABLE calibration_results (
    ref_radar VARCHAR(32),        -- Reference radar
    target_radar VARCHAR(32),     -- Target radar
    position_x FLOAT,             -- Relative X position (m)
    position_y FLOAT,             -- Relative Y position (m)
    orientation_deg FLOAT,        -- Relative orientation (degrees)
    residual FLOAT,               -- Quality metric (lower=better)
    num_frames INT,               -- Frames used
    timestamp TIMESTAMP           -- When computed
);
```

## Calibration Algorithm

**Input:** Frame-matched trajectory observations from N radars
- Each radar sees target at frames 1, 2, 3, ..., 50
- Polar coordinates (angle, range) → Cartesian complex numbers

**Process:** Closed-form solution for each radar pair (i, j):
1. **Correlation:** φ_ij = Σ (z_j[t] - mean(z_j)) * conj(z_i[t] - mean(z_i))
2. **Orientation:** θ_ij = -arctan2(imag(φ), real(φ))
3. **Position:** P_ij = mean(z_i) - exp(-i*φ) * mean(z_j)
4. **Residual:** Quality metric for calibration accuracy

**Output:** Relative position and orientation for each radar pair

## Trigger Conditions

Calibration runs when:
1. **At least MIN_RADARS radars** have sent data
2. **All radars have reached frame #X** where X ≥ CALIBRATION_WINDOW
3. **All frames in range exist** (no missing frames)

## Example Timeline

```
t=0s:     Patrick frame #1 → Database
          Mike frame #1 → Database
          
t=0-5s:   Frames accumulate (every ~100ms)
          Database: Patrick has 1-50, Mike has 1-48
          Processor checks: Mike only at #48, wait...

t=5.1s:   Mike frame #49 → Database
          Processor checks: Mike at #49, wait...

t=5.2s:   Mike frame #50 → Database
          ✓ TRIGGER! Both radars have frames 1-50
          
t=5.3s:   Calibration runs on frames 1-50
          Results stored in database
          Frames 1-50 marked as processed

t=5.4s:   Next trigger will occur when both reach frame #100
```

## MQTT Topics

**Publish (from Jetson):** `radar/{radar_name}/frame`
```json
{
  "radar_name": "Patrick",
  "frame": 42,
  "angle": 45.5,
  "range": 12.3,
  "timestamp_ns": 1700000000000000000
}
```

**Subscribe (ingest service):** `radar/+/frame`

## Troubleshooting

### No calibration triggers
**Check:** Do all radars have data?
```bash
docker exec -it postgres psql -U user -d mqttdata -c "
SELECT radar_name, MAX(frame_number) as max_frame 
FROM radar_frames 
WHERE processed = FALSE 
GROUP BY radar_name;"
```

**Fix:** Ensure all Jetsons are publishing data

### Missing frames
**Check:** Processor logs show "missing frames"
```bash
docker logs calibration_processor | grep "missing"
```

**Fix:** Ensure MQTT publisher sends all frames (check `mqtt_publisher.py`)

### Poor calibration results
**Check:** Residual values (should be < 1.0)
```bash
docker logs calibration_processor | grep "residual"
```

**Fix:** 
- Increase CALIBRATION_WINDOW for more frames
- Verify time synchronization with chrony
- Check target is in overlapping FOV

### Services won't start
```bash
docker-compose logs
docker-compose down
docker-compose up -d --build
```

## Integration with Existing File-Based Workflow

The new real-time system **runs in parallel** with existing file-based calibration:

**File-based (still works):**
```bash
./test 100                           # Collect data
./collect_radar_calibration.sh       # SSH, copy, calibrate
```

**Real-time (new):**
```bash
./test 100 &                         # Collect data
./scripts/mqtt_publish_frames.sh     # Publish to MQTT
# → Automatic calibration when frame #50 arrives from all radars
```

Both use the same calibration algorithm, just different data flow!

## Performance

- **Frame publish latency:** <100ms
- **Database insert latency:** <50ms
- **Calibration trigger:** Immediate (when frame threshold reached)
- **Calibration computation:** 1-3 seconds (50 frames)
- **End-to-end:** ~5-10 seconds from data collection to calibration result

## Advantages Over Timer-Based

| Aspect | Timer-Based | Frame-Based (This System) |
|--------|-------------|---------------------------|
| Synchronization | Approximate | Perfect (same frame #) |
| Triggering | Fixed intervals | Event-driven |
| Latency | 30-60 seconds | ~5-10 seconds |
| Accuracy | Good | Excellent |
| Adaptivity | None | Automatic |

## Requirements

- **Backend:** Docker, Docker Compose
- **Jetson:** Python 3, paho-mqtt
- **Network:** MQTT broker accessible from all Jetsons
- **Time Sync:** Chrony recommended (but not required for frame-based matching!)

## Support

**Logs:**
```bash
docker logs calibration_processor  # Calibration
docker logs ingest                 # Data ingestion
docker logs postgres               # Database
```

**Database Query:**
```bash
docker exec -it postgres psql -U user -d mqttdata
```

**Restart Services:**
```bash
docker-compose restart calibration_processor
```

## Future Enhancements

1. **Multi-target calibration:** Extend to N radars simultaneously
2. **Sliding window:** Continuous recalibration with rolling frame buffer
3. **Web dashboard:** Real-time visualization of calibration results
4. **Adaptive window:** Adjust CALIBRATION_WINDOW based on motion
5. **Alert system:** Notify when calibration drift detected

