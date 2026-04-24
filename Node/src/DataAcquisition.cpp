#include "DataAcquisition.h"
#include "RadarBlock.h"
#include "main.h"
#include <sys/socket.h>

DataAcquisition::DataAcquisition() : RadarBlock(SIZE, SIZE) {
    frame_data = reinterpret_cast<uint16_t *>(malloc(SIZE_W_IQ * sizeof(uint16_t)));
    BYTES_IN_FRAME = SLOW_TIME * FAST_TIME * RX * TX * IQ * IQ_BYTES;
    BYTES_IN_FRAME_CLIPPED = BYTES_IN_FRAME / BYTES_IN_PACKET * BYTES_IN_PACKET;
    PACKETS_IN_FRAME_CLIPPED = BYTES_IN_FRAME / BYTES_IN_PACKET;
    UINT16_IN_PACKET = BYTES_IN_PACKET / 2; // 728 entries in packet
    UINT16_IN_FRAME = BYTES_IN_FRAME / 2;
    packets_read = 0;
    buffer = reinterpret_cast<char *>(malloc(BUFFER_SIZE * sizeof(char)));
    packet_data = reinterpret_cast<uint16_t *>(malloc(UINT16_IN_PACKET * sizeof(uint16_t)));
}

// create_bind_socket - returns a socket object titled sockfd
int DataAcquisition::DataAcquisition::create_bind_socket()
{
    // Create a UDP socket file descriptor which is UNbounded
    if ((sockfd = socket(AF_INET, SOCK_DGRAM, 0)) < 0)
    {
        perror("Socket creation failed");
        exit(EXIT_FAILURE);
    }

    memset(&servaddr, 0, sizeof(servaddr));
    memset(&cliaddr, 0, sizeof(cliaddr));

    // Filling in the servers (DCA1000EVMs) information
    servaddr.sin_family = AF_INET;         // sets address family to internet 
    servaddr.sin_addr.s_addr = INADDR_ANY; // sets server address to IP address of host
    servaddr.sin_port = htons(PORT);       // port number to accept from, change from little to big endian to fit network byte order

    // Now we bind the socket with the servers (DCA1000EVMs) address
    // if (bind(sockfd, (const struct sockaddr *)&servaddr, sizeof(servaddr)) < 0)

    // Bind the socket to any available IP address and a specific port
    bzero(&servaddr, sizeof(servaddr));
    servaddr.sin_family = AF_INET;
    servaddr.sin_addr.s_addr = htonl(INADDR_ANY);
    servaddr.sin_port = htons(PORT);
    bind(sockfd, (struct sockaddr *)&servaddr, sizeof(servaddr));
    // std::cout << "Socket Binded Success!" << std::endl;
    return 0;
}

void DataAcquisition::close_socket()
{
    close(sockfd);
}

// read_socket will generate the buffer object that holds all raw ADC data
void DataAcquisition::read_socket()
{
    auto start = std::chrono::high_resolution_clock::now();
    // n is the packet size in bytes (including sequence number and byte count)

    n = recvfrom(sockfd, buffer, BUFFER_SIZE, 0, (struct sockaddr *)&cliaddr, &len);
    buffer[n] = '\0'; // Null-terminate the buffer
    // auto stop = std::chrono::high_resolution_clock::now();
    // auto duration_read_socket = duration_cast<microseconds>(stop - start);
    // std::cout << "Read Socket " << duration_read_socket.count() << std::endl;

    // start = std::chrono::high_resolution_clock::now();

    // stop = std::chrono::high_resolution_clock::now();
    // auto duration_set_packet_data = duration_cast<microseconds>(stop - start);
    // std::cout << "Set Packet Data " << duration_set_packet_data.count() << std::endl;
}

// get_packet_num will look at the buffer and return the packet number
uint32_t DataAcquisition::get_packet_num()
{
    uint32_t packet_number = ((buffer[0] & 0xFF) << 0) |
                                ((buffer[1] & 0xFF) << 8) |
                                ((buffer[2] & 0xFF) << 16) |
                                ((long)(buffer[3] & 0xFF) << 24);
    return packet_number;
}
// get_byte_count will look at the buffer and return the byte count of the packet
uint64_t DataAcquisition::get_byte_count()
{
    uint64_t byte_count = ((buffer[4] & 0xFF) << 0) |
                            ((buffer[5] & 0xFF) << 8) |
                            ((buffer[6] & 0xFF) << 16) |
                            ((buffer[7] & 0xFF) << 24) |
                            ((unsigned long long)(buffer[8] & 0xFF) << 32) |
                            ((unsigned long long)(buffer[9] & 0xFF) << 40) |
                            ((unsigned long long)(0x00) << 48) |
                            ((unsigned long long)(0x00) << 54);
    return byte_count;
}

