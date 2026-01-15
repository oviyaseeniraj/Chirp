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
    const char *node = "Patrick"; // Patrick or Mike
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
    const char *exit_msg = "Patrick Demo Complete";

public:
    void write_json(std::string fname, float angle, float range, auto duration);
    void send_file_data(std::string fname, float angle, float range, auto duration);
    int socket_setup();
    int get_frames();
    void process(float angle, float range, auto start_time);
    void end_stream();
};

#endif