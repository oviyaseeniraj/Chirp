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

// struct shareMem{
//     float frame[SLOW_TIME * FAST_TIME];
// };

struct shareMem{
    uint16_t frame[SIZE_W_IQ];
};



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

    rdm.process();

    int i = 0;
    while(true){
        daq.process();
        std::cout << "Frame " << i << std::endl;
        int val;
        sem_getvalue(sem_empty, &val);
        printf("sem_empty value = %d\n", val);
        sem_wait(sem_empty);
        std::cout << "copying data" << std::endl;
        // memcpy(shm->frame, rdm.getRDMDataPointer(), sizeof(float) * SLOW_TIME * FAST_TIME);
        memcpy(shm->frame, in_bufferptr, sizeof(uint16_t) * SIZE_W_IQ);
        sem_post(sem_full);
        i++;
    }

    cleanup_resources();
    return 0;
}
