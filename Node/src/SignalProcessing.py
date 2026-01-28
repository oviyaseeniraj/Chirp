import numpy as np
from scipy.fft import fft, fft2, fftshift

# Constants (matching main.h and DataAcquisition.py)
FAST_TIME = 512
SLOW_TIME = 64
RX = 4
TX = 3
IQ = 2

def reshape_cube(data):
    """
    Reshapes the flat binary data into a radar cube.
    Input format: [Chirp Loop][TX][Sample #][IQ][RX]
    Target format: [TX][RX][Chirp Loop][Sample #][IQ]
    
    Dimensions:
    Chirp Loop (SLOW_TIME) = 64
    TX = 3
    Sample # (FAST_TIME) = 512
    IQ = 2
    RX = 4
    """
    # Convert to numpy array if it's not already
    data = np.asarray(data, dtype=np.int16)
    
    # Initial reshape to the captured format
    # [SLOW_TIME, TX, FAST_TIME, IQ, RX]
    cube = data.reshape((SLOW_TIME, TX, FAST_TIME, IQ, RX))
    
    # Transpose to target format: [TX, RX, SLOW_TIME, FAST_TIME, IQ]
    # Original axes: 0=SLOW_TIME, 1=TX, 2=FAST_TIME, 3=IQ, 4=RX
    # Target axes: 1=TX, 4=RX, 0=SLOW_TIME, 2=FAST_TIME, 3=IQ
    cube_reshaped = cube.transpose((1, 4, 0, 2, 3))
    
    return cube_reshaped

def radar_cube_to_rdm(radar_cube):
    """
    Converts the radar cube into a range-doppler map using 2D FFT.
    Input: radar_cube of shape (TX, RX, SLOW_TIME, FAST_TIME, IQ)
    Output: RDM of shape (TX, RX, SLOW_TIME, FAST_TIME)
    """
    # Combine I and Q into complex numbers
    # radar_cube[..., 0] is I, radar_cube[..., 1] is Q
    cube_complex = radar_cube[..., 0] + 1j * radar_cube[..., 1]
    
    # Apply Range-FFT (across FAST_TIME dimension)
    # Range is usually the last dimension here
    # We apply windowing to reduce sidelobes
    range_window = np.hanning(FAST_TIME)
    cube_complex_windowed = cube_complex * range_window
    
    range_fft = fft(cube_complex_windowed, axis=-1)
    
    # Apply Doppler-FFT (across SLOW_TIME dimension)
    doppler_window = np.hanning(SLOW_TIME)
    # Need to broadcast doppler_window to (TX, RX, SLOW_TIME, FAST_TIME)
    # SLOW_TIME is axis 2
    doppler_window = doppler_window.reshape((1, 1, SLOW_TIME, 1))
    range_fft_windowed = range_fft * doppler_window
    
    rdm = fft(range_fft_windowed, axis=2)
    
    # Shift doppler axis to center zero velocity
    rdm = fftshift(rdm, axes=2)
    
    return rdm

def CFAR_rdm(rdm, guard_cells=(2, 2), training_cells=(8, 8), threshold_factor=10.0):
    """
    Implements 2D Cell-Averaging CFAR (CA-CFAR) on a Range-Doppler Map.
    Input: rdm (complex or magnitude)
    Output: mask (boolean array of detected targets)
    """
    # Work with magnitude squared (power)
    rdm_power = np.abs(rdm)**2
    
    # We take the average across all TX/RX channels for detection if they exist
    if rdm_power.ndim == 4:
        rdm_power = np.mean(rdm_power, axis=(0, 1))
    
    rows, cols = rdm_power.shape
    g_r, g_c = guard_cells
    t_r, t_c = training_cells
    
    mask = np.zeros_like(rdm_power, dtype=bool)
    
    # Total window size
    w_r = g_r + t_r
    w_c = g_c + t_c
    
    # Precompute the number of training cells
    num_training_cells = (2*w_r + 1) * (2*w_c + 1) - (2*g_r + 1) * (2*g_c + 1)
    
    # Slide across the RDM (ignoring edges for simplicity)
    for r in range(w_r, rows - w_r):
        for c in range(w_c, cols - w_c):
            # Training window
            window = rdm_power[r-w_r : r+w_r+1, c-w_c : c+w_c+1]
            
            # Sum all cells in window
            total_sum = np.sum(window)
            
            # Subtract the guard + CUT area
            guard_area = rdm_power[r-g_r : r+g_r+1, c-g_c : c+g_c+1]
            training_sum = total_sum - np.sum(guard_area)
            
            # Average noise level
            noise_level = training_sum / num_training_cells
            
            # Thresholding
            if rdm_power[r, c] > noise_level * threshold_factor:
                mask[r, c] = True
                
    return mask
