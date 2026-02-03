#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>

#include <cstring>
#include <cstdlib>
#include <iostream>
#include <vector>
#include <chrono>
#include <algorithm>

namespace py = pybind11;

// Branch prediction hints
#if defined(__GNUC__) || defined(__clang__)
    #define LIKELY(x)   __builtin_expect(!!(x), 1)
    #define UNLIKELY(x) __builtin_expect(!!(x), 0)
#else
    #define LIKELY(x)   (x)
    #define UNLIKELY(x) (x)
#endif

// Constants from main.h
constexpr int FAST_TIME = 512;
constexpr int SLOW_TIME = 64;
constexpr int RX = 4;
constexpr int TX = 3;
constexpr int IQ = 2;
constexpr int IQ_BYTES = 2;
constexpr int SIZE_W_IQ = TX * RX * FAST_TIME * SLOW_TIME * IQ;
constexpr int BUFFER_SIZE = 2048;
constexpr int PORT = 4098;
constexpr int BYTES_IN_PACKET = 1456;

static constexpr int DCA_HEADER_BYTES = 10; // packetNum(4) + byteCount(6)

class DataAcquisition {
private:
    // Socket members
    int sockfd;
    bool socket_ready;
    struct sockaddr_in servaddr, cliaddr;
    socklen_t len;

    // Buffers
    uint16_t* frame_data;
    char* buffer;

    // Computed sizes
    int BYTES_IN_FRAME;
    int BYTES_IN_FRAME_CLIPPED;
    int PACKETS_IN_FRAME_CLIPPED;
    int UINT16_IN_PACKET;
    int UINT16_IN_FRAME;

    int packets_read;

public:
    DataAcquisition() {
        BYTES_IN_FRAME = SLOW_TIME * FAST_TIME * RX * TX * IQ * IQ_BYTES;

        // Clip to whole UDP payload packets (payload excludes header)
        BYTES_IN_FRAME_CLIPPED = (BYTES_IN_FRAME / BYTES_IN_PACKET) * BYTES_IN_PACKET;

        // Packets per clipped frame
        PACKETS_IN_FRAME_CLIPPED = BYTES_IN_FRAME_CLIPPED / BYTES_IN_PACKET;

        UINT16_IN_PACKET = BYTES_IN_PACKET / 2;
        UINT16_IN_FRAME  = BYTES_IN_FRAME / 2;

        // Buffers
        frame_data = reinterpret_cast<uint16_t*>(malloc(UINT16_IN_FRAME * sizeof(uint16_t)));
        buffer     = reinterpret_cast<char*>(malloc(BUFFER_SIZE * sizeof(char)));

        packets_read = 0;

        // Socket state
        sockfd = -1;
        socket_ready = false;

        // Basic sanity: a recv buffer must hold header+payload at least
        if (UNLIKELY(BUFFER_SIZE < (DCA_HEADER_BYTES + BYTES_IN_PACKET))) {
            std::cerr << "[ERROR] BUFFER_SIZE is too small. Need >= "
                      << (DCA_HEADER_BYTES + BYTES_IN_PACKET) << " bytes.\n";
            std::exit(EXIT_FAILURE);
        }
    }

    ~DataAcquisition() {
        if (sockfd >= 0) close(sockfd);
        if (frame_data) free(frame_data);
        if (buffer) free(buffer);
    }

    // Create socket once and keep it open
    int create_bind_socket_once() {
        if (socket_ready) return 0;

        sockfd = socket(AF_INET, SOCK_DGRAM, 0);
        if (UNLIKELY(sockfd < 0)) {
            perror("[ERROR] socket() failed");
            return -1;
        }

        // Increase kernel receive buffer to reduce packet drops under load
        int rcvbuf = 16 * 1024 * 1024; // 16 MB for better buffering
        if (setsockopt(sockfd, SOL_SOCKET, SO_RCVBUF, &rcvbuf, sizeof(rcvbuf)) < 0) {
            perror("[WARN] setsockopt(SO_RCVBUF) failed");
            // not fatal
        }

        // Optional: allow fast rebinding if restart
        int reuse = 1;
        if (setsockopt(sockfd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse)) < 0) {
            perror("[WARN] setsockopt(SO_REUSEADDR) failed");
        }

        std::memset(&servaddr, 0, sizeof(servaddr));
        servaddr.sin_family      = AF_INET;
        servaddr.sin_addr.s_addr = htonl(INADDR_ANY);
        servaddr.sin_port        = htons(PORT);

