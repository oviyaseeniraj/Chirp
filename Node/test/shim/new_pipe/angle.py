"""
Angle-of-Arrival (AoA) Estimation for MIMO Radar

This module implements Direction of Arrival (DoA) estimation algorithms for MIMO radar systems.
Translates MATLAB angle estimation code to Python with PyTorch acceleration support.

Available Methods:
    1. angle_fft: FFT-based beamforming (fast, standard method)
    2. angle_music: MUSIC algorithm (higher resolution, can resolve multiple sources)
    3. angle_fft_simple: Placeholder for 2D RD maps without MIMO data

Usage Example:
    ```python
    import numpy as np
    from cfar import cfar_pytorch
    from angle import angle_fft

    # Assume you have MIMO radar data
    # clean_rdmap shape: [num_doppler, num_rx, num_tx, num_range]
    clean_rdmap = load_mimo_data()  # Your MIMO data loading
    rdmap_2d = np.abs(clean_rdmap[:, 0, 0, :])  # Extract one channel for CFAR

    # Run CFAR detection
    cfar_detections = cfar_pytorch(rdmap_2d, threshold_factor=2.5, device='cpu')

    # Estimate angles for detections
    angle_estimates = angle_fft(
        cfar_detections=cfar_detections,
        clean_rdmap=clean_rdmap,
        zero_pad_cols=124,
        device='cpu'
    )

    # angle_estimates contains angle in degrees for each detection
    # Zero values indicate no detection at that bin
    ```

Implementation Notes:
    - Based on MATLAB code that uses FFT beamforming for AoA estimation
    - Zero-padding provides angular super-resolution beyond physical array limits
    - Assumes virtual array is built from MIMO TX/RX channels
    - Angle range is in sin(θ) space from -1 to 1 for efficient FFT processing
    - Output angles are in degrees from -90 to +90

Radar Configuration (from main.h):
    - RX antennas: 4
    - TX antennas: 3
    - Virtual array size: 12 elements
    - Carrier frequency: 77 GHz
    - Wavelength: ~3.9 mm
"""

import numpy as np
import torch

# Radar parameters (from main.h)
RX = 4  # Number of receive antennas
TX = 3  # Number of transmit antennas
CARRIER_FREQ = 77e9
SPEED_OF_LIGHT = 3e8
LAMBDA = SPEED_OF_LIGHT / CARRIER_FREQ


def build_virtual_array(num_tx, sample_rd):
    """
    Build virtual array from MIMO radar data.

    Args:
        num_tx: Number of transmit channels
        sample_rd: Complex MIMO channel response [num_rx, num_tx]

    Returns:
        Virtual array vector (flattened)
    """
    # Flatten the MIMO array into a virtual array
    # Typical arrangement: concatenate RX responses for each TX
    virtual_array = sample_rd.flatten()
    return virtual_array


def angle_fft(
    cfar_detections,
    clean_rdmap,
    zero_pad_cols=124,
    num_tx_channels=TX,
    num_rx_channels=RX,
    device="cpu",
):
    """
    Estimate angle-of-arrival for CFAR detections using FFT-based beamforming.

    This function implements DoA estimation similar to MATLAB code:
    - Extracts virtual array response for each detection
    - Applies zero-padding for angular super-resolution
    - Uses FFT to estimate arrival angle

    Args:
        cfar_detections: Binary detection map [num_doppler, num_range]
        clean_rdmap: Clean range-Doppler map with MIMO data
                     Expected shape: [num_doppler, num_rx, num_tx, num_range]
                     or [num_doppler, num_range, num_rx, num_tx]
        zero_pad_cols: Number of zero columns to pad on each side (default: 124)
        num_tx_channels: Number of TX antennas (default: 3)
        num_rx_channels: Number of RX antennas (default: 4)
        device: Device to run on, 'cuda' or 'cpu' (default: 'cpu')

    Returns:
        angle_matrix: Angle estimates in degrees [num_doppler, num_range]
                     Zero where no detection
    """
    # Get dimensions
    num_doppler, num_range = cfar_detections.shape

    # Initialize angle matrix
    angle_matrix = np.zeros((num_doppler, num_range), dtype=np.float32)

    # Create angle range (sin space from -1 to 1)
    angle_range = np.linspace(-1, 1, 2 * zero_pad_cols + 8)

    # Find detections
    detections = np.argwhere(cfar_detections > 0)

    if len(detections) == 0:
        return angle_matrix

    # Convert to torch if using GPU
    angle_range_torch = torch.from_numpy(angle_range).to(device)

    for detection in detections:
        doppler_bin, range_bin = detection

        # Extract MIMO sample for this range-Doppler bin
        # Assuming clean_rdmap has shape [doppler, rx, tx, range]
        if clean_rdmap.ndim == 4:
            if clean_rdmap.shape == (
                num_doppler,
                num_rx_channels,
                num_tx_channels,
                num_range,
            ):
                sample_rd = clean_rdmap[doppler_bin, :, :, range_bin]
            elif clean_rdmap.shape == (
                num_doppler,
                num_range,
                num_rx_channels,
                num_tx_channels,
            ):
                sample_rd = clean_rdmap[doppler_bin, range_bin, :, :]
            else:
                raise ValueError(f"Unexpected clean_rdmap shape: {clean_rdmap.shape}")
        else:
            raise ValueError(f"Expected 4D clean_rdmap, got shape: {clean_rdmap.shape}")

        # Build virtual array
        virtual_array = build_virtual_array(num_tx_channels, sample_rd)

        # Add zero padding on both sides
        zeros = np.zeros(zero_pad_cols, dtype=virtual_array.dtype)
        virtual_array_padded = np.concatenate([virtual_array, zeros, zeros])

        # Perform FFT on the virtual array
        nfft_ang = len(virtual_array_padded)

        va_torch = torch.from_numpy(virtual_array_padded).to(device)
        angle_fft_result = torch.fft.fftshift(torch.fft.fft(va_torch, n=nfft_ang))
        angle_fft_mag = torch.abs(angle_fft_result)
        max_idx = torch.argmax(angle_fft_mag).item()
        ang_val = angle_range_torch[max_idx].item()
        # Convert from sin(theta) to theta in degrees
        # Clamp to [-1, 1] to avoid numerical issues with arcsin
        ang_val = np.clip(ang_val, -1.0, 1.0)
        angle_deg = np.rad2deg(np.arcsin(ang_val))

        # Store angle estimate
        angle_matrix[doppler_bin, range_bin] = angle_deg

    return angle_matrix