/*void set_packet_data(){
    // printf("Size of packet data = %d \n", BYTES_IN_PACKET);
    for (int i = 0; i< UINT16_IN_PACKET; i++)
    {
        packet_data[i] =  buffer[2*i+10] | (buffer[2*i+11] << 8);
    }
}*/

void DataAcquisition::set_frame_data()
{
    // Add packet_data to frame_data
    for (int i = UINT16_IN_PACKET * packets_read; i < (UINT16_IN_PACKET * (packets_read + 1)); i++)
    {
        frame_data[i] = buffer[2 * (i - UINT16_IN_PACKET * packets_read) + 10] | (buffer[2 * (i - UINT16_IN_PACKET * packets_read) + 11] << 8);
        // frame_data[i] = packet_data[i%UINT16_IN_PACKET];
    }
    packets_read++;
}

int DataAcquisition::end_of_frame()
{
    uint64_t byte_mod = (packets_read * BYTES_IN_PACKET) % BYTES_IN_FRAME_CLIPPED;
    if (byte_mod == 0) // end of frame found
        return 1;
    return 0;
}

int DataAcquisition::save_1d_array(uint16_t *arr, int width, int length, std::string &filename)
{
    std::ofstream outfile(filename);
    for (int i = 0; i < length * width; i++)
    {
        outfile << arr[i] << std::endl;
    }

    // outfile.close();
    std::cout << "Array saved to file. " << std::endl;
    return 0;
}

uint16_t *DataAcquisition::getBufferPointer()
{
    return frame_data;
}

void DataAcquisition::listen()
{
    for (;;)
    {
        if (frame == 0)
        {
            break;
        }
        if (*inputframeptr != lastframe)
        {
            lastframe = *inputframeptr;
            break;
        }
    }
}

void DataAcquisition::process()
{

    auto start = std::chrono::high_resolution_clock::now();

    create_bind_socket();

    // while true loop to get a single frame of data from UDP
    // std::cout<< "DAQ PROCESS ACTIVATED" << std::endl;
    // std::cout << "FRAME #: " << frame << "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~" << std::endl;
    // start = std::chrono::high_resolution_clock::now();
    while (true)
    {
        read_socket();
        // start = chrono::high_resolution_clock::now();
        set_frame_data();
        // stop = chrono::high_resolution_clock::now();
        // duration_set_frame_data = duration_cast<microseconds>(stop - start);
        // std::cout << "Set Frame Data " << duration_set_frame_data.count() << std::endl;
        // std::cout << std::endl;

        if (end_of_frame() == 1)
        {
            // string str = ("./out") + to_string(frame) + ".txt";
            //  save_1d_array(frame_data, FAST_TIME*TX*RX*IQ_DATA, SLOW_TIME, str);
            packets_read = 0;
            // first_packet = true;
            // start = chrono::high_resolution_clock::now();

            close_socket();
            // stop = chrono::high_resolution_clock::now();
            // auto duration_close_socket = duration_cast<microseconds>(stop - start);

            break;
        }
    }
    // auto stop = chrono::high_resolution_clock::now();
    // auto duration = duration_cast<microseconds>(stop - start);
    // std::cout << "Create Socket " << duration_create_socket.count() << std::endl;
    // std::cout << std::endl;
    //  auto stop = chrono::high_resolution_clock::now();
    //  auto duration = duration_cast<microseconds>(stop - start);
    //  std::cout << "Process Time " << duration.count() << std::endl;
    //  std::cout << std::endl;
    auto stop = std::chrono::high_resolution_clock::now();
    auto duration_daq_process = std::chrono::duration_cast<std::chrono::microseconds>(stop - start);
    std::cout << "DAQ Process Time " << duration_daq_process.count() << " microseconds" << std::endl;
    std::cout << "~~~~~~~~~~~~~~~~~~~END OF SINGLE FRAME~~~~~~~~~~~~~~~~~~~~" << std::endl;
}