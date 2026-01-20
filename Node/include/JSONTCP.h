#ifndef JSON_TCP_H
#define JSON_TCP_H

#include "main.h"

#include "rapidjson/document.h"
#include "rapidjson/writer.h"
#include "rapidjson/stringbuffer.h"
#include "rapidjson/filewritestream.h"
// Class for multi-node server comms
class JSON_TCP
{
    int frame = 1;
    std::string node_name;  // Set via constructor or setNodeName()
    int clientSd;
    struct sockaddr_in servaddr;
    socklen_t addr_size;
    rapidjson::Value s;
    FILE *fp;
    FILE *fp_in;
    std::string fname;
    const char *path = "/home/fusionsense/repos/AVR/RadarPipeline/test/non_thread/frame_data";
    char buffer[MAXLINE];
    int n;
    std::string exit_msg = "Patrick Demo Complete";
	float* rdm_data_ptr = nullptr;  // Pointer to RDM data for saving


public:
    JSON_TCP(const std::string& name = "Node");
    void setNodeName(const std::string& name);
    std::string getNodeName() const;
    void write_json(std::string fname, float angle, float range,  float doppler, int doppler_bin, std::chrono::milliseconds duration);
    void save_rdm_binary(const std::string& filename, float* rdm_data);
    void send_file_data(std::string fname, float angle, float range,  float doppler, int doppler_bin, std::chrono::milliseconds duration);
    int socket_setup();
    int get_frames();
    void setRDMPointer(float* ptr);
    void process(float angle, float range, float doppler, int doppler_bin, std::chrono::time_point<std::chrono::high_resolution_clock> start_time);
    void process(float angle, float range, std::chrono::time_point<std::chrono::high_resolution_clock> start_time);
    void end_stream();
    void run_calibration();
	void run_rdm_plotting();
	void run_rdm_plotting_single(int frame_num);

};

#endif