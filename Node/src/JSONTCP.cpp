#include "JSONTCP.h"

#include <fmt/core.h> //contextually assumed that this is what the process format call wants

// Class for multi-node server comms

void JSON_TCP::write_json(std::string fname, float angle, float range, auto duration)
{
    rapidjson::Document d;
    d.SetObject();
    s.SetString(rapidjson::StringRef(node));

    // Add data to the JSON document
    d.AddMember("Node", s, d.GetAllocator());
    d.AddMember("Frame Number", frame, d.GetAllocator());
    d.AddMember("Elapsed Time (ms)", duration.count(), d.GetAllocator());
    d.AddMember("Angle", angle, d.GetAllocator());
    d.AddMember("Range", range, d.GetAllocator());

    // Open the output file
    fp = fopen(fname.c_str(), "w");

    // Write the JSON data to the file
    char writeBuffer[65536];
    
    rapidjson::FileWriteStream os(fp, writeBuffer, sizeof(writeBuffer));
    rapidjson::Writer<rapidjson::FileWriteStream> writer(os);
    d.Accept(writer);

    fclose(fp);
}

void JSON_TCP::send_file_data(std::string fname, float angle, float range, auto duration)
{
    write_json(fname, angle, range, duration); // Write JSON file with angle data
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

void JSON_TCP::process(float angle, float range, auto start_time)
{
    auto stop = std::chrono::high_resolution_clock::now();
    auto duration_udp_process = std::chrono::duration_cast<std::chrono::milliseconds>(stop - start_time);
    
    fname = fmt::format("{}/{}_Frame{}.json", path, node, frame);
    send_file_data(fname, angle, range, duration_udp_process); // Send file to server
    printf("\nFrame Data Sent To Server\n\n");
    frame++;
}

void JSON_TCP::end_stream()
{
    memset(&buffer, 0, sizeof(buffer));
    strcpy(buffer, exit_msg);
    n = sendto(clientSd, buffer, MAXLINE, 0, (struct sockaddr *)&servaddr, sizeof(servaddr));
    close(clientSd);
    printf("Demo Complete!\n");
    printf("Connection Closed...\n\n");
}