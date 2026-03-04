import numpy as np
import cv2

def cfar_cpu(
    rdm_data,
    guard_cells_doppler=4,
    guard_cells_range=8,
    training_cells_doppler=6,
    training_cells_range=12,
    threshold_factor=3.0,
    device="cpu",  # Ignored, kept for compatibility
    **kwargs
):
    """
    Super-optimized 2D CA-CFAR implementation using OpenCV box filters.
    
    This replaces the PyTorch/Integral Image approach with hardware-accelerated 
    sliding window sums (SIMD/NEON).
    """
    # 1. Setup window sizes
    win_h = guard_cells_doppler + training_cells_doppler
    win_w = guard_cells_range + training_cells_range
    
    # Kernel sizes for boxFilter
    # Full window size (Outer)
    outer_h = 2 * win_h + 1
    outer_w = 2 * win_w + 1
    
    # Guard region size (Inner)
    inner_h = 2 * guard_cells_doppler + 1
    inner_w = 2 * guard_cells_range + 1
    
    # Number of training cells
    training_cell_count = (outer_h * outer_w) - (inner_h * inner_w)
    
    # 2. Pad the data once
    # We use reflect padding for radar data to handle edges gracefully
    padded = cv2.copyMakeBorder(
        rdm_data, 
        win_h, win_h, win_w, win_w, 
        cv2.BORDER_REFLECT
    )
    
    # 3. Compute sums using OpenCV optimized boxFilter
    # boxFilter(src, ddepth, ksize, normalize=False)
    # result[y,x] = sum_{dy,dx} src[y+dy, x+dx]
    
    # Outer sum (full window)
    # Note: anchor=(-1,-1) means center
    outer_sum = cv2.boxFilter(padded, -1, (outer_w, outer_h), normalize=False)
    
    # Inner sum (guard + CUT)
    inner_sum = cv2.boxFilter(padded, -1, (inner_w, inner_h), normalize=False)
    
    # 4. Crop back to original size
    # The sums at index [win_h:-win_h, win_w:-win_w] correspond to original grid centers
    h, w = rdm_data.shape
    outer_sum = outer_sum[win_h : win_h + h, win_w : win_w + w]
    inner_sum = inner_sum[win_h : win_h + h, win_w : win_w + w]
    
    # 5. CA-CFAR Logic
    # threshold = (TrainSum / TrainCount) * Factor
    noise_level = (outer_sum - inner_sum) / training_cell_count
    threshold = noise_level * threshold_factor
    
    # Detections
    detections = (rdm_data > threshold).astype(np.float32)
    
    return detections
