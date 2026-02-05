# test frame gen, creates a frame and then saves it to a files
#

import argparse
import os
import re
from hmac import trans_36

import numpy as np
import scipy.io as sio
from new_pipe.daqv3 import DataAcquisition
from new_pipe.rdm import RangeDoppler


def main():
    daq = DataAcquisition()
    rdm = RangeDoppler()
    num_frames = 200
    # frame_data = daq.process_v6().copy()
    # rdm.set_buffer(np.array(frame_data, dtype=np.float32))
    # cube = rdm.shape_cube_vect()
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)

    for i in range(num_frames):
        # Get frame data
        frame_data = daq.process_v6().copy()
        rdm.set_buffer(np.array(frame_data, dtype=np.float32))
        cube = rdm.shape_cube_vect()
        print(f"Cube shape: {cube.shape}, frame: {i}")
        # Save cube data as binary numpy file
        filename = os.path.join(data_dir, f"cube_frame_{i:04d}.npy")
        np.save(filename, cube)
        print(f"Saved frame {i} to {filename}")


def convert_npy_to_mat(input_dir, output_file):
    """
    Converts numpy radar cube files into a single .mat file.

    Format of bins: [TX = 3][RX = 4][Chirp Loop = 64][Sample = 512] complex values
    Target format: [frames][chirps per frame = 64][RX = 4][TX = 3][ADC samples = 512] complex values
    """

    # Radar parameters (from main.h)
    TX = 3
    RX = 4
    SLOW_TIME = 64
    FAST_TIME = 512

    # Find all .npy files in the directory
    npy_files = [f for f in os.listdir(input_dir) if f.endswith(".npy")]

    # Sort files numerically
    def extract_number(filename):
        match = re.search(r"(\d+)", filename)
        return int(match.group(0)) if match else filename

    npy_files.sort(key=extract_number)

    if not npy_files:
        print(f"No .npy files found in {input_dir}")
        return

    print(f"Processing {len(npy_files)} files from {input_dir}...")

    all_frames = []

    for filename in npy_files:
        file_path = os.path.join(input_dir, filename)

        # Load the numpy file (already complex values)
        data = np.load(file_path)

        expected_size = TX * RX * SLOW_TIME * FAST_TIME
        if data.size != expected_size:
            print(
                f"Warning: {filename} has unexpected size {data.size} (expected {expected_size}). Skipping."
            )
            continue

        # Reshape to [TX, RX, SLOW_TIME, FAST_TIME] - already complex
        # print(data.shape)
        cube = data.reshape((TX, RX, SLOW_TIME, FAST_TIME))
        # Current shape: (TX=3, RX=4, SLOW_TIME=64, FAST_TIME=512)
        # Target shape: (SLOW_TIME=64, RX=4, TX=3, FAST_TIME=512)
        # Transpose indices:
        # Original: 0=TX, 1=RX, 2=SLOW, 3=FAST
        # Target: 2=SLOW, 1=RX, 0=TX, 3=FAST -> axes=(2, 1, 0, 3)
        transposed_cube = cube.transpose(2, 1, 0, 3)

        all_frames.append(transposed_cube)
        print(f"Processed {filename}")

    if not all_frames:
        print("No valid frames processed.")
        return

    # Stack along a new 'frames' dimension
    # Shape: (frames, 64, 4, 3, 512)
    final_data = np.stack(all_frames, axis=0)

    # Save to .mat file
    sio.savemat(output_file, {"radar_cube": final_data})
    print(f"Successfully saved {final_data.shape} data to {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Test frame generator - capture and save radar data."
    )
    parser.add_argument(
        "--convert", action="store_true", help="Convert .npy files to .mat format"
    )
    parser.add_argument(
        "--input-dir", help="Input directory containing .npy files (for conversion)"
    )
    parser.add_argument("--output-file", help="Output .mat filename (for conversion)")

    args = parser.parse_args()

    if args.convert:
        if not args.input_dir or not args.output_file:
            print(
                "Error: --input-dir and --output-file are required when using --convert"
            )
            parser.print_help()
        else:
            input_path = os.path.abspath(args.input_dir)
            output_path = os.path.abspath(args.output_file)
            convert_npy_to_mat(input_path, output_path)
    else:
        main()
