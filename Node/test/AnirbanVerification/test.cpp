// g++ -std=c++11 -Wall -Wextra -pedantic -lfftw3f -lm -I../../src/ -o test test.cpp `pkg-config --cflags --libs opencv4`; ./test 
#include "DataAcquisition.h"
#include "RangeDoppler.h"
#include "Visualizer.h"

//CONFIGURATION FOR Test Data input ====
#define INPUT_SIZE (60 * 512) //make sure these are correct or you get seg faults
#define INPUT_FRAMES 1
// =================================

#define FRAME_SIZE (INPUT_SIZE*3*4*2)
//used to hold adc data after reading from test file.
uint16_t input_buffer[ INPUT_FRAMES*FRAME_SIZE ];

#define OUTPUT_SIZE 0

int main(int argc, char* argv[])
{   

    RangeDoppler rdm("blackman");
    Visualizer vis(INPUT_SIZE,OUTPUT_SIZE);
    //std::string input_file("./output_DAQ2.txt");
    std::string input_file;

    if (argc > 1){
        if (argc == 2) {
            input_file.assign(argv[1]); //read input file name
        }
        else if(argc == 4){
            float max = std::stof(argv[2]);
            float min = std::stof(argv[3]);
            rdm.setSNR(max,min);
        }
    } else if (argc == 1) {
        input_file.assign("./output_DAQ2.txt");
    } else {
    std::cout << "Incorrect number of arguments, format should be : \n    --> ./test max_SNR_THRESHOLD min_SNR_THRESHOLD \n OR --> ./test" << std::endl;
    return 1;
    }

    std::ifstream file(input_file);

    if (file.is_open())
    {
        std::string line;

        int i = 0;
        while (std::getline(file, line))
        {
            if (i > SIZE_W_IQ)
            {
                std::cerr << "Error: More samples than SIZE " << input_file << std::endl;
                break;
            }
            float value = std::stof(line);
            input_buffer[i] = value;
            i++;
        }
        std::cout << "File Successfully read!" << std::endl;
        file.close();
    }
    else
    {
        std::cerr << "Error: Could not open file " << input_file << std::endl;
    }


    // BUFFER POINTER INITIATION
    uint16_t *in_bufferptr    = input_buffer;
    float    *in_visualizeptr = rdm.getBufferPointer();
    float    *ang_visualizeptr = rdm.getAngleBufferPointer();
    int      *angidx_visptr = rdm.getAngleIndexPointer();
    float    *range_visualizeptr = rdm.getRangeBufferPointer();
    // this isn't used in what appears to be thier most recent test
    // can add to RadarBlock if needed eventually 
    // float    *angleMap_ptr = rdm.getAngleMapPointer();
    
    rdm.setBufferPointer(in_bufferptr);
    vis.setBufferPointer(in_visualizeptr);
    vis.setAngleBufferPointer(ang_visualizeptr);
    vis.setAngleIndexPointer(angidx_visptr);
    vis.setRangeBufferPointer(range_visualizeptr);
    // this isn't used in what appears to be thier most recent test
    // vis.setAngleMapPointer(angleMap_ptr);

    // FRAME POINTER INITIATION
    //auto frame_daq = daq.getFramePointer();
    //rdm.setFramePointer(frame_daq);
    //auto frame_rdm = rdm.getFramePointer();
    //daq.setFramePointer(frame_rdm);
    // OTHER PARAMS
    
    vis.setWaitTime(1);   

    rdm.process();
    
    std::cout << "Processed first frame" << std::endl; 
    
    int i = 0;
    while(true){
        //daq.process();
        rdm.process();
        vis.process();

	    //i = (++i)%INPUT_FRAMES;
        std::cout << i << std::endl;
        //in_bufferptr = input_buffer+i*FRAME_SIZE; 
        rdm.setBufferPointer(in_bufferptr);
    }

    return 0;
}
