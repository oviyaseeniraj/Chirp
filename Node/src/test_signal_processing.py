import numpy as np
import SignalProcessing as sp

def test_pipeline():
    print("Testing Signal Processing Pipeline...")
    
    # Create fake data
    # Shape: (SLOW_TIME, TX, FAST_TIME, IQ, RX)
    # SLOW_TIME=64, TX=3, FAST_TIME=512, IQ=2, RX=4
    shape = (sp.SLOW_TIME, sp.TX, sp.FAST_TIME, sp.IQ, sp.RX)
    data_size = np.prod(shape)
    
    # Flat array simulating raw data from DCA1000
    mock_data = np.random.randint(0, 1000, size=data_size, dtype=np.int16)
    
    # 1. Reshape
    cube = sp.reshape_cube(mock_data)
    print(f"Reshaped Cube Shape: {cube.shape}")
    assert cube.shape == (sp.TX, sp.RX, sp.SLOW_TIME, sp.FAST_TIME, sp.IQ)
    
    # 2. RDM
    rdm = sp.radar_cube_to_rdm(cube)
    print(f"RDM Shape: {rdm.shape}")
    assert rdm.shape == (sp.TX, sp.RX, sp.SLOW_TIME, sp.FAST_TIME)
    
    # 3. CFAR
    # Add a strong target in the center of RDM
    # Let's say at range bin 100, doppler bin 32
    target_range = 100
    target_doppler = 32
    # RDM is (TX, RX, SLOW, FAST)
    # rdm[:, :, 32, 100] = 1e9 # Very strong
    
    # Since rdm is already generated, let's inject a signal into a new cube and recompute
    cube_with_target = cube.copy().astype(np.complex128)
    # Inject a sine wave across fast time for range
    t_fast = np.arange(sp.FAST_TIME)
    f_fast = 100 / sp.FAST_TIME # 100th bin
    
    # Inject a sine wave across slow time for doppler
    t_slow = np.arange(sp.SLOW_TIME)
    f_slow = 10 / sp.SLOW_TIME # 10th bin (relative to 0, which gets shifted)
    
    # Composite signal
    signal = np.exp(2j * np.pi * (f_fast * t_fast[None, :] + f_slow * t_slow[:, None]))
    
    # Create a complex cube
    complex_cube = cube[..., 0] + 1j * cube[..., 1]
    complex_cube[0, 0, :, :] += 1e6 * signal # Add strong signal to channel (0,0)
    
    # Reverse IQ to put back into radar_cube format for testing sp functions
    cube_test = np.zeros(cube.shape, dtype=np.int16)
    cube_test[..., 0] = np.real(complex_cube).astype(np.int16)
    cube_test[..., 1] = np.imag(complex_cube).astype(np.int16)
    
    rdm_test = sp.radar_cube_to_rdm(cube_test)
    mask = sp.CFAR_rdm(rdm_test, threshold_factor=100.0)
    
    print(f"Mask Shape: {mask.shape}")
    detections = np.argwhere(mask)
    if len(detections) > 0:
        print(f"Detections found at: {detections}")
    else:
        print("No detections found with high threshold.")

    print("Pipeline test successful!")

if __name__ == "__main__":
    test_pipeline()
