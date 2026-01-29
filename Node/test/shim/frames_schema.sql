-- Supabase SQL schema for storing radar Range-Doppler Map (RDM) frame data
-- Each frame is a 64x512 2D array of float32 values representing the processed radar data
-- The frame has already been processed through FFT, magnitude computation, and averaging

CREATE TABLE frames (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    frame_number INT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    -- Range-Doppler Map Data (64 Doppler bins x 512 Range bins)
    -- Stored as base64 encoded float32 array
    rdm_data TEXT NOT NULL,
    rdm_shape INT[] NOT NULL,  -- Should be [64, 512]
    
    -- Detected target metadata
    range_value FLOAT,         -- Range of detected target (in range units)
    angle_value FLOAT,         -- Azimuth angle of detected target (in degrees)
    doppler_velocity FLOAT,    -- Doppler velocity of target (in m/s)
    doppler_bin INT,           -- Raw doppler bin index
    cfar_max_index INT,        -- CFAR detection peak index
    
    -- Statistics for the frame
    rdm_min FLOAT,
    rdm_max FLOAT,
    rdm_mean FLOAT,
    
    -- Configuration/Context
    slow_time INT NOT NULL,    -- Number of doppler bins (chirps), typically 64
    fast_time INT NOT NULL,    -- Number of range bins (samples per chirp), typically 512
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create index on frame_number for faster queries
CREATE INDEX idx_frames_frame_number ON frames(frame_number);

-- Create index on timestamp for temporal queries
CREATE INDEX idx_frames_timestamp ON frames(timestamp);

-- Create index on detected targets (non-null detections)
CREATE INDEX idx_frames_detections ON frames(cfar_max_index) WHERE cfar_max_index IS NOT NULL;

-- Enable RLS (Row Level Security) if needed
ALTER TABLE frames ENABLE ROW LEVEL SECURITY;
