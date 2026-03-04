import numpy as np
from .. import config

def angle_cpu(
    cfar_detections,
    clean_rdmap,
    zero_pad_cols=124,
    device="cpu",  # Ignored, for compatibility
    **kwargs
):
    """
    Optimized FFT-based Angle Estimation using pure NumPy.
    
    Fully vectorized to eliminate the loop over detections. This provides 
    significant speedups on CPU/ARM-NEON.
    """
    num_doppler, num_range = cfar_detections.shape
    
    # 1. Get detection indices
    detections = np.argwhere(cfar_detections > 0)
    if len(detections) == 0:
        return np.zeros((num_doppler, num_range), dtype=np.float32)

    # 2. Extract MIMO data for all detections at once
    # clean_rdmap: [num_doppler, num_rx, num_tx, num_range]
    # We want TX index 1 for all RX antennas at detection points
    d_idx = detections[:, 0]
    r_idx = detections[:, 1]
    
    # Vectorized extraction: [N, num_rx]
    # Corresponding to sample_rd[:, 1] in the old loop
    va_data = clean_rdmap[d_idx, :, 1, r_idx]
    
    # 3. FFT Beamforming Setup
    nfft_ang = 256
    padded_size = 8 + 2 * zero_pad_cols
    
    # Construct batch for FFT
    # Shape: [num_detections, padded_size]
    # We follow the old logic of placing 4 elements into the middle of an 8-slot block
    # then padding with zeros.
    va_batch = np.zeros((len(detections), nfft_ang), dtype=np.complex64)
    va_batch[:, 4:8] = va_data
    
    # 4. Batch FFT
    # FFT along the antenna dimension (axis 1)
    # We use fftshift to put the zero-frequency (bore-sight) in the middle
    spectra = np.fft.fft(va_batch, n=nfft_ang, axis=1)
    spectra = np.fft.fftshift(spectra, axes=1)
    mag = np.abs(spectra)
    
    # 5. Peak Finding
    max_indices = np.argmax(mag, axis=1)
    
    # 6. Map to Angle
    # Vectorized mapping from bin index to degrees
    angle_range = np.linspace(-1, 1, nfft_ang)
    sin_vals = angle_range[max_indices]
    sin_vals = np.clip(sin_vals, -1.0, 1.0)
    angle_degs = np.rad2deg(np.arcsin(sin_vals))
    
    # 7. Scatter back to output matrix
    angle_matrix = np.zeros((num_doppler, num_range), dtype=np.float32)
    angle_matrix[d_idx, r_idx] = angle_degs
    
    return angle_matrix
