#include "DataAcquisition.h"
#include "RangeDoppler.h"
#include <iostream>

int main(int argc, char const *argv[])
{
    DataAcquisition daq;

    RangeDoppler rdm("blackman");

    uint16_t *in_bufferptr    = daq.getBufferPointer();
    float    *in_visualizeptr = rdm.getBufferPointer();
    float    *ang_visualizeptr = rdm.getAngleBufferPointer();
    int      *angidx_visptr = rdm.getAngleIndexPointer();
    float    *range_visualizeptr = rdm.getRangeBufferPointer();

    rdm.setBufferPointer(in_bufferptr);

    // FRAME POINTER INITIATION
    auto frame_daq = daq.getFramePointer();
    rdm.setFramePointer(frame_daq);
    auto frame_rdm = rdm.getFramePointer();
    daq.setFramePointer(frame_rdm);

    // OTHER PARAMS
    if (argc > 1){
        if(argc != 3){
            std::cout << "Incorrect number of arguments, format should be : \n    --> ./test max_SNR_THRESHOLD min_SNR_THRESHOLD \n OR --> ./test" << std::endl;
            return 1;
        }
        float max = std::stof(argv[1]);
        float min = std::stof(argv[2]);
        rdm.setSNR(max,min);
    }

    rdm.process();

    int i = 0;
    while(true){
        daq.process();
        rdm.process();
        std::cout << "Frame " << i << " Range: " << *range_visualizeptr << std::endl;
        std::cout << "Frame " << i << "Angle: " << *ang_visualizeptr << std::endl;
        i++;
    }
    return 0;
}
