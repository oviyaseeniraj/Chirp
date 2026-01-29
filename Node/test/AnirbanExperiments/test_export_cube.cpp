// g++ -std=c++11 -Wall -Wextra -pedantic -lfftw3f -lm -I../../src/ -o test test.cpp `pkg-config --cflags --libs opencv4`; ./test 
#include "DataAcquisition.h"
#include "RangeDoppler.h"
#include "Visualizer.h"
#include "JSONTCP.h"

#define INPUT_SIZE 64 * 512
#define OUTPUT_SIZE 0
int main(int argc, char* argv[])
{   
    // Parse node name from command line (default: "Node")
    std::string node_name = "Node";
    int num_frames = 100;
    
    // CONSTRUCTOR INITIATION
    DataAcquisition daq;
    RangeDoppler rdm("");

    // BUFFER POINTER INITIATION
    uint16_t *in_bufferptr    = daq.getBufferPointer();
    float    *in_visualizeptr = rdm.getBufferPointer();
    float    *ang_visualizeptr = rdm.getAngleBufferPointer();
    int      *angidx_visptr = rdm.getAngleIndexPointer();
    float    *range_visualizeptr = rdm.getRangeBufferPointer();
    float    *angleMap_ptr = rdm.getAngleMapPointer();
    float    *doppler_visualizeptr = rdm.getDopplerBufferPointer();  // Doppler velocity in m/s
    int      *doppler_bin_ptr = rdm.getDopplerBinPointer();  // Raw doppler bin
    float    *rdm_data_ptr = rdm.getRDMDataPointer();  // Full RDM data for plotting
    
    rdm.setBufferPointer(in_bufferptr);

    // FRAME POINTER INITIATION
    auto frame_daq = daq.getFramePointer();
    rdm.setFramePointer(frame_daq);
    auto frame_rdm = rdm.getFramePointer();
    daq.setFramePointer(frame_rdm);
    
    // PARSE COMMAND LINE ARGUMENTS
    // Usage: ./test [num_frames] [node_name]
    //    or: ./test [max_SNR] [min_SNR]
    if (argc >= 2) {
        // Check if first arg is a number (frames) or contains a decimal (SNR)
        std::string arg1 = argv[1];
        if (arg1.find('.') != std::string::npos) {
            // SNR mode: ./test max_SNR min_SNR
            if (argc == 3) {
                float max = std::stof(argv[1]);
                float min = std::stof(argv[2]);
                rdm.setSNR(max, min);
            } else {
                std::cout << "Usage:\n";
                std::cout << "  ./test                              (100 frames, default node)\n";
                std::cout << "  ./test <num_frames>                 (custom frames, default node)\n";
                std::cout << "  ./test <num_frames> <node_name>     (custom frames and node name)\n";
                std::cout << "  ./test <max_SNR> <min_SNR>          (SNR thresholds)\n";
                return 1;
            }
        } else {
            // Frame count mode
            num_frames = std::stoi(argv[1]);
            
            // Optional node name as second argument
            if (argc >= 3) {
                node_name = argv[2];
            }
        }
    }

    rdm.process();
    
    for(int i = 0; i < num_frames; i++){
        auto start = std::chrono::high_resolution_clock::now();
        
        daq.process();
        rdm.export_cube();
    }
    return 0;
}
