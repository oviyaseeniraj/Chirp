#!/usr/bin/env python3
"""
Quick worst-case offset analysis across all nodes with visualization.
Usage: python3 worst_case_offset.py <file1.json> <file2.json> [file3.json ...]
"""

import json
import sys
import os
import numpy as np
from itertools import combinations
import matplotlib.pyplot as plt
from datetime import datetime
from scipy import stats

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


def create_worst_case_plots(nodes, worst_case, worst_pair, output_dir="data/plots"):
    """Create visualization plots for worst-case offset analysis."""
    
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Filter out master for plotting (it has only 1 sample = 0)
    slave_nodes = [n for n in nodes if n['id'] != 'master']
    
    # Color scheme
    colors = plt.cm.tab10(np.linspace(0, 1, len(slave_nodes) + 1))
    node_colors = {n['id']: colors[i] for i, n in enumerate(slave_nodes)}
    node_colors['master'] = 'black'
    
    # Create figure with subplots
    fig = plt.figure(figsize=(14, 10))
    
    # =========================================================================
    # Plot 1: Time series of all node offsets
    # =========================================================================
    ax1 = fig.add_subplot(2, 2, 1)
    
    for node in slave_nodes:
        samples = np.arange(len(node['offsets']))
        ax1.plot(samples, node['offsets'], label=node['id'], 
                color=node_colors[node['id']], alpha=0.8, linewidth=1)
    
    ax1.axhline(y=0, color='black', linestyle='--', linewidth=1.5, label='master (ref)')
    ax1.set_xlabel('Sample Index')
    ax1.set_ylabel('Offset from Master (μs)')
    ax1.set_title('Time Series: Node Offsets from Master')
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    
    # =========================================================================
    # Plot 2: Histogram/Distribution of offsets
    # =========================================================================
    ax2 = fig.add_subplot(2, 2, 2)
    
    for node in slave_nodes:
        ax2.hist(node['offsets'], bins=50, alpha=0.6, label=node['id'],
                color=node_colors[node['id']], edgecolor='white', linewidth=0.5)
    
    ax2.axvline(x=0, color='black', linestyle='--', linewidth=2, label='master (ref)')
    ax2.set_xlabel('Offset from Master (μs)')
    ax2.set_ylabel('Frequency')
    ax2.set_title('Distribution of Node Offsets')
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)
    
    # =========================================================================
    # Plot 3: Box plot comparison
    # =========================================================================
    ax3 = fig.add_subplot(2, 2, 3)
    
    box_data = [node['offsets'] for node in slave_nodes]
    box_labels = [node['id'] for node in slave_nodes]
    
    bp = ax3.boxplot(box_data, tick_labels=box_labels, patch_artist=True)
    
    for patch, node in zip(bp['boxes'], slave_nodes):
        patch.set_facecolor(node_colors[node['id']])
        patch.set_alpha(0.7)
    
    ax3.axhline(y=0, color='black', linestyle='--', linewidth=1.5, label='master (ref)')
    ax3.set_ylabel('Offset from Master (μs)')
    ax3.set_title('Offset Distribution by Node')
    ax3.grid(True, alpha=0.3, axis='y')
    
    # =========================================================================
    # Plot 4: Worst-case visualization
    # =========================================================================
    ax4 = fig.add_subplot(2, 2, 4)
    
    # Create bar chart showing min/max ranges for each node
    all_nodes = slave_nodes + [{'id': 'master', 'min': 0, 'max': 0, 'mean': 0}]
    node_names = [n['id'] for n in all_nodes]
    mins = [n['min'] for n in all_nodes]
    maxs = [n['max'] for n in all_nodes]
    means = [n['mean'] for n in all_nodes]
    
    x = np.arange(len(node_names))
    width = 0.6
    
    # Plot range bars
    for i, node in enumerate(all_nodes):
        color = node_colors.get(node['id'], 'gray')
        ax4.bar(i, node['max'] - node['min'], bottom=node['min'], 
               width=width, color=color, alpha=0.6, edgecolor='black')
        ax4.plot(i, node['mean'], 'ko', markersize=8)
    
    # Highlight worst-case pair
    if worst_pair:
        idx1 = node_names.index(worst_pair[0]) if worst_pair[0] in node_names else -1
        idx2 = node_names.index(worst_pair[1]) if worst_pair[1] in node_names else -1
        if idx1 >= 0 and idx2 >= 0:
            # Draw arrow between worst pair
            node1 = all_nodes[idx1]
            node2 = all_nodes[idx2]
            y1 = node1['max'] if node1['max'] > node2['min'] else node1['min']
            y2 = node2['min'] if node1['max'] > node2['min'] else node2['max']
            
            ax4.annotate('', xy=(idx2, y2), xytext=(idx1, y1),
                        arrowprops=dict(arrowstyle='<->', color='red', lw=2))
            
            mid_x = (idx1 + idx2) / 2
            mid_y = (y1 + y2) / 2
            ax4.text(mid_x, mid_y + 20, f'Worst: {worst_case:.1f}μs', 
                    ha='center', fontsize=10, color='red', fontweight='bold')
    
    ax4.axhline(y=0, color='black', linestyle='--', linewidth=1)
    ax4.set_xticks(x)
    ax4.set_xticklabels(node_names)
    ax4.set_ylabel('Offset (μs)')
    ax4.set_title(f'Worst-Case Analysis: {worst_case:.1f}μs between {worst_pair[0]} & {worst_pair[1]}')
    ax4.grid(True, alpha=0.3, axis='y')
    
    # Add legend for markers
    ax4.plot([], [], 'ko', label='Mean offset')
    ax4.legend(loc='upper right')
    
    # =========================================================================
    # Finalize and save
    # =========================================================================
    plt.tight_layout()
    
    # Save plot
    plot_filename = f"{output_dir}/worst_case_{timestamp}.png"
    plt.savefig(plot_filename, dpi=150, bbox_inches='tight')
    print(f"\nPlot saved: {plot_filename}")
    
    # Also save a summary plot filename without timestamp for easy access
    latest_filename = f"{output_dir}/worst_case_latest.png"
    plt.savefig(latest_filename, dpi=150, bbox_inches='tight')
    print(f"[PLOT] Latest plot: {latest_filename}")
    
    plt.show()
    
    return plot_filename


