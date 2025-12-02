#!/usr/bin/env python3
"""
Quick worst-case offset analysis across all nodes.
Usage: python3 worst_case_offset.py <file1.json> <file2.json> [file3.json ...]
"""

import json
import sys
import numpy as np
from itertools import combinations

def load_offset_data(filename):
    """Load offset data from JSON file."""
    with open(filename, 'r') as f:
        data = json.load(f)
    
    # Handle new format with metadata
    if isinstance(data, dict) and 'samples' in data:
        samples = data['samples']
        node_id = data.get('metadata', {}).get('node_id', filename)
    else:
        samples = data
        node_id = filename
    
    offsets_us = np.array([s['offset_us'] for s in samples])
    return node_id, offsets_us

def worst_case_analysis(filenames):
    """Find worst-case offset between any two devices."""
    
    if len(filenames) == 0:
        print("Error: No data files provided")
        sys.exit(1)
    
    # Load all node data
    nodes = []
    for filename in filenames:
        try:
            node_id, offsets = load_offset_data(filename)
            nodes.append({
                'id': node_id,
                'offsets': offsets,
                'min': np.min(offsets),
                'max': np.max(offsets),
                'mean': np.mean(offsets),
                'filename': filename
            })
        except Exception as e:
            print(f"Warning: Could not load {filename}: {e}")
            continue
    
    if len(nodes) == 0:
        print("Error: No valid data files loaded")
        sys.exit(1)
    
    # Add master node (offset = 0)
    master = {
        'id': 'master',
        'offsets': np.array([0]),
        'min': 0,
        'max': 0,
        'mean': 0,
        'filename': 'N/A (reference)'
    }
    nodes.append(master)
    
    # Find worst-case offset between any two devices
    # This is the maximum absolute difference between extreme offsets
    worst_case = 0
    worst_pair = None
    worst_description = ""
    
    for node1, node2 in combinations(nodes, 2):
        # Maximum possible offset difference occurs between extremes
        # Case 1: node1_max - node2_min (both positive or node1 ahead)
        diff1 = node1['max'] - node2['min']
        # Case 2: node2_max - node1_min (node2 ahead)
        diff2 = node2['max'] - node1['min']
        
        # Take the maximum absolute difference
        max_diff = max(abs(diff1), abs(diff2))
        
        if max_diff > worst_case:
            worst_case = max_diff
            if abs(diff1) > abs(diff2):
                worst_pair = (node1['id'], node2['id'])
                worst_description = f"{node1['id']} ahead of {node2['id']}"
                extreme_vals = (node1['max'], node2['min'])
            else:
                worst_pair = (node2['id'], node1['id'])
                worst_description = f"{node2['id']} ahead of {node1['id']}"
                extreme_vals = (node2['max'], node1['min'])
    
    # Print results
    print("=" * 70)
    print("WORST-CASE INTER-DEVICE OFFSET ANALYSIS")
    print("=" * 70)
    print()
    
    # Individual node statistics
    print("Individual Node Offsets from Master:")
    print("-" * 70)
    for node in sorted([n for n in nodes if n['id'] != 'master'], 
                       key=lambda x: abs(x['mean']), reverse=True):
        print(f"  {node['id']:<20} "
              f"Range: [{node['min']:+8.1f}, {node['max']:+8.1f}] μs  "
              f"Mean: {node['mean']:+8.1f} μs")
    print()
    
    # Worst-case comparison
    print("=" * 70)
    print("WORST-CASE OFFSET BETWEEN ANY TWO DEVICES")
    print("=" * 70)
    print()
    print(f"Maximum possible time difference: {worst_case:.1f} μs ({worst_case/1000:.3f} ms)")
    print(f"Occurs between: {worst_pair[0]} and {worst_pair[1]}")
    print(f"Scenario: {worst_description}")
    print(f"  {worst_pair[0]} extreme: {extreme_vals[0]:+.1f} μs")
    print(f"  {worst_pair[1]} extreme: {extreme_vals[1]:+.1f} μs")
    print(f"  Difference: {worst_case:+.1f} μs")
    print()
    
    # Assessment
    print("-" * 70)
    if worst_case < 100:
        status = "EXCELLENT"
        symbol = "✓"
    elif worst_case < 500:
        status = "GOOD"
        symbol = "✓"
    elif worst_case < 1000:
        status = "ACCEPTABLE"
        symbol = "~"
    else:
        status = "POOR - RECALIBRATION RECOMMENDED"
        symbol = "✗"
    
    print(f"{symbol} System Status: {status}")
    print(f"  Worst-case inter-device offset: {worst_case:.1f} μs ({worst_case/1000:.3f} ms)")
    print("-" * 70)
    print()

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 worst_case_offset.py <file1.json> <file2.json> [file3.json ...]")
        print()
        print("Analyzes worst-case time offset between any two devices in the network.")
        print("Considers the master as having 0 offset and finds the maximum possible")
        print("time difference between any pair of nodes (slave-slave or slave-master).")
        print()
        print("Example:")
        print("  python3 worst_case_offset.py data/jsons/slave1_*.json data/jsons/slave2_*.json")
        sys.exit(1)
    
    filenames = sys.argv[1:]
    worst_case_analysis(filenames)