def angle_fft_simple(
    cfar_detections,
    rdmap_2d,
    zero_pad_cols=124,
    device="cpu",
):
    """
    Simplified angle estimation for 2D range-Doppler map (no MIMO data).

    This is a placeholder that uses the range profile as a proxy for angular FFT.
    For true angle estimation, you need the full MIMO channel data.

    Args:
        cfar_detections: Binary detection map [num_doppler, num_range]
        rdmap_2d: 2D range-Doppler map [num_doppler, num_range]
        zero_pad_cols: Number of zero columns to pad on each side (default: 124)
        device: Device to run on, 'cuda' or 'cpu' (default: 'cpu')

    Returns:
        angle_matrix: Placeholder angle estimates [num_doppler, num_range]
    """
    # Get dimensions
    num_doppler, num_range = cfar_detections.shape

    # Initialize angle matrix
    angle_matrix = np.zeros((num_doppler, num_range), dtype=np.float32)

    # Without MIMO data, we can't perform true angle estimation
    # This is a placeholder that returns zeros
    # In a real system, you would need access to the raw MIMO channel data

    return angle_matrix


def angle_music(
    cfar_detections,
    clean_rdmap,
    num_sources=1,
    num_tx_channels=TX,
    num_rx_channels=RX,
    device="cpu",
):
    """
    MUSIC (Multiple Signal Classification) algorithm for angle estimation.

    More sophisticated than FFT-based method, can resolve multiple sources.

    Args:
        cfar_detections: Binary detection map [num_doppler, num_range]
        clean_rdmap: Clean range-Doppler map with MIMO data
        num_sources: Expected number of signal sources (default: 1)
        num_tx_channels: Number of TX antennas (default: 3)
        num_rx_channels: Number of RX antennas (default: 4)
        device: Device to run on, 'cuda' or 'cpu' (default: 'cpu')

    Returns:
        angle_matrix: Angle estimates in degrees [num_doppler, num_range]
    """
    # Get dimensions
    num_doppler, num_range = cfar_detections.shape
    num_virtual = num_tx_channels * num_rx_channels

    # Initialize angle matrix
    angle_matrix = np.zeros((num_doppler, num_range), dtype=np.float32)

    # Angle search space
    angle_search = np.linspace(-90, 90, 181)  # -90 to 90 degrees

    # Find detections
    detections = np.argwhere(cfar_detections > 0)

    if len(detections) == 0:
        return angle_matrix

    for detection in detections:
        doppler_bin, range_bin = detection

        # Extract MIMO sample
        if clean_rdmap.ndim == 4:
            if clean_rdmap.shape == (
                num_doppler,
                num_rx_channels,
                num_tx_channels,
                num_range,
            ):
                sample_rd = clean_rdmap[doppler_bin, :, :, range_bin]
            elif clean_rdmap.shape == (
                num_doppler,
                num_range,
                num_rx_channels,
                num_tx_channels,
            ):
                sample_rd = clean_rdmap[doppler_bin, range_bin, :, :]
            else:
                continue
        else:
            continue

        # Build virtual array
        virtual_array = build_virtual_array(num_tx_channels, sample_rd)

        # Compute covariance matrix
        R = np.outer(virtual_array, np.conj(virtual_array))

        # Eigendecomposition
        eigenvalues, eigenvectors = np.linalg.eigh(R)

        # Sort eigenvalues in descending order
        idx = eigenvalues.argsort()[::-1]
        eigenvalues = eigenvalues[idx]
        eigenvectors = eigenvectors[:, idx]

        # Noise subspace (all eigenvectors except first num_sources)
        noise_subspace = eigenvectors[:, num_sources:]

        # MUSIC spectrum
        music_spectrum = []
        for angle_deg in angle_search:
            # Steering vector
            angle_rad = np.deg2rad(angle_deg)
            k = 2 * np.pi / LAMBDA
            # Simplified steering vector (assumes linear array)
            a = np.exp(
                -1j * k * np.arange(num_virtual) * np.sin(angle_rad) * LAMBDA / 2
            )

            # MUSIC pseudo-spectrum
            denominator = np.abs(
                np.dot(
                    np.conj(a).T, np.dot(noise_subspace, np.conj(noise_subspace).T)
                ).dot(a)
            )
            music_spectrum.append(1.0 / (denominator + 1e-10))

        # Find peak
        max_idx = np.argmax(music_spectrum)
        angle_matrix[doppler_bin, range_bin] = angle_search[max_idx]

    return angle_matrix
