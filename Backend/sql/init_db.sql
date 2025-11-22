-- Database schema for real-time radar calibration system
-- This file initializes the complete database schema

-- Existing table: radarData (from ingest.py)
CREATE TABLE IF NOT EXISTS radarData (
    id SERIAL PRIMARY KEY,
    uuid VARCHAR(32),
    data BYTEA,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Existing table: node_key (from keygen.py)
CREATE TABLE IF NOT EXISTS node_key (
    id SERIAL PRIMARY KEY,
    name VARCHAR(32),
    uuid VARCHAR(32),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- NEW: Radar frames table for real-time calibration
CREATE TABLE IF NOT EXISTS radar_frames (
    id SERIAL PRIMARY KEY,
    radar_name VARCHAR(32) NOT NULL,
    frame_number INT NOT NULL,
    angle FLOAT NOT NULL,
    range FLOAT NOT NULL,
    timestamp_ns BIGINT NOT NULL,  -- nanoseconds since epoch for precise sync
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed BOOLEAN DEFAULT FALSE
);

-- NEW: Calibration results table
CREATE TABLE IF NOT EXISTS calibration_results (
    id SERIAL PRIMARY KEY,
    ref_radar VARCHAR(32) NOT NULL,
    target_radar VARCHAR(32) NOT NULL,
    position_x FLOAT NOT NULL,
    position_y FLOAT NOT NULL,
    orientation_deg FLOAT NOT NULL,
    residual FLOAT,
    num_frames INT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_radar_frames_name_timestamp ON radar_frames(radar_name, timestamp_ns);
CREATE INDEX IF NOT EXISTS idx_radar_frames_processed ON radar_frames(processed);
CREATE INDEX IF NOT EXISTS idx_radar_frames_created ON radar_frames(created_at);
CREATE INDEX IF NOT EXISTS idx_calibration_timestamp ON calibration_results(timestamp);

-- View for latest calibration results
CREATE OR REPLACE VIEW latest_calibration AS
SELECT DISTINCT ON (ref_radar, target_radar)
    ref_radar,
    target_radar,
    position_x,
    position_y,
    orientation_deg,
    residual,
    num_frames,
    timestamp
FROM calibration_results
ORDER BY ref_radar, target_radar, timestamp DESC;

