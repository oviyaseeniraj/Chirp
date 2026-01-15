#!/usr/bin/env python3
"""
Analyze collected Chrony offset data.
Run this after collect_offsets.py
"""

import json
import numpy as np
import sys
from scipy import stats
from scipy.stats import gaussian_kde
import os
from datetime import datetime
from itertools import combinations

def load_data(filename):
    """Load JSON data (handles both old and new format)."""
    with open(filename, 'r') as f:
        data = json.load(f)
    
    # Handle new format with metadata
    if isinstance(data, dict) and 'samples' in data:
        return data['samples'], data.get('metadata', {})
    # Handle old format (list of samples)
    else:
        return data, {}

def modified_z_score(data):
    """Calculate modified Z-scores for outlier detection."""
    median = np.median(data)
    mad = np.median(np.abs(data - median))
    if mad == 0:
        return np.zeros_like(data)
    modified_z = 0.6745 * (data - median) / mad
    return modified_z

def analyze_offsets(filename):
    """Perform statistical analysis on offset data."""
    print("="*60)
    print("CHRONY OFFSET ANALYSIS")
    print("="*60)
    print()
    
    # Load data
    data, metadata = load_data(filename)
    print(f"Loaded {len(data)} samples from {filename}")
    if metadata:
        print(f"Node ID: {metadata.get('node_id', 'Unknown')}")
        print(f"Collection period: {metadata.get('start_time', 'N/A')} to {metadata.get('end_time', 'N/A')}")
    print()
    
    # Extract offset arrays
    offset_us = np.array([s['offset_us'] for s in data])
    offset_ms = offset_us / 1000.0
    
    frequency_ppm = np.array([s['frequency_ppm'] for s in data])
    
    # Basic statistics
    print("─" * 60)
    print("OFFSET STATISTICS (microseconds)")
    print("─" * 60)
    print(f"Mean:              {np.mean(offset_us):+8.2f} μs  ({np.mean(offset_ms):+.4f} ms)")
    print(f"Median:            {np.median(offset_us):+8.2f} μs  ({np.median(offset_ms):+.4f} ms)")
    print(f"Std Deviation:     {np.std(offset_us):8.2f} μs  ({np.std(offset_ms):.4f} ms)")
    print(f"Min:               {np.min(offset_us):+8.2f} μs  ({np.min(offset_ms):+.4f} ms)")
    print(f"Max:               {np.max(offset_us):+8.2f} μs  ({np.max(offset_ms):+.4f} ms)")
    print(f"Range:             {np.ptp(offset_us):8.2f} μs  ({np.ptp(offset_ms):.4f} ms)")
    print()
    
    # Percentiles
    print("─" * 60)
    print("PERCENTILES")
    print("─" * 60)
    percentiles = [1, 5, 25, 50, 75, 95, 99]
    for p in percentiles:
        val = np.percentile(offset_us, p)
        print(f"P{p:2d}:                {val:+8.2f} μs")
    print()
    
    # IQR
    q1 = np.percentile(offset_us, 25)
    q3 = np.percentile(offset_us, 75)
    iqr = q3 - q1
    print(f"IQR (Q3-Q1):       {iqr:8.2f} μs")
    print()
    
    # Outlier detection
    print("─" * 60)
    print("OUTLIER DETECTION")
    print("─" * 60)
    
    # Modified Z-score method
    z_scores = modified_z_score(offset_us)
    outliers_z = np.abs(z_scores) > 3.5
    
    print(f"Modified Z-score (|Z| > 3.5):")
    print(f"  Outliers:        {np.sum(outliers_z)} / {len(offset_us)} ({np.sum(outliers_z)/len(offset_us)*100:.1f}%)")
    
    # IQR method
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr
    outliers_iqr = (offset_us < lower_bound) | (offset_us > upper_bound)
    
    print(f"IQR method (1.5×IQR):")
    print(f"  Outliers:        {np.sum(outliers_iqr)} / {len(offset_us)} ({np.sum(outliers_iqr)/len(offset_us)*100:.1f}%)")
    print()
    
    # Filtered statistics (remove outliers)
    print("─" * 60)
    print("FILTERED STATISTICS (outliers removed)")
    print("─" * 60)
    
    filtered_us = offset_us[~outliers_z]
    filtered_ms = filtered_us / 1000.0
    
    print(f"Filtered samples:  {len(filtered_us)} / {len(offset_us)}")
    print(f"Trimmed Mean:      {np.mean(filtered_us):+8.2f} μs  ({np.mean(filtered_ms):+.4f} ms)")
    print(f"Trimmed Median:    {np.median(filtered_us):+8.2f} μs  ({np.median(filtered_ms):+.4f} ms)")
    print(f"Trimmed Std Dev:   {np.std(filtered_us):8.2f} μs  ({np.std(filtered_ms):.4f} ms)")
    print()
    
    # 10% trimmed mean
    trim_percent = 10
    trim_count = int(len(offset_us) * trim_percent / 100)
    sorted_offsets = np.sort(offset_us)
    trimmed_10 = sorted_offsets[trim_count:-trim_count] if trim_count > 0 else sorted_offsets
    
    print(f"10% Trimmed Mean:  {np.mean(trimmed_10):+8.2f} μs  ({np.mean(trimmed_10)/1000:+.4f} ms)")
    print()
    
    # Normality test
    print("─" * 60)
    print("DISTRIBUTION TESTS")
    print("─" * 60)
    
    # Shapiro-Wilk test
    if len(offset_us) <= 5000:
        stat, p_value = stats.shapiro(offset_us)
        print(f"Shapiro-Wilk test:")
        print(f"  Statistic:       {stat:.6f}")
        print(f"  P-value:         {p_value:.6f}")
        print(f"  Normal dist:     {'Yes' if p_value > 0.05 else 'No'} (α=0.05)")
    else:
        print("Shapiro-Wilk test: Skipped (too many samples)")
    
    # Skewness and Kurtosis
    skewness = stats.skew(offset_us)
    kurtosis = stats.kurtosis(offset_us)
    print(f"Skewness:          {skewness:+8.4f}")
    print(f"Kurtosis:          {kurtosis:+8.4f}")
    print()
    
    # Frequency statistics
    print("─" * 60)
    print("FREQUENCY DRIFT")
    print("─" * 60)
    print(f"Mean frequency:    {np.mean(frequency_ppm):+.3f} ppm")
    print(f"Std deviation:     {np.std(frequency_ppm):.3f} ppm")
    print(f"Range:             {np.ptp(frequency_ppm):.3f} ppm")
    print()
    
    # Allan variance (simplified)
    if len(offset_us) > 10:
        print("─" * 60)
        print("STABILITY METRICS")
        print("─" * 60)
        
        # Simple Allan deviation for tau = sampling interval
        diffs = np.diff(offset_us)
        allan_var = np.var(diffs) / 2
        allan_dev = np.sqrt(allan_var)
        
        print(f"Allan deviation:   {allan_dev:.2f} μs")
        print(f"RMS jitter:        {np.std(diffs):.2f} μs")
        print()
    
    # Recommended true offset
    print("="*60)
    print("RECOMMENDED TRUE OFFSET ESTIMATE")
    print("="*60)
    print()
    print(f"Best estimate:     {np.mean(filtered_us):+.2f} μs  ({np.mean(filtered_ms):+.4f} ms)")
    print(f"Uncertainty (σ):   ±{np.std(filtered_us):.2f} μs  (±{np.std(filtered_ms):.4f} ms)")
    print(f"95% CI:            [{np.mean(filtered_us) - 1.96*np.std(filtered_us):+.2f}, {np.mean(filtered_us) + 1.96*np.std(filtered_us):+.2f}] μs")
    print()
    
    # Save summary
    summary = {
        'num_samples': len(offset_us),
        'num_samples_filtered': len(filtered_us),
        'mean_us': float(np.mean(offset_us)),
        'median_us': float(np.median(offset_us)),
        'std_us': float(np.std(offset_us)),
        'trimmed_mean_us': float(np.mean(filtered_us)),
        'trimmed_std_us': float(np.std(filtered_us)),
        'min_us': float(np.min(offset_us)),
        'max_us': float(np.max(offset_us)),
        'outliers_count': int(np.sum(outliers_z)),
        'mean_frequency_ppm': float(np.mean(frequency_ppm)),
        'std_frequency_ppm': float(np.std(frequency_ppm)),
    }

    script_dir = os.path.dirname(os.path.abspath(__file__))
    jsons_dir = os.path.join(script_dir, 'data', 'jsons')
    base_name = os.path.basename(filename).replace('.json', '_summary.json')
    full_output_path = os.path.join(jsons_dir, base_name)

    with open(full_output_path, 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"Summary saved to: {full_output_path}")
    print()
    
    return data, offset_us, filtered_us, metadata

