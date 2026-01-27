#include "JSONTCP.h"

#include <fmt/core.h> //contextually assumed that this is what the process format call wants

// Class for multi-node server comms

JSON_TCP::JSON_TCP(const std::string &name) : node_name(name)
{
    exit_msg = node_name + " Demo Complete";
}

void JSON_TCP::setNodeName(const std::string &name)
{
    node_name = name;
    exit_msg = node_name + " Demo Complete";
}

std::string JSON_TCP::getNodeName() const
{
    return node_name;
}

void JSON_TCP::write_json(std::string fname, float angle, float range, float doppler, int doppler_bin, std::chrono::milliseconds duration)
{
    rapidjson::Document d;
    d.SetObject();
    s.SetString(node_name.c_str(), d.GetAllocator());

    // Add data to the JSON document
    d.AddMember("Node", s, d.GetAllocator());
    d.AddMember("Frame Number", frame, d.GetAllocator());
    d.AddMember("Elapsed Time (ms)", duration.count(), d.GetAllocator());
    d.AddMember("Angle", angle, d.GetAllocator());
    d.AddMember("Range", range, d.GetAllocator());
    d.AddMember("Doppler", doppler, d.GetAllocator());         // Doppler velocity in m/s
    d.AddMember("Doppler Bin", doppler_bin, d.GetAllocator()); // Raw doppler bin index

    // Add RDM data file path
    std::string rdm_fname = fname.substr(0, fname.find_last_of('.')) + "_rdm.bin";
    rapidjson::Value rdm_path;
    rdm_path.SetString(rdm_fname.c_str(), d.GetAllocator());
    d.AddMember("RDM File", rdm_path, d.GetAllocator());

    // Open the output file
    fp = fopen(fname.c_str(), "w");

    // Write the JSON data to the file
    char writeBuffer[65536];

    rapidjson::FileWriteStream os(fp, writeBuffer, sizeof(writeBuffer));
    rapidjson::Writer<rapidjson::FileWriteStream> writer(os);
    d.Accept(writer);

    fclose(fp);
    printf("Frame %d saved: Angle=%.1f°, Range=%.2fm, Doppler=%.2fm/s\n", frame, angle, range, doppler);
}

void JSON_TCP::save_rdm_binary(const std::string &filename, float *rdm_data)
{
    FILE *fp_rdm = fopen(filename.c_str(), "wb");
    if (fp_rdm == NULL)
    {
        perror("[ERROR] Could not open RDM file for writing\n");
        return;
    }

    // Write header: dimensions (SLOW_TIME=64, FAST_TIME=512)
    int dims[2] = {SLOW_TIME, FAST_TIME};
    fwrite(dims, sizeof(int), 2, fp_rdm);

    // Write the RDM data (64 * 512 floats)
    fwrite(rdm_data, sizeof(float), SLOW_TIME * FAST_TIME, fp_rdm);

    fclose(fp_rdm);
}

void JSON_TCP::send_file_data(std::string fname, float angle, float range,  float doppler, int doppler_bin, std::chrono::milliseconds duration)
{
    write_json(fname, angle, range, doppler, doppler_bin, duration); // Write JSON file with angle data
    fp_in = fopen(fname.c_str(), "r");         // Read JSON file with angle data

    // Read the text file
    if (fp_in == NULL)
    {
        perror("[ERROR] reading the file\n");
        exit(EXIT_FAILURE);
    }

    // Send the data
    memset(&buffer, 0, sizeof(buffer));
    while (fgets(buffer, MAXLINE, fp_in) != NULL)
    {
        printf("\nSending: %s", buffer);

        n = sendto(clientSd, buffer, MAXLINE, 0, (struct sockaddr *)&servaddr, sizeof(servaddr));
        if (n == -1)
        {
            perror("[ERROR] sending data to the server.\n");
            exit(EXIT_FAILURE);
        }
        memset(&buffer, 0, sizeof(buffer));
    }

    // Send the 'END'
    strcpy(buffer, "END");
    sendto(clientSd, buffer, MAXLINE, 0, (struct sockaddr *)&servaddr, sizeof(servaddr));
    fclose(fp_in);
}