def create_pdf_plot(nodes, output_dir="data/plots", test_name="test"):
    """Create proper PDF (Probability Density Function) plot with standard deviation."""
    
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Filter out master for plotting
    slave_nodes = [n for n in nodes if n['id'] != 'master']
    
    if not slave_nodes:
        print("No slave nodes to plot")
        return None
    
    # Color scheme
    colors = ['#2E86AB', '#A23B72', '#F18F01', '#C73E1D', '#3B1F2B']
    
    # Create figure
    fig, axes = plt.subplots(1, len(slave_nodes), figsize=(6*len(slave_nodes), 5))
    if len(slave_nodes) == 1:
        axes = [axes]
    
    fig.suptitle(f'Probability Density Functions - {test_name}', fontsize=14, fontweight='bold')
    
    for idx, (node, ax, color) in enumerate(zip(slave_nodes, axes, colors)):
        offsets = node['offsets']
        
        # Calculate statistics
        mean = np.mean(offsets)
        std = np.std(offsets)
        min_val = np.min(offsets)
        max_val = np.max(offsets)
        
        # Create x range for PDF
        x_range = np.linspace(mean - 4*std, mean + 4*std, 500)
        
        # If std is very small, use a wider range based on data
        if std < 1:
            x_range = np.linspace(min_val - 5, max_val + 5, 500)
        
        # Kernel Density Estimation for smooth PDF
        kde = stats.gaussian_kde(offsets)
        pdf = kde(x_range)
        
        # Also fit a normal distribution for comparison
        normal_pdf = stats.norm.pdf(x_range, mean, std)
        
        # Plot KDE (actual distribution)
        ax.fill_between(x_range, pdf, alpha=0.3, color=color, label='Empirical PDF (KDE)')
        ax.plot(x_range, pdf, color=color, linewidth=2)
        
        # Plot normal fit (dashed)
        ax.plot(x_range, normal_pdf, '--', color='gray', linewidth=1.5, 
                label=f'Normal fit (μ={mean:.1f}, σ={std:.1f})')
        
        # Mark mean
        ax.axvline(x=mean, color=color, linestyle='-', linewidth=2, label=f'Mean: {mean:.1f} μs')
        
        # Mark ±1σ
        ax.axvline(x=mean - std, color=color, linestyle=':', linewidth=1.5, alpha=0.7)
        ax.axvline(x=mean + std, color=color, linestyle=':', linewidth=1.5, alpha=0.7)
        
        # Shade ±1σ region
        mask = (x_range >= mean - std) & (x_range <= mean + std)
        ax.fill_between(x_range[mask], pdf[mask], alpha=0.2, color=color, 
                       label=f'±1σ: [{mean-std:.1f}, {mean+std:.1f}] μs')
        
        # Mark ±2σ (lighter)
        ax.axvline(x=mean - 2*std, color=color, linestyle='--', linewidth=1, alpha=0.5)
        ax.axvline(x=mean + 2*std, color=color, linestyle='--', linewidth=1, alpha=0.5)
        
        # Add statistics text box
        stats_text = (f'Statistics:\n'
                     f'  Mean (μ): {mean:.2f} μs\n'
                     f'  Std Dev (σ): {std:.2f} μs\n'
                     f'  Min: {min_val:.2f} μs\n'
                     f'  Max: {max_val:.2f} μs\n'
                     f'  Range: {max_val - min_val:.2f} μs\n'
                     f'  N: {len(offsets)} samples')
        
        ax.text(0.97, 0.97, stats_text, transform=ax.transAxes, fontsize=9,
               verticalalignment='top', horizontalalignment='right',
               bbox=dict(boxstyle='round', facecolor='white', alpha=0.9),
               fontfamily='monospace')
        
        # Labels
        ax.set_xlabel('Offset from Master (μs)', fontsize=11)
        ax.set_ylabel('Probability Density', fontsize=11)
        ax.set_title(f'{node["id"]}', fontsize=12, fontweight='bold')
        ax.legend(loc='upper left', fontsize=8)
        ax.grid(True, alpha=0.3)
        
        # Add zero reference line if in range
        if x_range[0] <= 0 <= x_range[-1]:
            ax.axvline(x=0, color='black', linestyle='-', linewidth=1, alpha=0.5)
    
    plt.tight_layout()
    
    # Save plots
    pdf_filename = f"{output_dir}/pdf_{test_name}_{timestamp}.png"
    plt.savefig(pdf_filename, dpi=150, bbox_inches='tight')
    print(f"[PLOT] PDF plot saved: {pdf_filename}")
    
    latest_filename = f"{output_dir}/pdf_{test_name}_latest.png"
    plt.savefig(latest_filename, dpi=150, bbox_inches='tight')
    print(f"[PLOT] Latest PDF: {latest_filename}")
    
    plt.show()
    
    return pdf_filename