def plot_histogram(filename):
    """Generate plots if matplotlib available."""
    try:
        import matplotlib.pyplot as plt
        import os
    except ImportError:
        print("Matplotlib not available. Skipping plots.")
        return
    
    data, offset_us, filtered_us, metadata = analyze_offsets(filename)
    node_id = metadata.get('node_id', 'Unknown') if metadata else 'Unknown'
    
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    
    # Time series
    ax = axes[0, 0]
    ax.plot(offset_us, marker='o', markersize=2, linestyle='-', linewidth=0.5)
    ax.axhline(np.mean(offset_us), color='r', linestyle='--', label=f'Mean: {np.mean(offset_us):.1f} μs')
    ax.axhline(np.median(offset_us), color='g', linestyle='--', label=f'Median: {np.median(offset_us):.1f} μs')
    ax.set_xlabel('Sample Number')
    ax.set_ylabel('Offset (μs)')
    ax.set_title('Clock Offset Over Time')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # Histogram
    ax = axes[0, 1]
    ax.hist(offset_us, bins=50, alpha=0.7, edgecolor='black')
    ax.axvline(np.mean(offset_us), color='r', linestyle='--', label=f'Mean')
    ax.axvline(np.median(offset_us), color='g', linestyle='--', label=f'Median')
    ax.set_xlabel('Offset (μs)')
    ax.set_ylabel('Count')
    ax.set_title('Offset Distribution')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # Q-Q plot
    ax = axes[1, 0]
    stats.probplot(offset_us, dist="norm", plot=ax)
    ax.set_title('Q-Q Plot (Normality Test)')
    ax.grid(True, alpha=0.3)
    
    # Filtered histogram
    ax = axes[1, 1]
    ax.hist(filtered_us, bins=50, alpha=0.7, color='green', edgecolor='black')
    ax.axvline(np.mean(filtered_us), color='r', linestyle='--', label=f'Mean: {np.mean(filtered_us):.1f} μs')
    ax.set_xlabel('Offset (μs)')
    ax.set_ylabel('Count')
    ax.set_title('Filtered Offset Distribution (Outliers Removed)')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Build path to data/histograms relative to script location
    histograms_dir = os.path.join(script_dir, 'data', 'histograms')
    
    base_name = os.path.basename(filename).replace('.json', '_histogram.png')
    plot_file = os.path.join(histograms_dir, base_name)
    plt.savefig(plot_file, dpi=300)
    print(f"Plots saved to: {plot_file}")
    
    plt.show()

