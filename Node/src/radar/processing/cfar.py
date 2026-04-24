import sys
import numpy as np
import torch
import torch.nn.functional as F
from .. import config

# Debug flag - set to True to enable debugging output
DEBUG = False

def box_sum_integral(data, h1, h2, w1, w2):
    """Compute box sums using integral image for O(1) per box operation.

    Args:
        data: 2D tensor [H, W]
        h1, h2: height range (inclusive top, exclusive bottom)
        w1, w2: width range (inclusive left, exclusive right)

    Returns:
        Box sums for each position using windows of size (h2-h1) x (w2-w1)
    """
    H, W = data.shape

    # Compute integral image (cumulative sum)
    # Add zero padding on top and left for easier indexing
    integral = torch.zeros((H + 1, W + 1), dtype=data.dtype, device=data.device)
    integral[1:, 1:] = torch.cumsum(torch.cumsum(data, dim=0), dim=1)

    # Extract box sums using the integral image
    # For a box from (r1,c1) to (r2,c2), sum = I[r2,c2] - I[r1,c2] - I[r2,c1] + I[r1,c1]
    h_size = h2 - h1
    w_size = w2 - w1

    # Result will have shape [H, W] where each position is the sum of the box ending at that position
    # We want the box centered at each position, so we need to offset appropriately
    result = (
        integral[h2 : H + h2, w2 : W + w2]
        - integral[h1 : H + h1, w2 : W + w2]
        - integral[h2 : H + h2, w1 : W + w1]
        + integral[h1 : H + h1, w1 : W + w1]
    )

    return result


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
    """Run CFAR algorithm using integral images for ultra-fast box sum computation.

    This function applies a CFAR detection algorithm with separate window
    parameters for Doppler (slow time) and Range (fast time) dimensions.
    Uses integral images to compute box sums in O(1) per pixel.

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
        device: Device to run on, 'cuda' or 'cpu' (default: 'cpu')

    Returns:
        detections: Binary detection map of shape (SLOW_TIME, FAST_TIME//2)
                   where 1 indicates detection and 0 indicates no detection
    """
    # Step 1: Get dimensions of input data
    slow_time, fast_time = rdm_data.shape
    if DEBUG:
        print(f"[CFAR DEBUG] Input shape: {slow_time}x{fast_time}")

    # Step 2: Extract only the positive range bins (first half of fast time)
    rdm_half = rdm_data[:, :fast_time]

    # Step 3: Calculate window sizes for each dimension
    window_size_doppler = guard_cells_doppler + training_cells_doppler
    window_size_range = guard_cells_range + training_cells_range

    # Step 4: Determine padding sizes (use window sizes if not provided)
    if pad_doppler is None:
        pad_doppler = window_size_doppler
    if pad_range is None:
        pad_range = window_size_range

    if DEBUG:
        print(
            f"[CFAR DEBUG] Window sizes - Doppler: {window_size_doppler}, Range: {window_size_range}"
        )
        print(
            f"[CFAR DEBUG] Guard cells - Doppler: {guard_cells_doppler}, Range: {guard_cells_range}"
        )

    # Step 4a: Validate parameters
    if pad_doppler < window_size_doppler:
        raise ValueError(
            f"pad_doppler ({pad_doppler}) must be >= window_size_doppler ({window_size_doppler})"
        )
    if pad_range < window_size_range:
        raise ValueError(
            f"pad_range ({pad_range}) must be >= window_size_range ({window_size_range})"
        )

    # Step 5: Determine padding value (use mean if not provided)
    if pad_value is None:
        pad_value = float(np.mean(rdm_half))

    # Step 6: Convert to PyTorch tensor and move to device
    rdm_tensor = torch.from_numpy(rdm_half).float().to(device)

    # Step 7: Pad the tensor for edge handling
    # torch.nn.functional.pad format: (left, right, top, bottom)
    padded_rdm = F.pad(
        rdm_tensor,
        (pad_range, pad_range, pad_doppler, pad_doppler),
        mode="constant",
        value=pad_value,
    )

    if DEBUG:
        print(f"[CFAR DEBUG] Padded shape: {padded_rdm.shape}")

    # Step 8: Compute training cell statistics using integral images
    # The training region is the full window minus the guard region
    # We'll compute: sum(full_window) - sum(guard_region)

    # Full window dimensions
    full_h = 2 * window_size_doppler + 1
    full_w = 2 * window_size_range + 1

    # Guard region dimensions (including CUT)
    guard_h = 2 * guard_cells_doppler + 1
    guard_w = 2 * guard_cells_range + 1

    # Number of training cells
    training_cell_count = full_h * full_w - guard_h * guard_w

    if DEBUG:
        print(f"[CFAR DEBUG] Full window: {full_h}x{full_w} = {full_h * full_w} cells")
        print(
            f"[CFAR DEBUG] Guard region: {guard_h}x{guard_w} = {guard_h * guard_w} cells"
        )
        print(f"[CFAR DEBUG] Training cells: {training_cell_count}")

    # Compute integral image once
    H, W = padded_rdm.shape
    integral = torch.zeros((H + 1, W + 1), dtype=torch.float32, device=device)
    integral[1:, 1:] = torch.cumsum(torch.cumsum(padded_rdm, dim=0), dim=1)

    # Define box extraction function using precomputed integral
    def extract_box_sums(top_offset, bottom_offset, left_offset, right_offset):
        """Extract box sums for all positions with given offsets from center."""
        h1 = top_offset
        h2 = H - bottom_offset
        w1 = left_offset
        w2 = W - right_offset

        result = (
            integral[h2 : H + 1, w2 : W + 1]
            - integral[h1 : H - h2 + h1 + 1, w2 : W + 1]
            - integral[h2 : H + 1, w1 : W - w2 + w1 + 1]
            + integral[h1 : H - h2 + h1 + 1, w1 : W - w2 + w1 + 1]
        )
        return result[:slow_time, : fast_time // 2]

    # Compute sum of full window centered at each cell
    # For padded data, the original cells are at [pad_doppler:pad_doppler+slow_time, pad_range:pad_range+fast_time//2]
    # Extract the region where we can compute full windows
    extract_region = padded_rdm[
        pad_doppler - window_size_doppler : pad_doppler
        + slow_time
        + window_size_doppler,
        pad_range - window_size_range : pad_range + (fast_time) + window_size_range,
    ]

    H_extract, W_extract = extract_region.shape

    # Compute integral for the extraction region
    integral_extract = torch.zeros(
        (H_extract + 1, W_extract + 1), dtype=torch.float32, device=device
    )
    integral_extract[1:, 1:] = torch.cumsum(torch.cumsum(extract_region, dim=0), dim=1)

    # Full window sum: box from (0, 0) to (full_h, full_w) at each position
    full_window_sum = (
        integral_extract[full_h : H_extract + 1, full_w : W_extract + 1]
        - integral_extract[:-full_h, full_w : W_extract + 1]
        - integral_extract[full_h : H_extract + 1, :-full_w]
        + integral_extract[:-full_h, :-full_w]
    )

    # Guard region sum: centered box of size (guard_h, guard_w)
    offset_h = window_size_doppler - guard_cells_doppler
    offset_w = window_size_range - guard_cells_range

    guard_window_sum = (
        integral_extract[
            offset_h + guard_h : H_extract - offset_h + 1,
            offset_w + guard_w : W_extract - offset_w + 1,
        ]
        - integral_extract[
            offset_h : H_extract - offset_h - guard_h + 1,
            offset_w + guard_w : W_extract - offset_w + 1,
        ]
        - integral_extract[
            offset_h + guard_h : H_extract - offset_h + 1,
            offset_w : W_extract - offset_w - guard_w + 1,
        ]
        + integral_extract[
            offset_h : H_extract - offset_h - guard_h + 1,
            offset_w : W_extract - offset_w - guard_w + 1,
        ]
    )

    # Training sum = full window - guard region
    training_sum = full_window_sum - guard_window_sum

    # Compute noise level (mean of training cells)
    noise_level = training_sum / training_cell_count

    if DEBUG:
        noise_cpu = noise_level.cpu().numpy()
        print(
            f"[CFAR DEBUG] Noise level range: min={noise_cpu.min():.3f}, max={noise_cpu.max():.3f}, mean={noise_cpu.mean():.3f}"
        )

    # Step 9: Compute threshold
    threshold = noise_level * threshold_factor

    if DEBUG:
        threshold_cpu = threshold.cpu().numpy()
        print(
            f"[CFAR DEBUG] Threshold range: min={threshold_cpu.min():.3f}, max={threshold_cpu.max():.3f}"
        )

    # Step 10: Extract cells under test from original unpadded data
    cells_under_test = rdm_tensor

    # Step 11: Apply threshold test
    detections_tensor = cells_under_test > threshold

    if DEBUG:
        detections_cpu = detections_tensor.cpu().numpy()
        num_detections = int(detections_cpu.sum())
        total_cells = detections_cpu.size
        detection_rate = num_detections / total_cells * 100
        print(
            f"[CFAR DEBUG] Detections: {num_detections} out of {total_cells} cells ({detection_rate:.2f}%)"
        )

    # Step 12: Convert back to NumPy array and return
    detections = detections_tensor.cpu().numpy().astype(np.float32)

    return detections
