#!/usr/bin/env python3
"""
Collect Chrony offset measurements over time.
Run this on the SLAVE Jetson(s).
"""

import subprocess
import time
import json
from datetime import datetime
import os
import socket

def parse_chrony_tracking():
    """Parse chronyc tracking output and extract key metrics."""
    try:
        result = subprocess.run(['chronyc', 'tracking'], 
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, check=True)
        
        data = {}
        for line in result.stdout.split('\n'):
            line = line.strip()
            if not line:
                continue
                
            try:
                if 'System time' in line:
                    # Parse: "System time     : 0.000123456 seconds slow/fast of NTP time"
                    parts = line.split(':')
                    if len(parts) >= 2:
                        value_part = parts[1].strip().split()[0]
                        offset = float(value_part)
                        if 'slow' in line:
                            offset = -offset
                        data['offset_s'] = offset
                        data['offset_ms'] = offset * 1000
                        data['offset_us'] = offset * 1e6
                
                elif 'Last offset' in line:
                    parts = line.split(':')
                    if len(parts) >= 2:
                        value_part = parts[1].strip().split()[0]
                        last_offset = float(value_part)
                        data['last_offset_ms'] = last_offset * 1000
                
                elif 'RMS offset' in line:
                    parts = line.split(':')
                    if len(parts) >= 2:
                        value_part = parts[1].strip().split()[0]
                        data['rms_offset_ms'] = float(value_part) * 1000
                
                elif 'Frequency' in line and 'Residual' not in line:
                    parts = line.split(':')
                    if len(parts) >= 2:
                        value_part = parts[1].strip().split()[0]
                        data['frequency_ppm'] = float(value_part)
                
                elif 'Residual freq' in line:
                    parts = line.split(':')
                    if len(parts) >= 2:
                        value_part = parts[1].strip().split()[0]
                        data['residual_freq_ppm'] = float(value_part)
                
                elif 'Skew' in line:
                    parts = line.split(':')
                    if len(parts) >= 2:
                        value_part = parts[1].strip().split()[0]
                        data['skew_ppm'] = float(value_part)
                
                elif 'Root delay' in line:
                    parts = line.split(':')
                    if len(parts) >= 2:
                        value_part = parts[1].strip().split()[0]
                        data['root_delay_ms'] = float(value_part) * 1000
                
                elif 'Update interval' in line:
                    parts = line.split(':')
                    if len(parts) >= 2:
                        value_part = parts[1].strip().split()[0]
                        data['update_interval_s'] = float(value_part)
                
                elif 'Reference ID' in line:
                    parts = line.split(':')
                    if len(parts) >= 2:
                        data['reference_id'] = parts[1].strip().split()[0]
            except (ValueError, IndexError) as e:
                # Skip lines that don't parse correctly
                continue
        
        # Must have at least offset data
        if 'offset_us' not in data:
            return None
            
        return data
    
    except Exception as e:
        print(f"Error parsing chronyc: {e}")
        return None

def collect_samples(num_samples, interval_s, output_file, node_id=None):
    """Collect offset samples and save to JSON."""
    
    # Auto-detect node hostname if not specified
    if node_id is None:
        node_id = socket.gethostname()
    
    print(f"Node: {node_id}")
    print(f"Collecting {num_samples} samples at {interval_s}s intervals...")
    print(f"Output: {output_file}")
    print(f"Estimated time: {num_samples * interval_s / 60:.1f} minutes")
    print()
    
    samples = []
    
    for i in range(num_samples):
        data = parse_chrony_tracking()
        
        if data:
            data['sample_num'] = i
            data['timestamp'] = datetime.now().isoformat()
            data['unix_time'] = time.time()
            data['node_id'] = node_id
            samples.append(data)
            
            if (i + 1) % 10 == 0 or i == 0:
                print(f"[{i+1}/{num_samples}] Offset: {data['offset_us']:+.1f} μs, "
                      f"Freq: {data['frequency_ppm']:+.3f} ppm")
        else:
            print(f"[{i+1}/{num_samples}] Failed to collect sample")
        
        if i < num_samples - 1:
            time.sleep(interval_s)
    
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Build path to data/jsons relative to script location
    jsons_dir = os.path.join(script_dir, 'data', 'jsons')
    
    # Extract just the filename and put it in the jsons directory
    base_name = os.path.basename(output_file)
    full_output_path = os.path.join(jsons_dir, base_name)

    # Add metadata
    output_data = {
        'metadata': {
            'node_id': node_id,
            'num_samples': len(samples),
            'interval_s': interval_s,
            'start_time': samples[0]['timestamp'] if samples else None,
            'end_time': samples[-1]['timestamp'] if samples else None,
        },
        'samples': samples
    }
    
    # Save to file
    with open(full_output_path, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print()
    print(f"✓ Collected {len(samples)} samples from {node_id}")
    print(f"✓ Saved to {full_output_path}")
    print()
    print("Run analysis: python3 analyze_offsets.py " + full_output_path)

if __name__ == '__main__':
    import sys
    
    # Default parameters
    num_samples = 100
    interval_s = 1.0
    node_id = None  # Auto-detect if not provided
    output_file = f"offset_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    # Parse arguments
    if len(sys.argv) > 1:
        num_samples = int(sys.argv[1])
    if len(sys.argv) > 2:
        interval_s = float(sys.argv[2])
    if len(sys.argv) > 3:
        node_id = sys.argv[3]
    if len(sys.argv) > 4:
        output_file = sys.argv[4]
    
    print("="*60)
    print("CHRONY OFFSET COLLECTION")
    print("="*60)
    print()
    print("Usage: python3 collect_offsets.py [num_samples] [interval_s] [node_id] [output_file]")
    print("  node_id: Optional identifier for this slave (e.g., 'slave1', 'slave2')")
    print("           If not provided, hostname will be used")
    print()
    
    collect_samples(num_samples, interval_s, output_file, node_id)

