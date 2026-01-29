import sys

import numpy as np
import torch
import torch.nn.functional as F

# Radar parameters
FAST_TIME = 512
SLOW_TIME = 64
CARRIER_FREQ = 77e9
SPEED_OF_LIGHT = 3e8
LAMBDA = SPEED_OF_LIGHT / CARRIER_FREQ
CHIRP_DURATION = 100e-6
MAX_VELOCITY = LAMBDA / (4.0 * CHIRP_DURATION)
VELOCITY_RES = 2.0 * MAX_VELOCITY / SLOW_TIME
RANGE_MULTIPLIER = 9.0 / 256.0
MAX_RANGE = 9.0


def cfar_pytorch(
    rdm_data,
    guard_cells_doppler=4,
    guard_cells_range=8,
    training_cells_doppler=6,
    training_cells_range=12,
    threshold_factor=3.0,
    pad_value=None,
    pad_doppler=None,
    pad_range=None,
    device="cpu",
):
    """Run CFAR algorithm using PyTorch for GPU acceleration.

    This function applies a CFAR detection algorithm with separate window
    parameters for Doppler (slow time) and Range (fast time) dimensions.
    Uses PyTorch's unfold operation to extract all windows simultaneously
    and process them in parallel on GPU.

    Args:
        rdm_data: Input range-Doppler map of shape (SLOW_TIME, FAST_TIME)
        guard_cells_doppler: Number of guard cells in Doppler/slow-time dimension (default: 4)
        guard_cells_range: Number of guard cells in Range/fast-time dimension (default: 8)
        training_cells_doppler: Number of training cells in Doppler dimension (default: 6)
        training_cells_range: Number of training cells in Range dimension (default: 12)
        threshold_factor: Multiplicative factor for threshold (default: 3.0)
        pad_value: Value to use for padding. If None, uses mean of RDM data (default: None)
        pad_doppler: Number of cells to pad in Doppler dimension (top/bottom).
                     If None, uses window_size_doppler (default: None)
        pad_range: Number of cells to pad in Range dimension (left/right).
                   If None, uses window_size_range (default: None)
        device: Device to run on, 'cuda' or 'cpu' (default: 'cuda')

    Returns:
        detections: Binary detection map of shape (SLOW_TIME, FAST_TIME//2)
                   where 1 indicates detection and 0 indicates no detection
    """
    # Step 1: Get dimensions of input data
    slow_time, fast_time = rdm_data.shape

    # Step 2: Extract only the positive range bins (first half of fast time)
    rdm_half = rdm_data[:, : fast_time // 2]
    output_shape = (slow_time, fast_time // 2)

    # Step 3: Calculate window sizes for each dimension
    window_size_doppler = guard_cells_doppler + training_cells_doppler
    window_size_range = guard_cells_range + training_cells_range

    # Step 4: Determine padding sizes (use window sizes if not provided)
    if pad_doppler is None:
        pad_doppler = window_size_doppler
    if pad_range is None:
        pad_range = window_size_range

    # Step 4a: Validate parameters for dimensional consistency
    # Check that padding is sufficient for the window sizes
    if pad_doppler < window_size_doppler:
        raise ValueError(
            f"pad_doppler ({pad_doppler}) must be >= window_size_doppler ({window_size_doppler}). "
            f"Need at least {window_size_doppler} padding for guard_cells ({guard_cells_doppler}) + training_cells ({training_cells_doppler})."
        )
    if pad_range < window_size_range:
        raise ValueError(
            f"pad_range ({pad_range}) must be >= window_size_range ({window_size_range}). "
            f"Need at least {window_size_range} padding for guard_cells ({guard_cells_range}) + training_cells ({training_cells_range})."
        )

    # Validate input dimensions
    if slow_time <= 0 or fast_time <= 0:
        raise ValueError(f"Invalid RDM dimensions: {rdm_data.shape}")

    if rdm_data.ndim != 2:
        raise ValueError(f"RDM data must be 2D, got shape: {rdm_data.shape}")

    # Check that we have enough data after padding for window extraction
    padded_h = slow_time + 2 * pad_doppler
    padded_w = (fast_time // 2) + 2 * pad_range
    required_h = slow_time + 2 * window_size_doppler
    required_w = (fast_time // 2) + 2 * window_size_range

    if padded_h < required_h:
        raise ValueError(
            f"Insufficient padding in Doppler dimension. Padded height: {padded_h}, Required: {required_h}"
        )
    if padded_w < required_w:
        raise ValueError(
            f"Insufficient padding in Range dimension. Padded width: {padded_w}, Required: {required_w}"
        )

    # Step 5: Determine padding value (use mean if not provided)
    if pad_value is None:
        pad_value = np.mean(rdm_half)

    # Step 6: Convert to PyTorch tensor and move to device
    # Add batch and channel dimensions: [1, 1, H, W]
    rdm_tensor = torch.from_numpy(rdm_half).float().unsqueeze(0).unsqueeze(0)
    rdm_tensor = rdm_tensor.to(device)

    # Step 7: Pad the tensor for edge handling
    # F.pad format: (left, right, top, bottom)
    padded_rdm = F.pad(
        rdm_tensor,
        (pad_range, pad_range, pad_doppler, pad_doppler),
        mode="constant",
        value=pad_value,
    )

    # Step 8: Define the full window size for unfolding
    window_h = 2 * window_size_doppler + 1
    window_w = 2 * window_size_range + 1

    # Step 9: Use unfold to extract all windows simultaneously centered on each cell
    # The original data is at indices [pad_doppler:pad_doppler+slow_time, pad_range:pad_range+(fast_time//2)]
    # We need windows centered on each of these cells
    # Start extracting from (pad_doppler - window_size_doppler) to get first window centered on first cell
    # unfold(dimension, size, step) with step=1
    # Output size = (input_size - window_size + 1)
    # We want output = slow_time, so input = slow_time + window_h - 1 = slow_time + 2*window_size_doppler

    # Extract region that will give us exactly slow_time x (fast_time//2) windows
    extract_start_h = pad_doppler - window_size_doppler
    extract_end_h = pad_doppler + slow_time + window_size_doppler
    extract_start_w = pad_range - window_size_range
    extract_end_w = pad_range + (fast_time // 2) + window_size_range

    # Validate extraction bounds
    if extract_start_h < 0 or extract_end_h > padded_rdm.shape[2]:
        raise RuntimeError(
            f"Doppler extraction out of bounds: [{extract_start_h}:{extract_end_h}] for padded size {padded_rdm.shape[2]}"
        )
    if extract_start_w < 0 or extract_end_w > padded_rdm.shape[3]:
        raise RuntimeError(
            f"Range extraction out of bounds: [{extract_start_w}:{extract_end_w}] for padded size {padded_rdm.shape[3]}"
        )

    windows = (
        padded_rdm[:, :, extract_start_h:extract_end_h, extract_start_w:extract_end_w]
        .unfold(2, window_h, 1)
        .unfold(3, window_w, 1)
    )
    # Shape: [1, 1, slow_time, fast_time//2, window_h, window_w]

    # Validate windows shape
    expected_shape = (1, 1, slow_time, fast_time // 2, window_h, window_w)
    if windows.shape != expected_shape:
        raise RuntimeError(
            f"Window extraction produced unexpected shape: {windows.shape}, expected: {expected_shape}"
        )

    # Step 10: Reshape windows for easier processing
    # Combine spatial dimensions and flatten window dimensions
    windows = windows.squeeze(0).squeeze(
        0
    )  # [slow_time, fast_time//2, window_h, window_w]

    # Step 11: Create guard cell mask to exclude guard region from training
    # Build a mask where True = training cell, False = guard cell or CUT
    guard_mask = torch.ones((window_h, window_w), dtype=torch.bool, device=device)

    # Calculate center position of the window
    center_i = window_size_doppler
    center_j = window_size_range

    # Step 12: Set guard region and CUT to False in mask
    for i in range(window_h):
        for j in range(window_w):
            doppler_distance = abs(i - center_i)
            range_distance = abs(j - center_j)

            # Exclude cells within guard region (using OR logic)
            if (
                doppler_distance <= guard_cells_doppler
                and range_distance <= guard_cells_range
            ):
                guard_mask[i, j] = False

    # Step 13: Apply mask to extract training cells and compute noise level
    # Expand mask to match windows shape
    mask_expanded = guard_mask.unsqueeze(0).unsqueeze(0)  # [1, 1, window_h, window_w]
    mask_expanded = mask_expanded.expand_as(
        windows
    )  # [slow_time, fast_time//2, window_h, window_w]

    # Step 14: Compute mean of training cells for each window
    # Use masked_select alternative: set guard cells to 0 and count valid cells
    training_windows = windows * mask_expanded.float()

    # Sum training cell values and count of training cells
    training_sum = training_windows.sum(dim=(-2, -1))  # [slow_time, fast_time//2]
    training_count = mask_expanded.float().sum(
        dim=(-2, -1)
    )  # [slow_time, fast_time//2]

    # Compute noise level (mean of training cells)
    noise_level = training_sum / (
        training_count + 1e-10
    )  # Add epsilon to avoid division by zero

    # Step 15: Compute threshold for each cell
    threshold = noise_level * threshold_factor

    # Step 16: Extract cells under test from original unpadded data
    cells_under_test = rdm_tensor[0, 0, :, :]  # [slow_time, fast_time//2]

    # Validate threshold and cells_under_test have matching shapes
    if cells_under_test.shape != threshold.shape:
        raise RuntimeError(
            f"Shape mismatch: cells_under_test {cells_under_test.shape} != threshold {threshold.shape}"
        )

    # Step 17: Apply threshold test - compare CUT to threshold
    detections_tensor = (cells_under_test > threshold).float()

    # Step 18: Convert back to NumPy array and return
    detections = detections_tensor.cpu().numpy()

    return detections
