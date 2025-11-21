// g++ -std=c++11 -Wall -Wextra -pedantic -lfftw3f -lm -I../../src/ -o test test.cpp `pkg-config --cflags --libs opencv4`; ./test 
#include "../src/rpl/private-header.hpp"
#define INPUT_SIZE 64 * 512
#define OUTPUT_SIZE 0
int main(int argc, char* argv[])
{   

    // CONSTRUCTOR INITIATION
    DataAcquisition daq;
    RangeDoppler rdm("blackman");
    Visualizer vis(INPUT_SIZE,OUTPUT_SIZE);
    JSON_TCP tcp;  // For saving data and running calibration

    // BUFFER POINTER INITIATION
    uint16_t *in_bufferptr    = daq.getBufferPointer();
    float    *in_visualizeptr = rdm.getBufferPointer();
    float    *ang_visualizeptr = rdm.getAngleBufferPointer();
    int      *angidx_visptr = rdm.getAngleIndexPointer();
    float    *range_visualizeptr = rdm.getRangeBufferPointer();
    float    *angleMap_ptr = rdm.getAngleMapPointer();
    
    rdm.setBufferPointer(in_bufferptr);
    vis.setBufferPointer(in_visualizeptr);
    vis.setAngleBufferPointer(ang_visualizeptr);
    vis.setAngleIndexPointer(angidx_visptr);
    vis.setRangeBufferPointer(range_visualizeptr);
    vis.setAngleMapPointer(angleMap_ptr);

    // FRAME POINTER INITIATION
    auto frame_daq = daq.getFramePointer();
    rdm.setFramePointer(frame_daq);
    auto frame_rdm = rdm.getFramePointer();
    daq.setFramePointer(frame_rdm);
    
    // OTHER PARAMS
    int num_frames = 100;  // Collect 100 frames for calibration
    if (argc > 1){
        if(argc == 2){
            num_frames = std::stoi(argv[1]);
        } else if(argc == 3){
            float max = std::stof(argv[1]);
            float min = std::stof(argv[2]);
            rdm.setSNR(max,min);
        } else {
            std::cout << "Usage:\n";
            std::cout << "  ./test                    (100 frames, default SNR)\n";
            std::cout << "  ./test <num_frames>       (custom frame count)\n";
            std::cout << "  ./test <max_SNR> <min_SNR>\n";
            return 1;
        }
    }
    vis.setWaitTime(1);   

    rdm.process();
    
    std::cout << "\n=== Starting Data Collection ===\n";
    std::cout << "Collecting " << num_frames << " frames...\n\n";
    
    for(int i = 0; i < num_frames; i++){
        auto start = std::chrono::high_resolution_clock::now();
        
        daq.process();
        rdm.process();
        vis.process();
        
        // Get angle and range for this frame
        float angle = *ang_visualizeptr;
        float range = *range_visualizeptr;
        
        // Save data
        tcp.process(angle, range, start);
        
        std::cout << "Frame " << (i+1) << "/" << num_frames 
                  << " - Angle: " << angle << "°, Range: " << range << "m\n";
    }
    
    tcp.end_stream();
    
    std::cout << "\n=== Data Collection Complete ===\n";
    std::cout << "Running calibration...\n\n";
    
    tcp.run_calibration();

    return 0;
}
