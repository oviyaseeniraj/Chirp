import numpy as np
import scipy.io as sio
import os
import subprocess

def test_bin_to_mat():
    # Parameters
    TX = 3
    RX = 4
    SLOW_TIME = 64
    FAST_TIME = 512
    IQ = 2
    NUM_FRAMES = 2
    
    # Create temp directory
    test_dir = 'temp_test_bins'
    os.makedirs(test_dir, exist_ok=True)
    
    # Generate mock data
    print("Generating mock binary files...")
    expected_frames = []
    for i in range(NUM_FRAMES):
        # Create a unique pattern for each frame
        # Shape: (TX, RX, SLOW_TIME, FAST_TIME, IQ)
        frame_data = np.random.rand(TX, RX, SLOW_TIME, FAST_TIME, IQ).astype(np.float32)
        file_path = os.path.join(test_dir, f'radar_cube_{i+1}.bin')
        frame_data.tofile(file_path)
        
        # Calculate expected complex, transposed shape for this frame
        complex_frame = frame_data[..., 0] + 1j * frame_data[..., 1]
        # Target: (SLOW, RX, TX, FAST) -> (2, 1, 0, 3)
        transposed_frame = complex_frame.transpose(2, 1, 0, 3)
        expected_frames.append(transposed_frame)
    
    expected_cube = np.stack(expected_frames, axis=0)
    
    # Run the script
    output_mat = 'test_output.mat'
    script_path = '/home/chirp/Chirp/Node/src/rpl/bin_to_mat.py'
    print(f"Running script: python3 {script_path} {test_dir} {output_mat}")
    subprocess.run(['python3', script_path, test_dir, output_mat], check=True)
    
    # Verify the output
    print("Verifying .mat file...")
    mat_contents = sio.loadmat(output_mat)
    if 'radar_cube' not in mat_contents:
        print("Error: 'radar_cube' not found in .mat file")
        return
        
    result_cube = mat_contents['radar_cube']
    
    print(f"Result shape: {result_cube.shape}")
    print(f"Expected shape: {expected_cube.shape}")
    
    if result_cube.shape != expected_cube.shape:
        print("Error: Shape mismatch!")
        return
        
    if np.allclose(result_cube, expected_cube):
        print("SUCCESS: Data matches expected result!")
    else:
        print("Error: Data values mismatch!")

    # Cleanup
    for i in range(NUM_FRAMES):
        os.remove(os.path.join(test_dir, f'radar_cube_{i+1}.bin'))
    os.rmdir(test_dir)
    os.remove(output_mat)

if __name__ == "__main__":
    test_bin_to_mat()