def worst_case_analysis(filenames, test_name="test"):
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
        symbol = "[OK]"
    elif worst_case < 500:
        status = "GOOD"
        symbol = "[OK]"
    elif worst_case < 1000:
        status = "ACCEPTABLE"
        symbol = "[--]"
    else:
        status = "POOR - RECALIBRATION RECOMMENDED"
        symbol = "[!!]"
    
    print(f"{symbol} System Status: {status}")
    print(f"  Worst-case inter-device offset: {worst_case:.1f} μs ({worst_case/1000:.3f} ms)")
    print("-" * 70)
    print()
    
    # Create visualization plots
    create_worst_case_plots(nodes, worst_case, worst_pair)
    
    # Create PDF plots with standard deviation
    create_pdf_plot(nodes, test_name=test_name)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 worst_case_offset.py [--name TEST_NAME] <file1.json> <file2.json> [...]")
        print()
        print("Analyzes worst-case time offset between any two devices in the network.")
        print("Considers the master as having 0 offset and finds the maximum possible")
        print("time difference between any pair of nodes (slave-slave or slave-master).")
        print()
        print("Options:")
        print("  --name TEST_NAME   Name for the test (used in plot titles and filenames)")
        print()
        print("Example:")
        print("  python3 worst_case_offset.py --name indoor data/jsons/slave1.json data/jsons/slave2.json")
        print("  python3 worst_case_offset.py --name outdoor data/jsons/outside_*.json")
        sys.exit(1)
    
    # Parse arguments
    test_name = "test"
    filenames = []
    
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == '--name' and i + 1 < len(sys.argv):
            test_name = sys.argv[i + 1]
            i += 2
        else:
            filenames.append(sys.argv[i])
            i += 1
    
    if not filenames:
        print("Error: No data files provided")
        sys.exit(1)
    
    worst_case_analysis(filenames, test_name=test_name)

