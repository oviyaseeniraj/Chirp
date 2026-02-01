#include "DataAcquisition.h"
#include "RangeDoppler.h"
#include <iostream>
#include <semaphore.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <cstring>

sem_t* sem_empty = sem_open("/frame_empty", O_CREAT, 0666, 1);
sem_t* sem_full  = sem_open("/frame_full",  O_CREAT, 0666, 0);

void cleanup_resources() {
    sem_close(sem_empty);
    sem_close(sem_full);
    sem_unlink("/frame_empty");
    sem_unlink("/frame_full");
    shm_unlink("/frame_shm");
}

struct shareMem{
    float frame[SLOW_TIME * FAST_TIME];
};

// struct shareMem{
//     uint16_t frame[SLOW_TIME * FAST_TIME * 3 * 2 * 4];
// };



int main(int argc, char const *argv[])
{
    DataAcquisition daq;

    RangeDoppler rdm("blackman");

    uint16_t *in_bufferptr    = daq.getBufferPointer();
    float    *in_visualizeptr = rdm.getBufferPointer();
    float    *ang_visualizeptr = rdm.getAngleBufferPointer();
    int      *angidx_visptr = rdm.getAngleIndexPointer();
    float    *range_visualizeptr = rdm.getRangeBufferPointer();

    int fd = shm_open("/frame_shm", O_CREAT | O_RDWR, 0666);
    ftruncate(fd, sizeof(shareMem));
    shareMem* shm = (shareMem*)mmap(NULL, sizeof(shareMem), PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);

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
            cleanup_resources();
            return 1;
        }
        float max = std::stof(argv[1]);
        float min = std::stof(argv[2]);
        rdm.setSNR(max,min);
    }

    // rdm.process();
    //
    // load the frame from frame.txt file
    // std::ifstream file("frame.txt");
    // if (!file.is_open()) {
    //     std::cerr << "Failed to open frame.txt" << std::endl;
    //     cleanup_resources();
    //     return 1;
    // }
    // for (int i = 0; i < SIZE_W_IQ; ++i) {
    //     file >> in_bufferptr[i];
    // }
    // file.close();

    //daq.process() and then store the output in a file as plaintext
    daq.process();
    std::ofstream daq_file("daq.txt");
    if (!daq_file.is_open()) {
        std::cerr << "Failed to open daq.txt" << std::endl;
        cleanup_resources();
        return 1;
    }
    for (int i = 0; i < 64 * 512 * 4 * 3 * 2; ++i) {
        daq_file << in_bufferptr[i] << "\n";
    }
    daq_file.close();

    // write the frame to rdm.txt
    rdm.process();
    std::ofstream rdm_file("rdm.txt");
    if (!rdm_file.is_open()) {
        std::cerr << "Failed to open rdm.txt" << std::endl;
        cleanup_resources();
        return 1;
    }
    for (int i = 0; i < 64 * 512; ++i) {
        rdm_file << rdm.getBufferPointer()[i] << "\n";
    }
    rdm_file.close();

    cleanup_resources();
    return 0;
}