def plot_pdf(filename):
    try:
        import matplotlib.pyplot as plt
    except ImportError:
            print("Matplotlib not available. Skipping plots.")
            return
        
    data, offset_us, filtered_us, metadata = analyze_offsets(filename)
    node_id = metadata.get('node_id', 'Unknown') if metadata else 'Unknown'
    
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))

    # Time series (unchanged)
    ax = axes[0, 0]
    ax.plot(offset_us, marker='o', markersize=2, linestyle='-', linewidth=0.5)
    ax.axhline(np.mean(offset_us), color='r', linestyle='--', label=f'Mean: {np.mean(offset_us):.1f} μs')
    ax.axhline(np.median(offset_us), color='g', linestyle='--', label=f'Median: {np.median(offset_us):.1f} μs')
    ax.set_xlabel('Sample Number')
    ax.set_ylabel('Offset (μs)')
    ax.set_title('Clock Offset Over Time')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # PDF using KDE (MODIFIED)
    ax = axes[0, 1]
    # Create KDE
    kde = gaussian_kde(offset_us)
    # Create smooth x-axis range
    x_range = np.linspace(offset_us.min(), offset_us.max(), 1000)
    # Evaluate PDF
    pdf_values = kde(x_range)
    
    # Plot PDF
    ax.plot(x_range, pdf_values, linewidth=2, color='blue', label='PDF (KDE)')
    ax.fill_between(x_range, pdf_values, alpha=0.3)
    ax.axvline(np.mean(offset_us), color='r', linestyle='--', linewidth=2, label=f'Mean')
    ax.axvline(np.median(offset_us), color='g', linestyle='--', linewidth=2, label=f'Median')
    ax.set_xlabel('Offset (μs)')
    ax.set_ylabel('Probability Density')
    ax.set_title('Offset Probability Density Function')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # Q-Q plot (unchanged)
    ax = axes[1, 0]
    stats.probplot(offset_us, dist="norm", plot=ax)
    ax.set_title('Q-Q Plot (Normality Test)')
    ax.grid(True, alpha=0.3)
    
    # Filtered PDF (MODIFIED)
    ax = axes[1, 1]
    # Create KDE for filtered data
    kde_filtered = gaussian_kde(filtered_us)
    # Create smooth x-axis range
    x_range_filtered = np.linspace(filtered_us.min(), filtered_us.max(), 1000)
    # Evaluate PDF
    pdf_filtered = kde_filtered(x_range_filtered)
    
    # Plot PDF
    ax.plot(x_range_filtered, pdf_filtered, linewidth=2, color='green', label='PDF (KDE)')
    ax.fill_between(x_range_filtered, pdf_filtered, alpha=0.3, color='green')
    ax.axvline(np.mean(filtered_us), color='r', linestyle='--', linewidth=2, label=f'Mean: {np.mean(filtered_us):.1f} μs')
    ax.set_xlabel('Offset (μs)')
    ax.set_ylabel('Probability Density')
    ax.set_title('Filtered Offset PDF (Outliers Removed)')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Build path to data/histograms relative to script location
    pdfs_dir = os.path.join(script_dir, 'data', 'pdfs')

    base_name = os.path.basename(filename).replace('.json', '_pdf.png')
    plot_file = os.path.join(pdfs_dir, base_name)
    plt.savefig(plot_file, dpi=300)
    print(f"Plots saved to: {plot_file}")
    
    plt.show()

