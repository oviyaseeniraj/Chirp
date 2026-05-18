import os
import time
import numpy as np
import scipy.io as sio
import logging
from ..radar.daq_new import DataAcquisition
from ..radar.processing.rdm import RangeDoppler
from ..radar import config

class CaptureSession:
    def __init__(self, output_dir):
        self.output_dir = output_dir
        self.raw_dir = os.path.join(output_dir, "raw")
        self.rdm_dir = os.path.join(output_dir, "rdm")
        # Ensure directories exist
        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.rdm_dir, exist_ok=True)
        
        self.daq = DataAcquisition()
        self.rdm = RangeDoppler()
        
        # Configure logging
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)

    def capture_frames(self, num_frames, save_raw=True, save_rdm=True, timeout=None):
        """
        Captures a specified number of frames and optionally saves raw and/or RDM data.
        
        Args:
            num_frames: Number of frames to capture
            save_raw: Whether to save raw ADC data
            save_rdm: Whether to save processed RDM cubes
            timeout: Timeout in seconds for each frame. None means wait forever.
        """
        self.logger.info(f"Starting capture of {num_frames} frames...")
        
        i = 0
        while i < num_frames:
            try:
                # 1. Capture Raw Data
                # daq.capture() returns a uint16 numpy array
                try:
                    frame_data = self.daq.capture(timeout=timeout).copy()
                except TimeoutError as te:
                    self.logger.error(f"Timeout capturing frame {i}: {te}")
                    continue
                
                i += 1
                # 2. Save Raw Data
                if save_raw:
                    raw_filename = os.path.join(self.raw_dir, f"raw_frame_{i:04d}.npy")
                    np.save(raw_filename, frame_data)
                    self.logger.debug(f"Saved raw frame {i} to {raw_filename}")

                # 3. Process and Save RDM
                if save_rdm:
                    # RDM processing expects input buffer to be set
                    self.rdm.set_buffer(frame_data)
                    # We don't strictly need the return value of process() (loss map) for saving the complex cube
                    # But we assume process() populates the internal structures
                    self.rdm.process() 
                    
                    # Get the complex RDM cube
                    # Note: get_clean_rdm() usually returns (SLOW_TIME, RX, TX, FAST_TIME)
                    cube = self.rdm.get_clean_rdm()
                    
                    rdm_filename = os.path.join(self.rdm_dir, f"rdm_frame_{i:04d}.npy")
                    np.save(rdm_filename, cube)
                    self.logger.debug(f"Saved RDM frame {i} to {rdm_filename}")

                if i % 10 == 0:
                    self.logger.info(f"Captured {i}/{num_frames} frames")

            except Exception as e:
                self.logger.error(f"Error capturing frame {i}: {e}")
                # Optional: break or continue?
                # continue

        self.logger.info("Capture complete.")

    @staticmethod
    def convert_npy_to_mat(input_dir, output_file, data_type="rdm"):
        """
        Converts a directory of .npy files into a single .mat file.
        
        Args:
            input_dir: Directory containing .npy files
            output_file: Output .mat filename
            data_type: "rdm" or "raw". 
                       "rdm" expects shape (SLOW, RX, TX, FAST) or similar.
                       "raw" expects linear uint16 array? 
                       Actually, let's stick to the TFG logic for RDM.
                       For raw, we might want to just stack them.
        """
        import re
        
        # Find all .npy files
        npy_files = [f for f in os.listdir(input_dir) if f.endswith(".npy")]
        
        # Sort numerically
        def extract_number(filename):
            match = re.search(r"(\d+)", filename)
            return int(match.group(0)) if match else filename

        npy_files.sort(key=extract_number)

        if not npy_files:
            print(f"No .npy files found in {input_dir}")
            return

        print(f"Processing {len(npy_files)} files from {input_dir}...")
        all_frames = []

        # Constants from config (for reshaping logic if needed)
        # Assuming RDM cubes are already shaped, but TFG had reshaping logic.
        # IF we saved using `get_clean_rdm()`, it's already (SLOW, RX, TX, FAST)
        # TFG.py logic was:
        #   cube = data.reshape((TX, RX, SLOW_TIME, FAST_TIME))
        #   transposed_cube = cube.transpose(2, 1, 0, 3) -> (SLOW, RX, TX, FAST)
        #
        # If our `rdm.get_clean_rdm()` ALREADY returns (SLOW, RX, TX, FAST), 
        # then we just need to stack them.

        if data_type == "raw":
            from ..radar.processing.rdm import RangeDoppler
            rdm_processor = RangeDoppler()

        for filename in npy_files:
            file_path = os.path.join(input_dir, filename)
            data = np.load(file_path)
            
            if data_type == "raw":
                # Use RangeDoppler to correctly reshape the interleaved ADC data
                rdm_processor.set_buffer(data)
                cube = rdm_processor.shape_cube_vect()  # Returns (TX * RX, SLOW, FAST)
                
                # Reshape and transpose to match (SLOW, RX, TX, FAST)
                from ..radar import config
                cube = cube.reshape((config.TX, config.RX, config.SLOW_TIME, config.FAST_TIME))
                data = cube.transpose(2, 1, 0, 3)
            
            all_frames.append(data)

        if not all_frames:
            print("No valid frames processed.")
            return

        # Stack along new 'frames' dimension -> (frames, SLOW, RX, TX, FAST)
        final_data = np.stack(all_frames, axis=0)
        
        # TFG.py wanted: [frames][chirps per frame = 64][RX = 4][TX = 3][ADC samples = 512]
        # If `get_clean_rdm` is (SLOW, RX, TX, FAST), then we are good.
        
        save_dict = {f"{data_type}_cube": final_data}
        sio.savemat(output_file, save_dict)
        print(f"Successfully saved {final_data.shape} data to {output_file}")

