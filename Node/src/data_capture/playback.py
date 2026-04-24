import os
import re
import time
import numpy as np
import logging
from ..radar import config

class PlaybackDAQ:
    def __init__(self, input_dir, loop=True, delay=0.1):
        """
        Mimics DataAcquisition but reads from files.
        
        Args:
            input_dir: Directory containing raw .npy files.
            loop: Whether to loop playback.
            delay: Artificial delay between frames (seconds).
        """
        self.input_dir = input_dir
        self.loop = loop
        self.delay = delay
        self.logger = logging.getLogger(__name__)
        
        self.files = self._get_sorted_files()
        self.current_idx = 0
        
        if not self.files:
            raise ValueError(f"No .npy files found in {input_dir}")
            
        self.logger.info(f"Initialized PlaybackDAQ with {len(self.files)} frames from {input_dir}")

    def _get_sorted_files(self):
        files = [f for f in os.listdir(self.input_dir) if f.endswith(".npy") and "raw" in f]
        # Fallback if "raw" not in name but are .npy
        if not files:
             files = [f for f in os.listdir(self.input_dir) if f.endswith(".npy")]
             
        def extract_number(filename):
            match = re.search(r"(\d+)", filename)
            return int(match.group(0)) if match else filename
        
        return sorted(files, key=extract_number)

    def capture(self):
        """
        Returns the next frame of data.
        Mocking DataAcquisition.capture() signature.
        """
        if self.delay > 0:
            time.sleep(self.delay)
            
        if self.current_idx >= len(self.files):
            if self.loop:
                self.current_idx = 0
                self.logger.info("Playback looping...")
            else:
                # In main.py, capture() blocks or raises error? 
                # DAQ loop catches exceptions.
                # Let's raise an exception to signal end, or just block.
                # For pipeline, blocking is better than crashing? 
                # But blocking might freeze the UI. 
                # Raise StopIteration-like exception that DAQ process handles?
                # DataAcquisition.capture() doesn't usually raise "End of Stream".
                # Let's just return the last frame repeatedly or wait?
                # Best to raise an exception so the caller knows.
                raise EOFError("End of playback")

        filename = self.files[self.current_idx]
        filepath = os.path.join(self.input_dir, filename)
        
        try:
            # frame_data = np.load(filepath)
            # data structure in capture.py was just np.save(raw_filename, frame_data)
            # frame_data is mostly uint16.
            
            data = np.load(filepath)
            self.current_idx += 1
            return data
            
        except Exception as e:
            self.logger.error(f"Error reading frame {filename}: {e}")
            raise e

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
        
    def close(self):
        pass

