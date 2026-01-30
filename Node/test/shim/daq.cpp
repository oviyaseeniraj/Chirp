#include <iostream>
#include <cstring>
#include <chrono>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <cstdint>

// Constants from main.h
#define FAST_TIME 512
#define SLOW_TIME 64
#define RX 4
#define TX 3
#define IQ 2
#define IQ_BYTES 2
#define SIZE_W_IQ (TX * RX * FAST_TIME * SLOW_TIME * IQ)

#define BUFFER_SIZE 2048
#define PORT 4098
#define BYTES_IN_PACKET 1456

class DataAcquisition {
private:
    int sockfd;
    struct sockaddr_in servaddr, cliaddr;
    socklen_t len;

    char *buffer;
    uint16_t *frame_data;

    uint64_t BYTES_IN_FRAME;
    uint64_t BYTES_IN_FRAME_CLIPPED;
    uint64_t UINT16_IN_PACKET;
    uint32_t packets_read;

    int frame;

public:
    DataAcquisition() : frame(0), packets_read(0) {
        // Allocate buffers
        frame_data = (uint16_t *)malloc(SIZE_W_IQ * sizeof(uint16_t));
        buffer = (char *)malloc(BUFFER_SIZE * sizeof(char));

        // Calculate sizes
        BYTES_IN_FRAME = SLOW_TIME * FAST_TIME * RX * TX * IQ * IQ_BYTES;
        BYTES_IN_FRAME_CLIPPED = (BYTES_IN_FRAME / BYTES_IN_PACKET) * BYTES_IN_PACKET;
        UINT16_IN_PACKET = BYTES_IN_PACKET / 2;

        len = sizeof(cliaddr);
        sockfd = -1;
    }

    ~DataAcquisition() {
        free(frame_data);
        free(buffer);
        if (sockfd >= 0) {
            close(sockfd);
        }
    }

    int create_bind_socket() {
        if ((sockfd = socket(AF_INET, SOCK_DGRAM, 0)) < 0) {
            perror("Socket creation failed");
            exit(EXIT_FAILURE);
        }

        memset(&servaddr, 0, sizeof(servaddr));
        memset(&cliaddr, 0, sizeof(cliaddr));

        servaddr.sin_family = AF_INET;
        servaddr.sin_addr.s_addr = htonl(INADDR_ANY);
        servaddr.sin_port = htons(PORT);

        bind(sockfd, (struct sockaddr *)&servaddr, sizeof(servaddr));
        return 0;
    }

    void close_socket() {
        close(sockfd);
        sockfd = -1;
    }

    void read_socket() {
        int n = recvfrom(sockfd, buffer, BUFFER_SIZE, 0, (struct sockaddr *)&cliaddr, &len);
        buffer[n] = '\0';
    }

    void set_frame_data() {
        for (uint64_t i = UINT16_IN_PACKET * packets_read; i < (UINT16_IN_PACKET * (packets_read + 1)); i++) {
            frame_data[i] = buffer[2 * (i - UINT16_IN_PACKET * packets_read) + 10] |
                           (buffer[2 * (i - UINT16_IN_PACKET * packets_read) + 11] << 8);
        }
        packets_read++;
    }

    int end_of_frame() {
        uint64_t byte_mod = (packets_read * BYTES_IN_PACKET) % BYTES_IN_FRAME_CLIPPED;
        return (byte_mod == 0) ? 1 : 0;
    }

    uint16_t* process() {
        auto start = std::chrono::high_resolution_clock::now();

        create_bind_socket();

        while (true) {
            read_socket();
            set_frame_data();

            if (end_of_frame() == 1) {
                packets_read = 0;
                close_socket();
                break;
            }
        }

        auto stop = std::chrono::high_resolution_clock::now();
        auto duration = std::chrono::duration_cast<std::chrono::microseconds>(stop - start);

        std::cout << "Frame " << frame << ": " << duration.count() << " μs" << std::endl;

        frame++;

        return frame_data;
    }

    int get_frame_count() const {
        return frame;
    }
};

int main() {
    std::cout << "C++ Data Acquisition (Matching Original Implementation)" << std::endl;
    std::cout << "Port: " << PORT << ", Config: " << FAST_TIME << "x" << SLOW_TIME
              << ", " << RX << "RX x " << TX << "TX" << std::endl;

    DataAcquisition daq;

    while (true) {
        uint16_t* frame_data = daq.process();

        // Process frame_data here...
    }

    return 0;
}
