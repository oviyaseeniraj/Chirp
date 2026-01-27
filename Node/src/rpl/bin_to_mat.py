import numpy as np
import scipy.io as sio
import os
import argparse
import re

def process_radar_data(input_dir, output_file):
    """
    Converts binary radar cube files into a single .mat file.
    
    Format of bins: [TX = 3][RX = 4][Chirp Loop = 64][Sample = 512][IQ = 2] floats
    Target format: [frames][chirps per frame = 64][RX = 4][TX = 3][ADC samples = 512] complex values
    """
    
    # Radar parameters (from main.h)
    TX = 3
    RX = 4
    SLOW_TIME = 64
    FAST_TIME = 512
    IQ = 2
    
    # Find all .bin files in the directory
    bin_files = [f for f in os.listdir(input_dir) if f.endswith('.bin')]
    
    # Sort files numerically if possible (assuming radar_cube_N.bin format)
    def extract_number(filename):
        match = re.search(r'(\d+)', filename)
        return int(match.group(0)) if match else filename

    bin_files.sort(key=extract_number)
    
    if not bin_files:
        print(f"No .bin files found in {input_dir}")
        return

    print(f"Processing {len(bin_files)} files from {input_dir}...")
    
    all_frames = []
    
    for filename in bin_files:
        file_path = os.path.join(input_dir, filename)
        
        # Read the binary file as float32
        # The user mentioned the bins are generated in RangeDoppler.cpp
        # RangeDoppler.cpp saves 'adc_data_reshaped' which is SIZE_W_IQ floats
        data = np.fromfile(file_path, dtype=np.float32)
        
        expected_size = TX * RX * SLOW_TIME * FAST_TIME * IQ
        if data.size != expected_size:
            print(f"Warning: {filename} has unexpected size {data.size} (expected {expected_size}). Skipping.")
            continue
            
        # Reshape to [TX, RX, SLOW_TIME, FAST_TIME, IQ]
        # RangeDoppler.cpp: tx = indices[0] * RX * SLOW_TIME * FAST_TIME * IQ; etc.
        # This corresponds to (TX, RX, SLOW_TIME, FAST_TIME, IQ)
        cube = data.reshape((TX, RX, SLOW_TIME, FAST_TIME, IQ))
        
        # Convert IQ to complex values
        # IQ is at the last dimension (0=Real, 1=Imaginary)
        complex_cube = cube[..., 0] + 1j * cube[..., 1]
        
        # Current shape: (TX=3, RX=4, SLOW_TIME=64, FAST_TIME=512)
        # Target shape: (SLOW_TIME=64, RX=4, TX=3, FAST_TIME=512)
        # Transpose indices:
        # Original: 0=TX, 1=RX, 2=SLOW, 3=FAST
        # Target: 2=SLOW, 1=RX, 0=TX, 3=FAST -> axes=(2, 1, 0, 3)
        transposed_cube = complex_cube.transpose(2, 1, 0, 3)
        
        all_frames.append(transposed_cube)
        print(f"Processed {filename}")

    if not all_frames:
        print("No valid frames processed.")
        return
        
    # Stack along a new 'frames' dimension
    # Shape: (frames, 64, 4, 3, 512)
    final_data = np.stack(all_frames, axis=0)
    
    # Save to .mat file
    # MATLAB key 'radar_data'
    sio.savemat(output_file, {'radar_cube': final_data})
    print(f"Successfully saved {final_data.shape} data to {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Convert radar binary cubes to .mat file.')
    parser.add_argument('input_dir', help='Directory containing .bin files')
    parser.add_argument('output_file', help='Output .mat filename')
    
    args = parser.parse_args()
    
    input_path = os.path.abspath(args.input_dir)
    output_path = os.path.abspath(args.output_file)
    
    process_radar_data(input_path, output_path)
