"""
Supabase database manager for storing radar frames as JSON.
Simpler approach that stores the entire frame data as JSONB for flexibility.
"""

import os
from datetime import datetime
from typing import Optional

import numpy as np
from supabase import create_client, Client


class SupabaseFrameManager:
    """Manager class for Supabase database operations with frame data as JSON."""
    
    # Supabase Configuration
    SUPABASE_URL = os.getenv("SUPABASE_URL", "https://ldfxdteygvfvtotxohsl.supabase.co/")
    SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "sb_secret_zItTcVMLrRNHUfAsnWybbA_BualFz4_")
    TABLE_NAME = "frames"
    
    def __init__(self):
        """Initialize Supabase client connection."""
        self.client: Optional[Client] = None
        self.is_connected = False
        self._initialize()
    
    def _initialize(self) -> None:
        """Initialize connection to Supabase."""
        self._validate_config()
        try:
            self.client = create_client(self.SUPABASE_URL, self.SUPABASE_KEY)
            self._validate_permissions()
            self.is_connected = True
            print("✓ Supabase connection initialized")
        except Exception as e:
            self.is_connected = False
            print(f"✗ Supabase connection failed: {e}")
            raise

    def _validate_config(self) -> None:
        if not self.SUPABASE_URL:
            raise ValueError("SUPABASE_URL is required")
        if not self.SUPABASE_KEY:
            raise ValueError("SUPABASE_SERVICE_KEY is required for server inserts")
        if self.SUPABASE_KEY.startswith("sb_publishable_"):
            raise ValueError(
                "SUPABASE_SERVICE_KEY must be a service role key (sb_secret_...), not a publishable key"
            )

    def _validate_permissions(self) -> None:
        if not self.client:
            raise RuntimeError("Supabase client not initialized")
        # Lightweight permission check to fail fast if RLS blocks inserts
        self.client.table(self.TABLE_NAME).select("id").limit(1).execute()
    
    def store_frame(
        self,
        rdm_frame: np.ndarray,
        frame_number: int,
        range_value: Optional[float] = None,
        angle_value: Optional[float] = None,
        doppler_velocity: Optional[float] = None,
        doppler_bin: Optional[int] = None,
        cfar_max_index: Optional[int] = None,
    ) -> bool:
        """
        Store Range-Doppler Map frame data to Supabase as JSON.
        
        Args:
            rdm_frame: Range-Doppler Map data (64x512 array of float32)
            frame_number: Sequential frame counter
            range_value: Range of detected target (optional)
            angle_value: Azimuth angle of target in degrees (optional)
            doppler_velocity: Doppler velocity in m/s (optional)
            doppler_bin: Raw doppler bin index (optional)
            cfar_max_index: CFAR detection peak index (optional)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_connected or not self.client:
            print("✗ Database not connected")
            return False
        
        try:
            # Convert frame to list for JSON serialization
            rdm_list = rdm_frame.astype(np.float32).tolist()
            
            # Prepare frame metadata
            frame_data = {
                "frame_number": int(frame_number),
                "rdm_data": rdm_list,
                "rdm_shape": [int(rdm_frame.shape[0]), int(rdm_frame.shape[1])],
                "rdm_min": float(np.min(rdm_frame)),
                "rdm_max": float(np.max(rdm_frame)),
                "rdm_mean": float(np.mean(rdm_frame)),
                "range_value": float(range_value) if range_value is not None else None,
                "angle_value": float(angle_value) if angle_value is not None else None,
                "doppler_velocity": float(doppler_velocity) if doppler_velocity is not None else None,
                "doppler_bin": int(doppler_bin) if doppler_bin is not None else None,
                "cfar_max_index": int(cfar_max_index) if cfar_max_index is not None else None,
            }
            
            # Prepare insertion data
            insert_data = {
                "frame_number": int(frame_number),
                "timestamp": datetime.utcnow().isoformat(),
                "frame_data": frame_data,  # Store entire frame as JSONB
                "slow_time": int(rdm_frame.shape[0]),
                "fast_time": int(rdm_frame.shape[1]),
            }
            
            # Debug output
            print(f"Inserting frame {frame_number}...")
            response = self.client.table(self.TABLE_NAME).insert(insert_data).execute()
            print(f"✓ Frame {frame_number} inserted successfully")
            return True
            
        except Exception as e:
            print(f"✗ Failed to store frame {frame_number}: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def is_ready(self) -> bool:
        """Check if Supabase connection is ready."""
        return self.is_connected and self.client is not None
