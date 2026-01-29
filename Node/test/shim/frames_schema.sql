-- Supabase SQL schema for storing radar Range-Doppler Map (RDM) frame data as JSON
-- Each frame is stored as JSONB containing the 64x512 RDM array and metadata

DROP TABLE IF EXISTS frames CASCADE;

CREATE TABLE frames (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    frame_number INT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    -- Store entire frame data as JSONB for flexibility
    -- Contains: rdm_data (64x512 array), rdm_shape, rdm_min/max/mean, and target metadata
    frame_data JSONB NOT NULL,
    
    -- Quick access fields for indexing
    slow_time INT NOT NULL,    -- Number of doppler bins (chirps), typically 64
    fast_time INT NOT NULL,    -- Number of range bins (samples per chirp), typically 512
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create index on frame_number for faster queries
CREATE INDEX idx_frames_frame_number ON frames(frame_number);

-- Create index on timestamp for temporal queries
CREATE INDEX idx_frames_timestamp ON frames(timestamp);

-- Create JSONB index for querying frame metadata
CREATE INDEX idx_frames_data_gin ON frames USING gin(frame_data);

-- Enable RLS (Row Level Security) if needed
ALTER TABLE frames ENABLE ROW LEVEL SECURITY;
