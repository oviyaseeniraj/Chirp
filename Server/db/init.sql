-- ============================================================
-- Chirp  –  Database schema
-- ============================================================

-- 1.  Calibration frames  (chirp/v1/group/+/calibration/frame/+)
-- -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS calibration_frames (
    id              BIGSERIAL PRIMARY KEY,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- MQTT‑derived routing
    group_id        TEXT        NOT NULL,
    node_id         TEXT        NOT NULL,
    command_id      TEXT        NOT NULL,

    -- payload fields
    schema_version  INT         NOT NULL DEFAULT 1,
    timestamp_ms    BIGINT      NOT NULL,
    frame_num       INT         NOT NULL,

    -- radar data
    detections      JSONB       NOT NULL DEFAULT '[]'::jsonb,
      --  [[range_m, doppler_mps, angle_rad], …]
    tracks          JSONB       NOT NULL DEFAULT '[]'::jsonb
      --  [{"track_id":int, "x":float, "y":float}, …]
);

CREATE INDEX IF NOT EXISTS idx_calframe_group_node
    ON calibration_frames (group_id, node_id);
CREATE INDEX IF NOT EXISTS idx_calframe_command
    ON calibration_frames (command_id);
CREATE INDEX IF NOT EXISTS idx_calframe_received
    ON calibration_frames (received_at DESC);


-- 2.  Calibration‑done signals  (chirp/v1/group/+/calibration/done/+)
-- -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS calibration_done (
    id              BIGSERIAL PRIMARY KEY,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    group_id        TEXT        NOT NULL,
    node_id         TEXT        NOT NULL,
    command_id      TEXT        NOT NULL,

    schema_version  INT         NOT NULL DEFAULT 1,
    timestamp_ms    BIGINT      NOT NULL,
    total_frames    INT         NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_caldone_command
    ON calibration_done (command_id);


-- 3.  Live per‑frame clusters + tracks  (chirp/v1/group/+/frames/+)
-- -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS live_frames (
    id              BIGSERIAL PRIMARY KEY,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    group_id        TEXT        NOT NULL,
    node_id         TEXT        NOT NULL,

    schema_version  INT         NOT NULL DEFAULT 1,
    timestamp_ms    BIGINT      NOT NULL,

    clusters        JSONB       NOT NULL DEFAULT '[]'::jsonb,
      --  [{"range_m", "angle_rad", "angle_deg", "doppler_mps", "mass"}, …]
    tracks          JSONB       NOT NULL DEFAULT '[]'::jsonb
      --  [{"track_id", "x", "y", "vx", "vy"}, …]
);

CREATE INDEX IF NOT EXISTS idx_liveframe_group_node
    ON live_frames (group_id, node_id);
CREATE INDEX IF NOT EXISTS idx_liveframe_received
    ON live_frames (received_at DESC);


-- 4.  Capture commands  (chirp/v1/group/+/capture/start)  – stored by the bridge
-- -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS capture_commands (
    id              BIGSERIAL PRIMARY KEY,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    group_id        TEXT        NOT NULL,
    command_id      TEXT        NOT NULL,

    calibration     BOOLEAN     NOT NULL DEFAULT false,
    calibration_frames INT     NOT NULL DEFAULT 150,
    start_epoch_ms  BIGINT,
    target_node_ids JSONB       DEFAULT '[]'::jsonb,

    raw_payload     JSONB       NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_capcmd_group
    ON capture_commands (group_id);
CREATE INDEX IF NOT EXISTS idx_capcmd_command
    ON capture_commands (command_id);


CREATE TABLE IF NOT EXISTS node_status (
    node_id VARCHAR(50) PRIMARY KEY,
    ip_address VARCHAR(45) NOT NULL,
    last_seen_ms BIGINT
);
