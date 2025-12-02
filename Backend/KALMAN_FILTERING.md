# Kalman Filtering for Multi-Target Calibration

Quick guide for using and debugging the Extended Kalman Filter (EKF) multi-target tracking system.

**Supports:** 2+ radar nodes with multiple moving targets per scene.

## Quick Start

```bash
# 1. Rebuild with Kalman filtering
cd /Users/oseeniraj/Chirp/Backend
docker-compose up -d --build calibration_processor

# 2. Trigger Jetsons (from your Mac)
cd /Users/oseeniraj/Chirp
./scripts/trigger_all_jetsons.sh

# 3. Watch calibration logs
docker logs -f calibration_processor
```

## What You'll See

**2-radar, multi-target scenario:**
```
Running Kalman filtering for multi-target tracking...
  Patrick: 3 valid tracks detected
  Mike: 2 valid tracks detected

Calibrating 2 radar pairs: [('Patrick', 'Mike'), ('Mike', 'Patrick')]
Running multi-target calibration...
  Total track combinations tested: 12

✓ Multi-target calibration complete!
  Best calibration for each radar pair:

    Patrick → Mike: P=(40.12, -0.23)m, θ=89.8°, residual=0.156
      Using tracks: 2 ↔ 1 (45 frames)
    Mike → Patrick: P=(-40.08, 0.21)m, θ=-90.2°, residual=0.148
      Using tracks: 1 ↔ 2 (45 frames)

  Summary: Calibrated 2/2 radar pairs
  Mean residual: 0.152
```

**3-radar system:**
```
Running Kalman filtering for multi-target tracking...
  Patrick: 2 valid tracks detected
  Mike: 2 valid tracks detected
  John: 1 valid tracks detected

Calibrating 6 radar pairs: [('Patrick', 'Mike'), ('Patrick', 'John'), 
                            ('Mike', 'Patrick'), ('Mike', 'John'),
                            ('John', 'Patrick'), ('John', 'Mike')]
Running multi-target calibration...
  Total track combinations tested: 24

✓ Multi-target calibration complete!
  Best calibration for each radar pair:

    Patrick → Mike: P=(40.15, -0.18)m, θ=89.9°, residual=0.167
      Using tracks: 1 ↔ 2 (48 frames)
    Patrick → John: P=(20.05, 34.64)m, θ=60.1°, residual=0.198
      Using tracks: 1 ↔ 1 (48 frames)
    Mike → Patrick: P=(-40.12, 0.15)m, θ=-90.1°, residual=0.165
      Using tracks: 2 ↔ 1 (48 frames)
    Mike → John: P=(-20.08, 34.70)m, θ=119.8°, residual=0.203
      Using tracks: 2 ↔ 1 (48 frames)
    John → Patrick: P=(-20.03, -34.67)m, θ=-60.2°, residual=0.195
      Using tracks: 1 ↔ 1 (48 frames)
    John → Mike: P=(20.11, -34.72)m, θ=-60.3°, residual=0.201
      Using tracks: 1 ↔ 2 (48 frames)

  Summary: Calibrated 6/6 radar pairs
  Mean residual: 0.188
```

## Debug: No Tracks Detected

**Symptom:**
```
Patrick: 0 valid tracks detected
✗ Insufficient radars with valid tracks
```

**Causes & Fixes:**

### 1. Not Enough Frames
Tracks need ≥10 frames (default `MIN_TRACK_LENGTH`)

**Fix:** Collect more frames or lower threshold
```yaml
# docker-compose.yaml
environment:
  MIN_TRACK_LENGTH: "5"  # Lower threshold
```

### 2. Targets Moving Too Little
Kalman filter may reject static objects

**Check:** Are people/targets actually moving in the scene?

### 3. Clustering Too Aggressive
DBSCAN may be filtering out valid detections

**Fix:** Increase cluster epsilon
```yaml
environment:
  DBSCAN_EPS: "1.0"  # Larger = more permissive (default: 0.5)
  DBSCAN_MIN_SAMPLES: "2"  # Lower = easier to form clusters (default: 3)
```

### 4. Check Raw Data
```bash
# Verify frames are being ingested
docker exec -it postgres psql -U user -d mqttdata

# Check frame counts per radar
SELECT radar_name, COUNT(*), MIN(frame_number), MAX(frame_number) 
FROM radar_frames 
WHERE processed = FALSE 
GROUP BY radar_name;

# View sample frames
SELECT radar_name, frame_number, angle, range 
FROM radar_frames 
ORDER BY created_at DESC 
LIMIT 20;
```

## Debug: High Residuals

**Symptom:**
```
Best calibration: residual=5.234  (> 1.0 is concerning)
```

**Causes & Fixes:**

### 1. Wrong Track Pairing
System paired unrelated targets between radars