int JSON_TCP::socket_setup()
{
    memset(&servaddr, 0, sizeof(servaddr));

    // Socket address properties
    servaddr.sin_family = AF_INET;
    servaddr.sin_addr.s_addr = inet_addr(IP);
    servaddr.sin_port = htons(SERVER_PORT);

    // Create a TCP socket
    clientSd = socket(AF_INET, SOCK_STREAM, 0);
    if (clientSd < 0)
    {
        perror("[ERROR] socket error\n");
        exit(EXIT_FAILURE);
    }
    printf("\nClient Setup Complete...\n");

    if (connect(clientSd, (sockaddr *)&servaddr, sizeof(servaddr)) < 0)
    {
        printf("Error Connecting To Socket!\n");
        exit(EXIT_FAILURE);
    }
    printf("Connected To Server!\n\n");
    return 1;
}

int JSON_TCP::get_frames()
{
    memset(&buffer, 0, sizeof(buffer));
    addr_size = sizeof(servaddr);
    n = recvfrom(clientSd, buffer, MAXLINE, 0, (struct sockaddr *)&servaddr, &addr_size);
    printf("Capturing %s Frames...\n\n", buffer);
    return std::stoi(buffer);
}

void JSON_TCP::setRDMPointer(float *ptr)
{
    rdm_data_ptr = ptr;
}

void JSON_TCP::process(float angle, float range, float doppler, int doppler_bin, std::chrono::time_point<std::chrono::high_resolution_clock> start_time)
{
    auto stop = std::chrono::high_resolution_clock::now();
    auto duration_udp_process = std::chrono::duration_cast<std::chrono::milliseconds>(stop - start_time);

    fname = fmt::format("{}/{}_Frame{}.json", path, node_name.c_str(), frame);
    write_json(fname, angle, range, doppler, doppler_bin, duration_udp_process); // Write JSON file locally

    // Save RDM binary data for plotting
    if (rdm_data_ptr != nullptr)
    {
        std::string rdm_fname = fmt::format("{}/{}_Frame{}_rdm.bin", path, node_name.c_str(), frame);
        save_rdm_binary(rdm_fname, rdm_data_ptr);
    }

    frame++;
}

void JSON_TCP::process(float angle, float range, std::chrono::time_point<std::chrono::high_resolution_clock> start_time)
{
   process(angle, range, 0.0f, 0, start_time);
}

void JSON_TCP::end_stream()
{
    printf("\n=== Data Collection Complete ===\n");
    printf("Saved %d frames to: %s\n\n", frame - 1, path);
}

void JSON_TCP::run_calibration()
{
    printf("\n=== Running Calibration ===\n");
    // Call Python calibration script with data directory
    std::string cmd = fmt::format("python3 /home/chirp/Chirp/Self-Calibration/Simulation/Single-Target/calibrate.py %s", path);
    int ret = system(cmd.c_str());
    if (ret == 0)
    {
        printf("Calibration complete! Check %s/calibration_output/\n", path);
    }
    else
    {
        printf("Calibration failed (exit code: %d)\n", ret);
    }
}

void JSON_TCP::run_rdm_plotting()
{
    printf("\n=== Running Range-Doppler Map Plotting ===\n");
    // Call Python RDM plotting script with data directory
    // The script path is relative to the project root
    std::string script_path = "/home/chirp/Chirp/Node/src/rpl/rdm_plotter.py";
    std::string cmd = fmt::format("python3 %s %s", script_path.c_str(), path);
    int ret = system(cmd.c_str());
    if (ret == 0)
    {
        printf("RDM plotting complete! Check %s/rdm_plots/\n", path);
    }
    else
    {
        printf("RDM plotting failed (exit code: %d)\n", ret);
    }
}

void JSON_TCP::run_rdm_plotting_single(int frame_num)
{
    printf("\n=== Running Range-Doppler Map Plotting for Frame %d ===\n", frame_num);
    // Call Python RDM plotting script for a single frame
    std::string script_path = "/home/chirp/Chirp/Node/src/rpl/rdm_plotter.py";
    std::string cmd = fmt::format("python3 %s %s --frame %d", script_path.c_str(), path, frame_num);
    int ret = system(cmd.c_str());
    if (ret == 0)
    {
        printf("RDM plot saved!\n");
    }
    else
    {
        printf("RDM plotting failed (exit code: %d)\n", ret);
    }
}