def compare_nodes(filenames):
    """Compare offset data from multiple slave nodes."""
    print("="*60)
    print("MULTI-NODE COMPARISON")
    print("="*60)
    print()
    
    if len(filenames) < 2:
        print("Error: Need at least 2 files to compare")
        return
    
    nodes_data = []
    for filename in filenames:
        data, metadata = load_data(filename)
        offset_us = np.array([s['offset_us'] for s in data])
        node_id = metadata.get('node_id', os.path.basename(filename)) if metadata else os.path.basename(filename)
        nodes_data.append({
            'filename': filename,
            'node_id': node_id,
            'data': data,
            'offset_us': offset_us,
            'metadata': metadata
        })
    
    # Summary table
    print("─" * 80)
    print(f"{'Node ID':<20} {'Samples':<10} {'Mean (μs)':<15} {'Std (μs)':<15} {'Range (μs)':<15}")
    print("─" * 80)
    
    for node in nodes_data:
        print(f"{node['node_id']:<20} "
              f"{len(node['offset_us']):<10} "
              f"{np.mean(node['offset_us']):+.2f}{'':<9} "
              f"{np.std(node['offset_us']):.2f}{'':<10} "
              f"{np.ptp(node['offset_us']):.2f}")
    print()
    
    # Statistical comparison
    print("─" * 60)
    print("STATISTICAL COMPARISON")
    print("─" * 60)
    
    # Pairwise t-tests
    for (node1, node2) in combinations(nodes_data, 2):
        t_stat, p_value = stats.ttest_ind(node1['offset_us'], node2['offset_us'])
        print(f"{node1['node_id']} vs {node2['node_id']}:")
        print(f"  T-statistic: {t_stat:+.4f}")
        print(f"  P-value: {p_value:.6f}")
        print(f"  Significantly different: {'Yes' if p_value < 0.05 else 'No'} (α=0.05)")
        
        # Mean difference
        mean_diff = np.mean(node1['offset_us']) - np.mean(node2['offset_us'])
        print(f"  Mean difference: {mean_diff:+.2f} μs")
        print()
    
    # Plot comparison if matplotlib available
    try:
        import matplotlib.pyplot as plt
        
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        
        # Time series overlay
        ax = axes[0, 0]
        for node in nodes_data:
            ax.plot(node['offset_us'], label=node['node_id'], alpha=0.7, linewidth=1)
        ax.set_xlabel('Sample Number')
        ax.set_ylabel('Offset (μs)')
        ax.set_title('Clock Offset Over Time (All Nodes)')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # Box plot comparison
        ax = axes[0, 1]
        box_data = [node['offset_us'] for node in nodes_data]
        box_labels = [node['node_id'] for node in nodes_data]
        ax.boxplot(box_data, labels=box_labels)
        ax.set_ylabel('Offset (μs)')
        ax.set_title('Offset Distribution Comparison')
        ax.grid(True, alpha=0.3)
        
        # Histogram overlay
        ax = axes[1, 0]
        for node in nodes_data:
            ax.hist(node['offset_us'], bins=30, alpha=0.5, label=node['node_id'], edgecolor='black')
        ax.set_xlabel('Offset (μs)')
        ax.set_ylabel('Count')
        ax.set_title('Offset Histogram Comparison')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # Violin plot
        ax = axes[1, 1]
        parts = ax.violinplot(box_data, positions=range(len(nodes_data)), 
                             showmeans=True, showmedians=True)
        ax.set_xticks(range(len(nodes_data)))
        ax.set_xticklabels(box_labels)
        ax.set_ylabel('Offset (μs)')
        ax.set_title('Offset Distribution (Violin Plot)')
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        # Save plot
        script_dir = os.path.dirname(os.path.abspath(__file__))
        histograms_dir = os.path.join(script_dir, 'data', 'histograms')
        plot_file = os.path.join(histograms_dir, 
                                f"comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        plt.savefig(plot_file, dpi=300)
        print(f"Comparison plot saved to: {plot_file}")
        plt.show()
        
    except ImportError:
        print("Matplotlib not available. Skipping plots.")
    
    print()

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage:")
        print("  Single node:   python3 analyze_offsets.py <data_file.json> [--plot]")
        print("  Multi-node:    python3 analyze_offsets.py --compare <file1.json> <file2.json> [file3.json ...]")
        sys.exit(1)
    
    if '--compare' in sys.argv:
        # Multi-node comparison mode
        compare_idx = sys.argv.index('--compare')
        filenames = [arg for arg in sys.argv[compare_idx+1:] if not arg.startswith('--')]
        if len(filenames) < 2:
            print("Error: --compare requires at least 2 data files")
            sys.exit(1)
        compare_nodes(filenames)
    else:
        # Single node analysis mode
        filename = sys.argv[1]
        
        if '--plot' in sys.argv:
            plot_histogram(filename)
            plot_pdf(filename)
        else:
            analyze_offsets(filename)