**Check logs:**
```
Total track combinations tested: 6
```

If many combinations but all have high residuals → targets may not overlap in field of view

### 2. Measurement Noise Too Low
Filter trusts noisy measurements too much

**Fix:** Increase noise parameters
```yaml
environment:
  SIGMA_RANGE: "0.1"      # Higher = less trust in range (default: 0.035)
  SIGMA_AZIMUTH: "45"     # Higher = less trust in angle (default: 30)
```

### 3. Process Noise Too Low
Motion model too rigid for erratic movement

**Fix:** Increase process noise
```yaml
environment:
  PROCESS_NOISE_STD: "0.1"  # Higher = more flexible motion (default: 0.025)
```

## Debug: Too Many Tracks

**Symptom:**
```
Patrick: 15 valid tracks detected  (expected 1-3)
```

**Causes & Fixes:**

### 1. Noise Being Tracked
DBSCAN creating clusters from random detections

**Fix:** Tighten clustering
```yaml
environment:
  DBSCAN_EPS: "0.3"          # Smaller = stricter (default: 0.5)
  DBSCAN_MIN_SAMPLES: "5"    # Higher = fewer clusters (default: 3)
```

### 2. Track Fragments
Single target split into multiple tracks

**Fix:** Relax association gate
```yaml
environment:
  MAHALANOBIS_GATE: "12.0"  # Higher = associate further detections (default: 9.0)
```

### 3. Lower Track Length Requirement
```yaml
environment:
  MIN_TRACK_LENGTH: "20"  # Higher = only long tracks (default: 10)
```

## Tuning Parameter Guide

| Parameter | What It Does | Increase When | Decrease When |
|-----------|--------------|---------------|---------------|
| `SIGMA_RANGE` | Range measurement trust | Radar noisy | Radar accurate |
| `SIGMA_AZIMUTH` | Angle measurement trust | Wide beamwidth | Narrow beamwidth |
| `DBSCAN_EPS` | Clustering radius | Targets far apart | Targets close together |
| `DBSCAN_MIN_SAMPLES` | Cluster threshold | Too many false clusters | Missing real targets |
| `MIN_TRACK_LENGTH` | Track validity | Too many short tracks | Not enough tracks |
| `MAHALANOBIS_GATE` | Association distance | Tracks drop frequently | Wrong associations |

## View Results in Database

```bash
# Connect to database
docker exec -it postgres psql -U user -d mqttdata

# Latest calibration results
SELECT * FROM latest_calibration;

# All calibration history
SELECT 
    ref_radar, 
    target_radar, 
    position_x, 
    position_y, 
    orientation_deg,
    residual,
    num_frames,
    timestamp 
FROM calibration_results 
ORDER BY timestamp DESC;

# Check which frames were used
SELECT radar_name, COUNT(*) as frames_used
FROM radar_frames 
WHERE processed = TRUE
GROUP BY radar_name;
```

## Reset and Reprocess

Want to try different parameters without collecting new data?

```bash
# Mark all frames as unprocessed
docker exec -it postgres psql -U user -d mqttdata -c \
  "UPDATE radar_frames SET processed = FALSE;"

# Restart calibration processor (will reprocess frames)
docker restart calibration_processor

# Watch with new parameters
docker logs -f calibration_processor
```

## Expected Performance

**Good calibration indicators:**
- ✅ Residual < 0.5 (excellent)
- ✅ Residual < 1.0 (good)
- ⚠️ Residual > 1.0 (check parameters)
- ❌ Residual > 2.0 (likely wrong track pairing)

**Track counts:**
- Single target: 1 track per radar
- Multi-target: 2-4 tracks per radar (depends on scene)
- > 10 tracks: Likely noise, tighten parameters

**Calibration pairs:**
- 2 radars: 2 pairs (A→B, B→A)
- 3 radars: 6 pairs (all directed combinations)
- N radars: N×(N-1) pairs

## Still Having Issues?

1. **Check service logs:**
   ```bash
   docker logs ingest              # Data ingestion
   docker logs calibration_processor  # Kalman filtering
   docker logs nanomq              # MQTT broker
   ```

2. **Verify Jetson connectivity:**
   ```bash
   # Test from Mac
   ssh fusionsense@169.231.217.90
   ssh fusionsense@169.231.22.160
   ```

3. **Check frame synchronization:**
   ```sql
   -- Should show similar frame numbers for all radars
   SELECT radar_name, MAX(frame_number) 
   FROM radar_frames 
   GROUP BY radar_name;
   ```

4. **Enable Python debug output:**
   ```yaml
   # docker-compose.yaml
   environment:
     PYTHONUNBUFFERED: 1
     LOG_LEVEL: DEBUG  # If implemented
   ```

