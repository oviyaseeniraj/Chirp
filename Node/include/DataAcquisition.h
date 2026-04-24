#ifndef DATA_ACQUISITION_H
#define DATA_ACQUISITION_H
#include "main.h"
#include "RadarBlock.h"

class DataAcquisition : public RadarBlock {
    public:
        DataAcquisition();

        // create_bind_socket - returns a socket object titled sockfd
        int create_bind_socket();

        void close_socket();

        // read_socket will generate the buffer object that holds all raw ADC data
        void read_socket();

        // get_packet_num will look at the buffer and return the packet number
        uint32_t get_packet_num();

        // get_byte_count will look at the buffer and return the byte count of the packet
        uint64_t get_byte_count();

        void set_frame_data();

        int end_of_frame();

        int save_1d_array(uint16_t *arr, int width, int length, std::string &filename);

        uint16_t* getBufferPointer();

        void listen() override;

        void process() override;

    private:
        int sockfd;                           // socket file descriptor
        struct sockaddr_in servaddr, cliaddr; // initialize socket
        socklen_t len;

        char *buffer;
        int n; // n is the packet size in bytes (including sequence number and byte count)

        uint16_t *packet_data, *frame_data;
        uint32_t packet_num;
        uint64_t BYTES_IN_FRAME, BYTES_IN_FRAME_CLIPPED, PACKETS_IN_FRAME_CLIPPED, UINT16_IN_PACKET, UINT16_IN_FRAME, packets_read;

        std::complex<float> *rdm_data, *adc_data;
        float *adc_data_flat, *rdm_avg, *rdm_norm, *adc_data_reshaped;
};

#endif