#!/usr/bin/env python3
import argparse
import sys
import os

# Add parent directory to path to allow importing src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data_capture.capture import CaptureSession

def main():
    parser = argparse.ArgumentParser(description="Data Capture Utility for Chirp Radar")
    
    # Mode selection
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--capture", action="store_true", help="Capture frames from radar")
    group.add_argument("--convert", action="store_true", help="Convert captured .npy files to .mat")
    
    # Capture arguments
    parser.add_argument("--frames", type=int, default=100, help="Number of frames to capture")
    parser.add_argument("--output", type=str, default="data_capture", help="Output directory for captured data")
    parser.add_argument("--timeout", type=float, default=5, help="Timeout in seconds for each frame (default: 5s)")
    parser.add_argument("--no-raw", action="store_true", help="Do not save raw data")
    parser.add_argument("--no-rdm", action="store_true", help="Do not save processed RDM data")
    
    # Convert arguments
    parser.add_argument("--input-dir", type=str, help="Input directory for conversion")
    parser.add_argument("--output-file", type=str, help="Output .mat filename")
    parser.add_argument("--type", choices=["rdm", "raw"], default="rdm", help="Type of data to convert (default: rdm)")

    args = parser.parse_args()
    
    if args.capture:
        output_dir = os.path.abspath(args.output)
        session = CaptureSession(output_dir)
        
        save_raw = not args.no_raw
        save_rdm = not args.no_rdm
        
        print(f"Starting capture: {args.frames} frames -> {output_dir}")
        print(f"Saving Raw: {save_raw}, Saving RDM: {save_rdm}, Timeout: {args.timeout}s")
        
        session.capture_frames(args.frames, save_raw=save_raw, save_rdm=save_rdm, timeout=args.timeout)
        
    elif args.convert:
        if not args.input_dir or not args.output_file:
            print("Error: --input-dir and --output-file are required for conversion.")
            return
            
        input_path = os.path.abspath(args.input_dir)
        output_path = os.path.abspath(args.output_file)
        
        CaptureSession.convert_npy_to_mat(input_path, output_path, args.type)

if __name__ == "__main__":
    main()
