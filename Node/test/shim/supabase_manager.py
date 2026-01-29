"""
Supabase database manager for storing radar Range-Doppler Map (RDM) frame data.
Handles connection, initialization, and storage of processed radar frames.
"""

import base64
from datetime import datetime
from typing import Optional

import numpy as np
from supabase import create_client, Client


class SupabaseFrameManager:
    """Manager class for Supabase database operations with Range-Doppler Map frame data."""
    
    # Supabase Configuration
    SUPABASE_URL = "https://ldfxdteygvfvtotxohsl.supabase.co/"
    SUPABASE_KEY = "sb_publishable_9orBiFX93EnU0y2O1HAVTQ_VFk-Zeaa"
    TABLE_NAME = "frames"
    
    def __init__(self):
        """Initialize Supabase client connection."""
        self.client: Optional[Client] = None
        self.is_connected = False
        self._initialize()
    
    def _initialize(self) -> None:
        """Initialize connection to Supabase."""
        try:
            self.client = create_client(self.SUPABASE_URL, self.SUPABASE_KEY)
            self.is_connected = True
            print("✓ Supabase connection initialized")
        except Exception as e:
            self.is_connected = False
            print(f"✗ Supabase connection failed: {e}")
    
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
        Store Range-Doppler Map frame data to Supabase database.
        
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
            return False
        
        try:
            # Encode RDM frame data as base64 to reduce storage size
            # Frame is expected to be 64x512 array of float32 values
            rdm_bytes = rdm_frame.astype(np.float32).tobytes()
            rdm_encoded = base64.b64encode(rdm_bytes).decode('utf-8')
            
            # Prepare data for insertion
            data = {
                "frame_number": frame_number,
                "timestamp": datetime.utcnow().isoformat(),
                "rdm_data": rdm_encoded,
                "rdm_shape": list(rdm_frame.shape),
                "range_value": range_value,
                "angle_value": angle_value,
                "doppler_velocity": doppler_velocity,
                "doppler_bin": doppler_bin,
                "cfar_max_index": cfar_max_index,
                "rdm_min": float(np.min(rdm_frame)),
                "rdm_max": float(np.max(rdm_frame)),
                "rdm_mean": float(np.mean(rdm_frame)),
                "slow_time": rdm_frame.shape[0],
                "fast_time": rdm_frame.shape[1],
            }
            
            # Insert into database
            self.client.table(self.TABLE_NAME).insert(data).execute()
            return True
            
        except Exception as e:
            print(f"Failed to store frame {frame_number} to database: {e}")
            return False
    
    def is_ready(self) -> bool:
        """Check if Supabase connection is ready."""
        return self.is_connected and self.client is not None
