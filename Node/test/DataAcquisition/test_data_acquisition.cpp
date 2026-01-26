#include "DataAcquisition.h"
#include "RangeDoppler.h"
#include <iostream>

int main(int argc, char const *argv[])
{
    DataAcquisition daq;

    // OTHER PARAMS

    int i = 0;
    
    daq.process();
    daq.save_1d_array(daq.getBufferPointer(),SIZE_W_IQ, 1, "data.txt");
    
    // std::cout << "Frame " << i << " Range: " << *range_visualizeptr << std::endl;
    // std::cout << "Frame " << i << " Angle: " << *ang_visualizeptr << std::endl;
    // i++;
    return 0;
}