        if (UNLIKELY(bind(sockfd, (struct sockaddr*)&servaddr, sizeof(servaddr)) < 0)) {
            perror("[ERROR] bind() failed");
            close(sockfd);
            sockfd = -1;
            return -1;
        }

        std::memset(&cliaddr, 0, sizeof(cliaddr));
        len = sizeof(cliaddr);

        socket_ready = true;
        return 0;
    }

    void close_socket() {
        if (sockfd >= 0) {
            close(sockfd);
            sockfd = -1;
        }
        socket_ready = false;
    }

    // Blocking receive with timeout using SO_RCVTIMEO
    int set_socket_timeout_ms(int timeout_ms) {
        if (!socket_ready) return -1;
        timeval tv;
        tv.tv_sec  = timeout_ms / 1000;
        tv.tv_usec = (timeout_ms % 1000) * 1000;
        if (setsockopt(sockfd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv)) < 0) {
            perror("[WARN] setsockopt(SO_RCVTIMEO) failed");
            return -1;
        }
        return 0;
    }

    inline int read_socket() {
        // DO NOT null-terminate binary UDP payload. Just read bytes.
        int bytes = recvfrom(sockfd, buffer, BUFFER_SIZE, 0, (struct sockaddr*)&cliaddr, &len);
        return bytes;
    }

    // Packet number is first 4 bytes
    inline uint32_t get_packet_num() const {
        const unsigned char* b = reinterpret_cast<const unsigned char*>(buffer);
        uint32_t packet_number =
            ((uint32_t)(b[0]) << 0)  |
            ((uint32_t)(b[1]) << 8)  |
            ((uint32_t)(b[2]) << 16) |
            ((uint32_t)(b[3]) << 24);
        return packet_number;
    }

    inline uint64_t get_byte_count() const {
        const unsigned char* b = reinterpret_cast<const unsigned char*>(buffer);
        uint64_t byte_count =
            ((uint64_t)(b[4]) << 0)  |
            ((uint64_t)(b[5]) << 8)  |
            ((uint64_t)(b[6]) << 16) |
            ((uint64_t)(b[7]) << 24) |
            ((uint64_t)(b[8]) << 32) |
            ((uint64_t)(b[9]) << 40);
        return byte_count;
    }

    // Copy payload into frame_data at the correct offset (slot-based)
    // OPTIMIZED: Use memcpy instead of loop for better performance
    inline void place_packet_payload_into_frame(int slot) {
        const int dst_u16 = (slot * BYTES_IN_PACKET) / 2;
        // Use memcpy for faster copy - compiler will optimize to SIMD instructions
        std::memcpy(&frame_data[dst_u16], buffer + DCA_HEADER_BYTES, BYTES_IN_PACKET);
    }

    uint16_t* getBufferPointer() {
        return frame_data;
    }

    /*
     * Robust frame capture:
     * - Keeps socket open
     * - Uses byte_count to compute (frameId, slot) and places packets accordingly
     * - Tolerates reordering, detects duplicates, and avoids mixing frames
     * - Can discard incomplete frames
     */
    py::array_t<uint16_t> capture_frame() {
        auto start = std::chrono::high_resolution_clock::now();

        if (UNLIKELY(create_bind_socket_once() != 0)) {
            std::cerr << "[ERROR] Failed to create/bind socket.\n";
            throw std::runtime_error("Failed to create/bind socket");
        }

        // Optional: timeout so don't block forever if packets stop
        set_socket_timeout_ms(500); // 500ms

        const int payloadBytes      = BYTES_IN_PACKET;
        const uint64_t frameBytes   = (uint64_t)BYTES_IN_FRAME_CLIPPED;
        const int packetsPerFrame   = PACKETS_IN_FRAME_CLIPPED;
        const int minPacketSize     = DCA_HEADER_BYTES + payloadBytes;

        // Track which packet slots of the current frame have arrived
        std::vector<uint8_t> got(packetsPerFrame, 0);
        int gotCount = 0;
        int duplicates = 0;

        // Track current frame id derived from byte_count
        // frameId = byte_count / frameBytes
        uint64_t currentFrameId = UINT64_MAX;

        // Clear the frame buffer (helps debugging missing packets)
        std::memset(frame_data, 0, UINT16_IN_FRAME * sizeof(uint16_t));

        while (true)
        {
            int nbytes = read_socket();
            if (UNLIKELY(nbytes < 0)) {
                // timeout or error
                perror("[WARN] recvfrom timeout/error");
                // If we already started a frame and it's incomplete, discard and restart
                currentFrameId = UINT64_MAX;
                std::fill(got.begin(), got.end(), 0);
                gotCount = 0;
                duplicates = 0;
                continue;
            }

            // Require at least header+payload
            if (UNLIKELY(nbytes < minPacketSize)) {
                std::cerr << "[WARN] Short packet received: " << nbytes << " bytes\n";
                continue;
            }

            const uint32_t pktNum = get_packet_num();
            const uint64_t bc     = get_byte_count();

            const uint64_t frameId = bc / frameBytes;
            const uint64_t offset  = bc % frameBytes;
            const int slot = (int)(offset / payloadBytes);

            // First packet: lock to its frameId
            if (UNLIKELY(currentFrameId == UINT64_MAX)) {
                currentFrameId = frameId;
                std::fill(got.begin(), got.end(), 0);
                gotCount = 0;
                duplicates = 0;
                // optional: clear buffer at frame start
                std::memset(frame_data, 0, UINT16_IN_FRAME * sizeof(uint16_t));
            }

            // Old out-of-order packet for a previous frame: ignore
            if (UNLIKELY(frameId < currentFrameId)) {
                continue;
            }

            // We advanced to the next frame before completing the current one:
            // Doppler for incomplete frames is incorrect, so DISCARD current and start new.
            if (UNLIKELY(frameId > currentFrameId)) {
                // Log the incomplete frame stats
                int missing = packetsPerFrame - gotCount;
                std::cerr << "[WARN] Incomplete frame discarded. frameId=" << currentFrameId
                          << " got=" << gotCount << "/" << packetsPerFrame
                          << " missing=" << missing
                          << " duplicates=" << duplicates << "\n";

                // Start new frame
                currentFrameId = frameId;
                std::fill(got.begin(), got.end(), 0);
                gotCount = 0;
                duplicates = 0;
                std::memset(frame_data, 0, UINT16_IN_FRAME * sizeof(uint16_t));
            }

            // Bounds check slot
            if (UNLIKELY(slot < 0 || slot >= packetsPerFrame)) {
                std::cerr << "[WARN] slot out of range. pktNum=" << pktNum
                          << " frameId=" << frameId << " slot=" << slot << "\n";
                continue;
            }

            // Duplicate slot?
            if (UNLIKELY(got[slot])) {
                duplicates++;
                continue;
            }

            // Place packet payload into correct frame offset
            place_packet_payload_into_frame(slot);
            got[slot] = 1;
            gotCount++;

            // Frame complete: return successfully with a clean frame buffer
            if (LIKELY(gotCount == packetsPerFrame)) {
                break;
            }
        }

        auto stop = std::chrono::high_resolution_clock::now();
        auto dur_us = std::chrono::duration_cast<std::chrono::microseconds>(stop - start);
        auto

        std::cout << "DAQ Process Time " << dur_us.count() << " microseconds\n";
        std::cout << "Frame capture complete: got=" << gotCount << "/" << packetsPerFrame
                  << " duplicates=" << duplicates
                  << " frameId=" << currentFrameId << "\n";
        std::cout << "~~~~~~~~~~~~~~~~~~~END OF SINGLE FRAME~~~~~~~~~~~~~~~~~~~~\n";

        // Return numpy array (zero-copy view into frame_data)
        return py::array_t<uint16_t>(
            {SIZE_W_IQ},  // shape
            {sizeof(uint16_t)},  // strides
            frame_data,  // data pointer
            py::cast(*this)  // parent object to keep alive
        );
    }
};

PYBIND11_MODULE(daq_fast, m) {
    m.doc() = "Hyper-optimized C++ DAQ implementation from daq-anirban.cpp with Python bindings";

    py::class_<DataAcquisition>(m, "DataAcquisition")
        .def(py::init<>(),
             "Initialize DataAcquisition")
        .def("capture_frame", &DataAcquisition::capture_frame,
             "Capture a complete frame and return as numpy array")
        .def("close_socket", &DataAcquisition::close_socket,
             "Close the UDP socket");

    m.attr("FAST_TIME") = FAST_TIME;
    m.attr("SLOW_TIME") = SLOW_TIME;
    m.attr("RX") = RX;
    m.attr("TX") = TX;
    m.attr("SIZE_W_IQ") = SIZE_W_IQ;
    m.attr("PORT") = PORT;
}
