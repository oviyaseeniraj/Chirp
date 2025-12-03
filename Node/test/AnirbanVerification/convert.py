
import numpy as np
from scipy.io import loadmat
import sys
import h5py

# =============Configuration ======================

mat_filename = "apr0325_expc1_left_Raw_0_noRangeFT.mat"        # path to .mat file
#mat_filename = "apr0325_expc1_right_Raw_0_noRangeFT.mat"        # path to .mat file

var_name     = "Data_PostBPM_noFFT"             # variable to load from the MAT file
output_name = "./outputdata/DAQ2"       # output path/filename (don't include .txt suffix)

#Each frame in the .mat file is written to its own txt file
#EXAMPLE: output txt filename: #{output_name}_frame_{frame}.txt"

#=============== CONVERSION =======================
#Frame * chirp # * RX * TX * SAMPLE * IQ - anirban's format
#To 
#Frame*[Chirp Loop][TX][Sample #][IQ][RX] - fusionsense's format
#def convert_py(input_filename, output_file, frame_data_name):
# Load MAT file

cube = None
with h5py.File(mat_filename, 'r') as f:
    if var_name not in f:
        raise ValueError(f"Variable '{var_name}' not found in MAT file.")
    cube = f[var_name][()]
    print("Loaded:", var_name, "shape =", cube.shape)

for frame in range(0,cube.shape[4],60):
    #try doing only the first frame for now
    
    print(f"Writing Frame {frame} ================")
    with open(f"{output_name}_frame_{frame}.txt",'w') as out:
        lines = 0
        for chirp in range(cube.shape[3]):
            for tx in range(cube.shape[1]):
                for sample in range(cube.shape[0]):
                    data = cube[sample,tx,:,chirp,frame] #across all rx

                    reals = [num[0] for num in data]
                    imags = [num[1] for num in data]
                    iq_arr = np.stack([reals, imags], axis=1)

                    flat_arr = iq_arr.flatten().astype(np.uint16)
                    
                    out.writelines(f"{v}\n" for v in flat_arr)
                    lines+=len(flat_arr)
    print(f"Wrote {lines} lines")
    print(f"Finished writing to {output_name}_frame_{frame}.txt")


