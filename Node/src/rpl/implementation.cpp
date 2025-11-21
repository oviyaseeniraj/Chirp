using namespace std;
using namespace cv;
using namespace std::chrono;
using Eigen::MatrixXd;
using namespace Eigen;
using namespace rapidjson;
#include <iostream>
#include <fstream>
#include "rapidjson/document.h"
#include "rapidjson/writer.h"
#include "rapidjson/stringbuffer.h"

# define n_pi           3.14159265358979323846 

#define FAST_TIME 512 //Initializes the number of fast time samples | # of range samples
#define SLOW_TIME 64 //Initializes the number of slow time samples | # of doppler samples
#define RX 4        // # of Rx
#define TX 3        // # of Tx
#define IQ 2 //Types of IQ (I and Q) 
#define SIZE_W_IQ TX*RX*FAST_TIME*SLOW_TIME*IQ  // Size of the total number of separate IQ sampels from ONE frame
#define SIZE TX*RX*FAST_TIME*SLOW_TIME          // Size of the total number of COMPLEX samples from ONE frame

#define BUFFER_SIZE 2048 
#define PORT        4098
#define BYTES_IN_PACKET 1456 // Max packet size - sequence number and byte count = 1466-10 

#define IQ_BYTES 2 

#define IP				"169.231.215.235" // server IP
#define SERVER_PORT		1210 
#define MAXLINE 		1024

// Class for multi-node server comms
class JSON_TCP {
    int frame = 1;
    const char *node = "Patrick";    // Patrick or Mike
    int clientSd;
    struct sockaddr_in servaddr;
	socklen_t addr_size;
    Value s;
	FILE* fp;
	FILE* fp_in;
	string fname;
	const char *path = "/home/fusionsense/Documents/Chirp/Node/test/non_thread/frame_data";
	char buffer[MAXLINE];
	int n;
	const char *exit_msg = "Patrick Demo Complete";
    
	public:
		void write_json(string fname, float angle, float range, auto duration) {
		    Document d; 
		    d.SetObject();
		    s.SetString(StringRef(node));

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
		    FileWriteStream os(fp, writeBuffer, sizeof(writeBuffer)); 
		    Writer<FileWriteStream> writer(os); 
		    d.Accept(writer);

		    fclose(fp);
		    printf("Frame %d saved: Angle=%.1f°, Range=%.2fm\n", frame, angle, range);
		}

		void send_file_data(string fname, float angle, float range, auto duration) {
			write_json(fname, angle, range, duration);    	// Write JSON file with angle data
		    fp_in = fopen(fname.c_str(), "r");				// Read JSON file with angle data

		    // Read the text file
		    if (fp_in == NULL) {
		        perror("[ERROR] reading the file\n");
		        exit(EXIT_FAILURE);
		    }
		    
		    // Send the data
		    memset(&buffer, 0, sizeof(buffer));
		    while (fgets(buffer, MAXLINE, fp_in) != NULL) {
		        printf("\nSending: %s", buffer);

		        n = sendto(clientSd, buffer, MAXLINE, 0, (struct sockaddr*)&servaddr, sizeof(servaddr));
		        if (n == -1) {
		            perror("[ERROR] sending data to the server.\n");
		            exit(EXIT_FAILURE);
		        }
		        memset(&buffer, 0, sizeof(buffer));
		    }

		    // Send the 'END'
		    strcpy(buffer, "END");
		    sendto(clientSd, buffer, MAXLINE, 0, (struct sockaddr*)&servaddr, sizeof(servaddr));
		    fclose(fp_in);
		}
		
		int socket_setup() {
			memset(&servaddr, 0, sizeof(servaddr));
		    
		    // Socket address properties
		    servaddr.sin_family = AF_INET;
			servaddr.sin_addr.s_addr = inet_addr(IP);
		    servaddr.sin_port = htons(SERVER_PORT);
		    
		    // Create a TCP socket
		    clientSd = socket(AF_INET, SOCK_STREAM, 0);
		    if (clientSd < 0) {
		        perror("[ERROR] socket error\n");
		        exit(EXIT_FAILURE);
		    }
		    printf("\nClient Setup Complete...\n");
		    
		    if (connect(clientSd, (sockaddr*) &servaddr, sizeof(servaddr)) < 0) {
		    	printf("Error Connecting To Socket!\n");
		    	exit(EXIT_FAILURE);
		    }
		    printf("Connected To Server!\n\n");
		    return 1;
		}

		int get_frames() {
			memset(&buffer, 0, sizeof(buffer));
			addr_size = sizeof(servaddr);
			n = recvfrom(clientSd, buffer, MAXLINE, 0, (struct sockaddr*)&servaddr, &addr_size);
			printf("Capturing %s Frames...\n\n", buffer);
			return stoi(buffer);
		}

		void process(float angle, float range, auto start_time) {
		    auto stop = chrono::high_resolution_clock::now();
		    auto duration_udp_process = duration_cast<milliseconds>(stop - start_time);		    
		    
			fname = format("%s/%s_Frame%d.json", path, node, frame);
		    write_json(fname, angle, range, duration_udp_process); // Write JSON file locally
		    
		    frame++;
		}
		
	void end_stream() {
		printf("\n=== Data Collection Complete ===\n");
		printf("Saved %d frames to: %s\n\n", frame - 1, path);
	}
	
	void run_calibration() {
		printf("\n=== Running Calibration ===\n");
		// Call Python calibration script with data directory
		string cmd = format("python3 /home/fusionsense/calibrate.py %s", path);
		int ret = system(cmd.c_str());
		if (ret == 0) {
			printf("Calibration complete! Check %s/calibration_output/\n", path);
		} else {
			printf("Calibration failed (exit code: %d)\n", ret);
		}
	}
};

// Base class used for other modules
class RadarBlock
{
    int inputsize;
    int outputsize;
    bool verbose;

    public:
        // Public variables
        uint frame = 0;

        uint* inputframeptr;
        float* inputbufferptr;
		float* inputangbufferptr;
		float* inputrangebuffptr;
		int* inputangindexptr;
		float* inputangmapptr;

        uint lastframe;

        // Public functions
        // Class constructor
        RadarBlock(int size_in, int size_out, bool v = false) : outputbuffer(new float[size_out])
        {   
            inputsize = size_in;
            outputsize = size_out;
            verbose = v;

            printf("New %s created.\n", typeid(*this).name());
        }

        // Class deconstructor
        ~RadarBlock()
        {
            delete[] outputbuffer; 

            printf("%s destroyed.\n", typeid(*this).name());
        }

        // Sets the input buffer pointer
        void setBufferPointer(float* ptr)
        {
            inputbufferptr = ptr;
        }
        
        void setRangeBufferPointer(float* ptr)
        {
            inputrangebuffptr = ptr;
        }

		void setAngleBufferPointer(float* ptr)
        {
            inputangbufferptr = ptr;
        }

		void setAngleIndexPointer(int* ptr)
        {
            inputangindexptr = ptr;
        }
        
        void setAngleMapPointer(float* ptr)
        {
            inputangmapptr = ptr;
        }

        // Sets the input frame pointer
        void setFramePointer(uint* ptr)
        {
            inputframeptr = ptr;
            lastframe = *ptr;
        }

        // Retrieve outputbuffer pointer
        float* getBufferPointer()
        {
            return outputbuffer;
        }

        // Retrieve frame pointer
        uint* getFramePointer()
        {
            return &frame;
        }

        // Complete desired calculations / data manipulation
        virtual void process()
        {
            printf("Process done!\n");
        }

        // Iterates
        void iteration()
        {
            for(;;)
            {
                listen();

                // start timer
                auto start = chrono::high_resolution_clock::now();

                process();

                // stop timer
                auto stop = chrono::high_resolution_clock::now();

                if(verbose)
                {
                    // calculate elapsed time in microseconds
                    auto duration = chrono::duration_cast<chrono::microseconds>(stop - start);

                    // print elapsed time
                    cout << "Elapsed time: " << duration.count() << " microseconds" << endl;
                }

                increment_frame();
            }
        }

    private:
        // Private variables
        float* outputbuffer;

        // Private functions
        // Listens for previous block (overwritten in some cases)
        virtual void listen()
        {
            for(;;)
            {
                if(*inputframeptr != lastframe)
                {
                    lastframe = *inputframeptr;
                    break;
                }
            }
        }

        // Increments frame count
        void increment_frame()
        {
            frame++;
        }
};

// 1024 x 600
// Visualizes range-doppler data
class Visualizer : public RadarBlock
{
    // Variables
    int width = 64;
    int height = 512;

    int px_width = 10;
    int px_height = 2;

    float X_SCALE = 0.16;
    float Y_SCALE = 0.035;
    int stepSizeX = 64;
    int stepSizeY = 57; 
    int borderSize = 60;
    int borderLeft = 220;
    int borderRight = borderLeft;
    int borderBottom = 60;
    int AXES_COLOR = 169;
    int frame;

    public:
        Visualizer(int size_in, int size_out, bool verbose = false) : RadarBlock(size_in, size_out, verbose), 
            image(px_height * height/2, px_width * width, CV_8UC1, Scalar(255))
        {
            frame = 1;
            namedWindow("Image",WINDOW_NORMAL);
            setWindowProperty("Image", WND_PROP_FULLSCREEN, WINDOW_NORMAL);

        }

        // Visualizer's process
        void process() override
        {
            auto start = chrono::high_resolution_clock::now();
            
            //if(frame <= 1){
                cv::Scalar borderColor(0, 0, 0); 

                // Add the padded border
                // TOP | BOTTOM | LEFT | RIGHT
                cv::copyMakeBorder(image, borderedImage, borderSize, borderSize, borderLeft, borderRight,
                                cv::BORDER_CONSTANT, borderColor);

		cv::Point zeroZero(0,0);
		cv::Point maxMax(1080,632);
		

		cv::rectangle(borderedImage, zeroZero, maxMax, borderColor, -1);

                cv::Point xEnd(borderedImage.cols-borderLeft, borderedImage.rows-borderSize);
                cv::Point yEnd(borderLeft, borderSize);

                cv::Point originRDM(120, 316);
                cv::Point xEndRDM(440, 316);
                cv::Point yEndRDM(120, 60);

		cv::Point originXY(640,316);
		cv::Point cornerXY(960, 60);
		cv::rectangle(borderedImage, originXY, cornerXY, borderColor, -1);
                cv::Point origin(borderLeft, borderedImage.rows-borderSize);
               // cv::line(borderedImage, originRDM, xEndRDM, cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);
//		//cv::line(borderedImage, originRDM, yEndRDM, cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);
                
		cv::rectangle(borderedImage, originRDM, cv::Point(440,60), cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);
		cv::rectangle(borderedImage, originXY, cornerXY, cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);

		cv::rectangle(borderedImage, cv::Point(795,321), cv::Point(805,311), cv::Scalar(130, 34, 34), -1);

                std::string label_x = "-     Velocity     +";
                std::string label_RDM = "RDM";
                std::string label_XY = "XY Plot";
		std::string label_xXY = "x position";



                int fontFace = cv::FONT_HERSHEY_SIMPLEX;
                double fontScale = 1.0;
                int thickness = 4;
                int baseline = 0;

                cv::Size textSize = cv::getTextSize(label_x, fontFace, fontScale, thickness, &baseline);
                //cv::Point textPosition_x((image.cols - textSize.width)/2, image.rows - baseline - 10);
                //madness begins here
                cv::Point textPosition_x(110, 370);
                cv::Point textPosition_RDM(240, 50);

		cv::Point textPosition_XY(240+500, 50);
                cv::Point textPosition_xXY(110+600, 370);

                cv::Point textPosition_r(50, 130);
                cv::Point textPosition_a(50, 160);
                cv::Point textPosition_n(50, 190);
                cv::Point textPosition_g(50, 220);
                cv::Point textPosition_e(50, 250);

                cv::Point textPosition_y(50+520, 60);
                cv::Point textPosition_p(50+520, 120);
                cv::Point textPosition_o(50+520, 150);
                cv::Point textPosition_s(50+520, 180);
                cv::Point textPosition_i(50+520, 210);
                cv::Point textPosition_t(50+520, 240);
                cv::Point textPosition_i2(50+520, 270);
                cv::Point textPosition_o2(50+520, 300);
                cv::Point textPosition_n2(50+520, 330);

                cv::putText(borderedImage, label_x, textPosition_x, fontFace, fontScale, cv::Scalar(169, 169, 169), thickness);
                cv::putText(borderedImage, label_RDM, textPosition_RDM, fontFace, fontScale, cv::Scalar(169, 169, 169), thickness);

                cv::putText(borderedImage, label_XY, textPosition_XY, fontFace, fontScale, cv::Scalar(169, 169, 169), thickness);
                cv::putText(borderedImage, label_xXY, textPosition_xXY, fontFace, fontScale, cv::Scalar(169, 169, 169), thickness);

                cv::putText(borderedImage, "R", textPosition_r, fontFace, fontScale, cv::Scalar(169, 169, 169), thickness);
                cv::putText(borderedImage, "a", textPosition_a, fontFace, fontScale, cv::Scalar(169, 169, 169), thickness);
                cv::putText(borderedImage, "n", textPosition_n, fontFace, fontScale, cv::Scalar(169, 169, 169), thickness);
                cv::putText(borderedImage, "g", textPosition_g, fontFace, fontScale, cv::Scalar(169, 169, 169), thickness);
                cv::putText(borderedImage, "e", textPosition_e, fontFace, fontScale, cv::Scalar(169, 169, 169), thickness);

                cv::putText(borderedImage, "y", textPosition_y, fontFace, fontScale, cv::Scalar(169, 169, 169), thickness);
                cv::putText(borderedImage, "p", textPosition_p, fontFace, fontScale, cv::Scalar(169, 169, 169), thickness);
                cv::putText(borderedImage, "o", textPosition_o, fontFace, fontScale, cv::Scalar(169, 169, 169), thickness);
                cv::putText(borderedImage, "s", textPosition_s, fontFace, fontScale, cv::Scalar(169, 169, 169), thickness);
                cv::putText(borderedImage, "i", textPosition_i, fontFace, fontScale, cv::Scalar(169, 169, 169), thickness);                
                cv::putText(borderedImage, "t", textPosition_t, fontFace, fontScale, cv::Scalar(169, 169, 169), thickness);
                cv::putText(borderedImage, "i", textPosition_i2, fontFace, fontScale, cv::Scalar(169, 169, 169), thickness);
                cv::putText(borderedImage, "o", textPosition_o2, fontFace, fontScale, cv::Scalar(169, 169, 169), thickness);
                cv::putText(borderedImage, "n", textPosition_n2, fontFace, fontScale, cv::Scalar(169, 169, 169), thickness);





	        //cv::Point textPosition_ang(borderLeft - 200, (borderedImage.rows-60+4*(textSize.height+24))/2);
	        //cv::putText(borderedImage, "F", textPosition_ang, fontFace, fontScale, cv::Scalar(169, 169, 169), thickness);
		cv::Point textPosition_angtxt(borderLeft + 650, (borderedImage.rows-60+2*(textSize.height+300))/2); // Angle
		//cv::putText(borderedImage, "Est. Angle (Degrees)", textPosition_angtxt, cv::FONT_HERSHEY_PLAIN, 1.0, cv::Scalar(169, 169, 169), 2); //  ANGLE VISUALIZER

                for (int i = -5; i <= 5; i += 1) {
                    std::ostringstream stream;
                    stream << std::fixed << std::setprecision(0) << i;
                    cv::Point pt(i*32 + 160+220-100, 316);
                    cv::line(borderedImage, pt, pt - cv::Point(0, -5), cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);
                    cv::putText(borderedImage, stream.str(), pt + cv::Point(-10, 20),
                                cv::FONT_HERSHEY_SIMPLEX, 0.5, cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);

                    cv::line(borderedImage, pt + cv::Point(520,0), pt - cv::Point(0, -5) + cv::Point(520,0), cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);
                    cv::putText(borderedImage, stream.str(), pt + cv::Point(-10, 20) + cv::Point(520,0),
                                cv::FONT_HERSHEY_SIMPLEX, 0.5, cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);
                }
               for (int i = 0; i <= 9; i += 1) {
                    std::ostringstream stream;
                    stream << std::fixed << std::setprecision(0) << 9-i;
                    cv::Point pt(220-100, i*28 + 60);
                    cv::line(borderedImage, pt, pt + cv::Point(-5, 0), cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);
                    cv::putText(borderedImage, stream.str(), pt + cv::Point(-30, 10),
                                cv::FONT_HERSHEY_SIMPLEX, 0.5, cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);

                    cv::line(borderedImage, pt + cv::Point(520,0), pt + cv::Point(-5, 0) + cv::Point(520,0), cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);
                    cv::putText(borderedImage, stream.str(), pt + cv::Point(-30, 10) + cv::Point(520,0),
                                cv::FONT_HERSHEY_SIMPLEX, 0.5, cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);
                }

		  /* Range Angle Map Debug      
		        for (int i = -90; i <= 90; i += 45) {
                    std::ostringstream stream;
                    stream << std::fixed << std::setprecision(0) << i;
                    cv::Point pt1(400-100, 500 - i);
                    cv::line(borderedImage, pt1, pt1 + cv::Point(-5, 0), cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);
                    cv::putText(borderedImage, stream.str(), pt1 + cv::Point(-45, 5),
                                cv::FONT_HERSHEY_SIMPLEX, 0.5, cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);
                                
                }
                cv::line(borderedImage, cv::Point(300,590), cv::Point(300, 410), cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);
                
                
				for (int i = -90; i <= 90; i += 30) {
                    std::ostringstream stream;
                    stream << std::fixed << std::setprecision(0) << i;
                    cv::Point pt2((i+90)*3.2 + 400-100, 595);
                    cv::line(borderedImage, pt2, pt2 + cv::Point(0, -5), cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);
                    cv::putText(borderedImage, stream.str(), pt2 + cv::Point(-10, 20),
                                cv::FONT_HERSHEY_SIMPLEX, 0.5, cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);

                }
                cv::line(borderedImage, cv::Point(300,590), cv::Point(876, 590), cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);
		
		
			for (int i = 0; i < 64; i++) {
                for (int j = 0; j < 4; j++) {
                    for(int x = 0; x < 9; x++) {
                        for(int y = 0; y < 45; y++) {
                            borderedImage.at<uint8_t>(45 * (j) + y + 410, 9 * i + x + 300) = static_cast<uint8_t>(inputangmapptr[64*(4) - ((64-1)*4 - 4 * i + j)]);
                        }
                    }
                }
            }
		*/


            //}
		//cv::Point originXY(640,316);
		//cv::Point cornerXY(960, 60);
		//cv::rectangle(borderedImage, originXY, cornerXY, cv::Scalar(0,0,0), -1);


            int half_offset = 0;
            if(true)
                half_offset = height/2;

	    cv::Size textSize1 = cv::getTextSize("-           Velocity           +", cv::FONT_HERSHEY_SIMPLEX, 1.0, 4, 0); 
	    
	    /*cv::Point textPosition_ang(borderLeft + 650, (borderedImage.rows-60+4*(textSize.height+24))/2); // OLD ANGLE VISUALIZER
	    cv::line(borderedImage, textPosition_ang, textPosition_ang + cv::Point(150, 0), cv::Scalar(0, 0, 0), 70);
	    float anglefloat = *inputangbufferptr; 
	    setprecision(1);
	    std::string anglestr = to_string(anglefloat);
	    cv::putText(borderedImage, anglestr, textPosition_ang, cv::FONT_HERSHEY_SIMPLEX, 1.0, cv::Scalar(169, 169, 169), 2); */
	    
 	    cv::Point textPosition_slow(borderLeft + 475, 100+(borderedImage.rows-60+6*(textSize1.height+24))/2); // for debug its borderleft -200
	    cv::Point textPosition_fast(borderLeft - 25, 100+(borderedImage.rows-60+6*(textSize1.height+24))/2);
	    //cv::line(borderedImage, textPosition_slow - cv::Point(150, 0), textPosition_slow + cv::Point(150, 0), cv::Scalar(0, 0, 0), 100);
	    cv::Point textPosition_angle(borderLeft + 475, 100+(borderedImage.rows-60+4*(textSize1.height+24))/2); // for debug its borderleft -200
	    cv::Point textPosition_range(borderLeft - 25, 100+(borderedImage.rows-60+4*(textSize1.height+24))/2);
	    cv::putText(borderedImage, "Range:", textPosition_range, cv::FONT_HERSHEY_SIMPLEX, 1.0, cv::Scalar(169, 169, 169), 2);
	    cv::putText(borderedImage, "Angle:", textPosition_angle, cv::FONT_HERSHEY_SIMPLEX, 1.0, cv::Scalar(169, 169, 169), 2);
	    
	    
	    float anglefloat = *inputangbufferptr;
	    
	    cout << "Angle Norm size: " << anglefloat << endl;
	    int cfar_slow = *inputangindexptr/FAST_TIME;
	    int cfar_fast = *inputangindexptr%FAST_TIME;
	    float rangefloat = *inputrangebuffptr;
	    setprecision(1);
	    std::string anglestr = to_string(anglefloat);
	    std::string slow_str = to_string(cfar_slow);
	    std::string fast_str = to_string(cfar_fast);
	    std::string rangestr = to_string(rangefloat);
	    //std::string fast_str = to_string(*inputangindexptr);  // Testing out the MVDR Angle Estimation
	    cv::putText(borderedImage, anglestr, textPosition_slow, cv::FONT_HERSHEY_SIMPLEX, 1.0, cv::Scalar(169, 169, 169), 2);
	    //cv::putText(borderedImage, slow_str, textPosition_slow, cv::FONT_HERSHEY_SIMPLEX, 1.0, cv::Scalar(169, 169, 169), 2);
	    //cv::putText(borderedImage, fast_str, textPosition_fast, cv::FONT_HERSHEY_SIMPLEX, 1.0, cv::Scalar(169, 169, 169), 2);
	    cv::putText(borderedImage, rangestr, textPosition_fast, cv::FONT_HERSHEY_SIMPLEX, 1.0, cv::Scalar(169, 169, 169), 2);
	    


            
            //took j to height/2 to height in order to cut Range on RDM in half
            for (int i = 0; i < width; i++) {
                for (int j = half_offset; j < height; j++) {
                    for(int x = 0; x < px_width/2; x++) {
                        for(int y = 0; y < px_height/2; y++) {
                            borderedImage.at<uint8_t>(px_height/2 * (j-height/2) + y + borderSize, px_width/2 * i + x + borderLeft-100) = static_cast<uint8_t>(inputbufferptr[width*(height) - ((width-1)*height - height * i + j)]);
                        }
                    }
                }
            }
            
            
            
	    cv::Point detection1(borderLeft - 100 + cfar_slow*px_width/2 - px_width/2, 316 - (cfar_fast*px_height/2 - px_height/2) );
	    cv::Point detection2(borderLeft - 100 + cfar_slow*px_width/2, 316 - cfar_fast*px_height/2);
	    cv::rectangle(borderedImage, detection1, detection2, Scalar(169,169,169), 3);
	    
	    float angrad = anglefloat * (M_PI / 180);
	    int xcoord = 800 + rangefloat*sin(angrad)*32;
	    int ycoord = 316 - rangefloat*cos(angrad)*28;
	
	    cv::Point xyPoint(xcoord, ycoord);

	    cv::line(borderedImage, xyPoint, xyPoint, cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 9);	
	    cv::line(borderedImage, cv::Point(800,316), xyPoint, cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 3);	

	    //cv::rectangle(borderedImage, xyPoint, xyPoint + cv::Point(2,2), cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), -1);
	    //cv::line(borderedImage, xyPoint, xyPoint, cv::Scalar(0, 0, 0), 9);	

       
            // cv::Rect roi(borderLeft, borderedImage.row - borderSize, px_width*width, px_height*height);
            // cv::Mat roiImage = borderedImage(roi);
            // Convert the matrix to a color image for visualization
            applyColorMap(borderedImage, colorImage, COLORMAP_JET);
            // Display the color image
            imshow("Image", colorImage);

            // Waits 1ms
            waitKey(wait_time);
            auto stop = chrono::high_resolution_clock::now();
            auto duration_vis_process = duration_cast<microseconds>(stop - start);
            std::cout << "VIS Process Time " << duration_vis_process.count() << " microseconds" << std::endl;
            frame ++;
            
        }

        void setWaitTime(int num){
            wait_time = num;
        }
        
        void listen() override
        {
            return;
        }

    private:
        Mat image;
        Mat borderedImage;
        Mat colorImage;
        int wait_time;
        
};


// Processes IQ data to make Range-Doppler map
class RangeDoppler : public RadarBlock
{
    public:
        RangeDoppler(const char* win = "blackman") : RadarBlock(SIZE,SIZE)
        {
            // RANGE DOPPLER PARAMETER INITIALIZATION
            WINDOW_TYPE = win;          //Determines what type of windowing will be done
            SET_SNR = false;
            adc_data_flat = reinterpret_cast<float*>(malloc(SIZE_W_IQ*sizeof(float)));                          // allocate mem for Separate IQ adc data from Data aquisition
            adc_data=reinterpret_cast<std::complex<float>*>(adc_data_flat);                                     // allocate mem for COMPLEX adc data from Data aquisition 
            adc_data_reshaped = reinterpret_cast<float*>(malloc(SIZE_W_IQ*sizeof(float)));                      // allocate mem for reorganized/reshaped adc data
            rdm_data = reinterpret_cast<std::complex<float>*>(malloc(SIZE * sizeof(std::complex<float>)));      // allocate mem for processed complex adc data
            rdm_norm = reinterpret_cast<float*>(malloc(SIZE * sizeof(float)));                                  // allocate mem for processed magnitude adc data
            rdm_avg = reinterpret_cast<float*>(calloc(SLOW_TIME*FAST_TIME, sizeof(float)));                     // allocate mem for averaged adc data across all virtual antennas
			prev_rdm_avg = reinterpret_cast<float*>(calloc(SLOW_TIME*FAST_TIME, sizeof(float))); // Previous frame allocation
			zero_rdm_avg = reinterpret_cast<float*>(calloc(SLOW_TIME*FAST_TIME, sizeof(float))); // rdm avg but with 0 doppler removed

			cfar_cube = reinterpret_cast<float*>(calloc(SLOW_TIME*FAST_TIME, sizeof(float)));
			angle_data = reinterpret_cast<std::complex<float>*>(calloc(256, sizeof(std::complex<float>)));
			angfft_data = reinterpret_cast<std::complex<float>*>(calloc(256, sizeof(std::complex<float>)));
			angle_norm = reinterpret_cast<float*>(malloc(256 * sizeof(float)));
			final_angle = reinterpret_cast<float*>(malloc(1 * sizeof(float)));
			final_range = reinterpret_cast<float*>(malloc(1 * sizeof(float)));
			cfar_max = reinterpret_cast<int*>(malloc(1 * sizeof(int)));
			//Rmatrix = reinterpret_cast<complex<float>*>(malloc(64 * sizeof(complex<float>)));
			Rmatrix = reinterpret_cast<complex<float>*>(malloc(144 * sizeof(complex<float>)));

            onlyRD_data = reinterpret_cast<std::complex<float>*>(malloc(SIZE * sizeof(std::complex<float>)));
            //preholding_data = reinterpret_cast<std::complex<float>*>(malloc(SLOW_TIME*FAST_TIME * sizeof(std::complex<float>)));
            //postholding_data = reinterpret_cast<std::complex<float>*>(malloc(SLOW_TIME*FAST_TIME * sizeof(std::complex<float>)));
            preholding_data = reinterpret_cast<std::complex<float>*>(malloc(FAST_TIME * sizeof(std::complex<float>)));
            postholding_data = reinterpret_cast<std::complex<float>*>(malloc(FAST_TIME * sizeof(std::complex<float>)));
            
            
            // FFT SETUP PARAMETERS
            const int rank = 2;     // Determines the # of dimensions for FFT
            const int n[] = {SLOW_TIME, FAST_TIME};
            const int howmany = TX*RX;
            const int idist = SLOW_TIME*FAST_TIME;
            const int odist = SLOW_TIME*FAST_TIME;
            const int istride = 1;
            const int ostride = 1;
            plan = fftwf_plan_many_dft(rank, n, howmany,
                                reinterpret_cast<fftwf_complex*>(adc_data), n, istride, idist,
                                reinterpret_cast<fftwf_complex*>(rdm_data), n, ostride, odist,
                                FFTW_FORWARD, FFTW_ESTIMATE);      // create the FFT plan
			
			const int rank2 = 2;     // Determines the # of dimensions for FFT
			const int n2[] = {4, 64};
			const int howmany2 = 1;
			const int idist2 = 0;
			const int odist2 = 0;
			const int istride2 = 1;
			const int ostride2 = 1;
			plan2 = fftwf_plan_many_dft(rank2, n2, howmany2,
				            reinterpret_cast<fftwf_complex*>(angle_data), n2, istride2, idist2,
				            reinterpret_cast<fftwf_complex*>(angfft_data), n2, ostride2, odist2,
				            FFTW_FORWARD, FFTW_ESTIMATE);      // create the FFT plan
				            
			/*	            
			const int rank3 = 1;     // Determines the # of dimensions for FFT
            const int n3[] = {SLOW_TIME};
            const int howmany3 = FAST_TIME;
            const int idist3 = 1;
            const int odist3 = 1;
            const int istride3 = FAST_TIME;
            const int ostride3 = FAST_TIME;
            plan3 = fftwf_plan_many_dft(rank3, n3, howmany3,
                                reinterpret_cast<fftwf_complex*>(preholding_data), n3, istride3, idist3,
                                reinterpret_cast<fftwf_complex*>(postholding_data), n3, ostride3, odist3,
                                FFTW_FORWARD, FFTW_ESTIMATE);      // create the FFT plan
			*/


			int frame = 1;
			int maxidx = 0;
        }
        
    /*    
    void compute_doppler_fft(complex<float>* adc_data, complex<float>* onlyRD_data, complex<float>* preholding_data, complex<float>* postholding_data) {
    
    	const int RD_bins = SLOW_TIME*FAST_TIME;
    	
    	for (int j=0; j<TX*RX; j++) {
			for (int i=0; i<RD_bins; i++) {
				preholding_data[i] = adc_data[i + j*RD_bins];
			}
		
		    fftwf_execute(plan3);
		    
		    for (int i=0; i<RD_bins; i++) {
				onlyRD_data[i + j*RD_bins] = postholding_data[i];
			}
		}
    	
    }
    */
    
    void compute_range_fft(complex<float>* adc_data, complex<float>* onlyRD_data, complex<float>* preholding_data, complex<float>* postholding_data) {
    
    	const int RD_bins = SLOW_TIME*FAST_TIME;
    	const int N3 = FAST_TIME;
        const int howmany3 = SLOW_TIME*TX*RX;
        const int idist3 = N3;
        const int istride3 = 1;
        plan3 = fftwf_plan_dft_1d(N3, reinterpret_cast<fftwf_complex*>(preholding_data), reinterpret_cast<fftwf_complex*>(postholding_data), FFTW_FORWARD, FFTW_ESTIMATE);
        
        for (int k=0; k<howmany3; k++) {
        	for (int j=0; j<N3; j++) {
        		preholding_data[j] = adc_data[j*istride3 + k*idist3];
        	}
        	
        	fftwf_execute(plan3);
        	
        	for (int i=0; i<N3; i++) {
				onlyRD_data[i*istride3 + k*idist3] = postholding_data[i];
			}
        }

    	
    }

	void remove_zero_dop(float* rdm_avg, float* zero_rdm_avg) {
	    for(int i=0; i<SLOW_TIME*FAST_TIME; i++) {
		zero_rdm_avg[i] = rdm_avg[i];
            }
	    for(int i=32; i<34; i++) {
		for(int j=0; j<FAST_TIME; j++) {
		    int idx = i*FAST_TIME + j;
		    zero_rdm_avg[idx] = 0;
                }
            }

	    //31-34 doppler frames need to be 0 out of 64, 
	}


	int compute_angle_est() {
	    fftwf_execute(plan2);
	    return 0;
	}

	int compute_angmag_norm(std::complex<float>* rdm_complex, float* rdm_magnitude) {
	    float norm, log;
	    std::complex<float> val; 
	    for(int i=0; i<256; i++) {
		val=rdm_complex[i];
		norm=std::norm(val);
		log=log2f(norm)/2.0f;
		rdm_magnitude[i]=log;
	    }         
	    return 0;
	    
	    float max = 0;
	    float min;
	    
	    for (int i=0; i<256; i++) {
	    	if (i==0) {
	    		max = rdm_magnitude[i];
	    		min = rdm_magnitude[i];
	    	}
	    	else {
	    		if (rdm_magnitude[i] > max) {
	    			max = rdm_magnitude[i];
	    		}
	    		if (rdm_magnitude[i] < min) {
	    			min = rdm_magnitude[i];
	    		}
	    		
	    	}
	    }
	    
	    if (min < 0) {
	    	min = 0;
	    }
	    
	    scale_rdm_values(rdm_magnitude, max, min);
	}

	
	void find_azimuth_angle(float* angle_norm, float* final_angle) {
	    float step = 180/64;
	    float data[64];
	    for(int i=0; i<64; i++) {
		data[i] = angle_norm[128+i];
	    }
	    float max = 0; //*std::max_element(data, data + 64);
	    int idxmax;
	    
	    for(int i=0; i<64; i++) {
	    	if (angle_norm[128+i] > max) {
	    		max = angle_norm[128+i];
	    		idxmax = i;
	    	}
	    }
	    
	    
	    float scale = (90 + 90) / (20 + 90);
	    float angle = step*idxmax - 90;
	    float transform = angle + 30;
	    final_angle[0] = angle;
	    

	}

/*
	void correlation_matrix(float* rdm_avg, float* prev_rdm_avg, float* cfar_cube, complex<float>* adc_data, int* cfar_max, complex<float>* Rmatrix, float* final_range) {

	    cfar_max[0] = cfar_matrix(rdm_avg, prev_rdm_avg, cfar_cube);
	    int maxidx = cfar_max[0];
	    
	    float multiplier = 9.0f / 256.0f;
	    float rangebin = (maxidx%FAST_TIME) * multiplier;
	    final_range[0] = rangebin;

	    complex<float> indices[12] = {0};
	    //getADCindices(maxidx, indices);
	    
	    getADCaverage(maxidx, indices, adc_data);

	    complex<float> xn_values[8] = {0};
	    for(int i=0; i<4; i++) {
		//xn_values[i] = adc_data[indices[i]];
		//xn_values[i+4] = adc_data[indices[i+4]];
		xn_values[i] = indices[i];
		xn_values[i+4] = indices[i+4];
	    }

	    // Create a 8 by 1 matrix from the array
	    Matrix<complex<float>,8,1> xnMat; // This is x[n]

	    // Initialize the matrix from the array
	    for (int i = 0; i < 8; ++i) {
		xnMat(i,0) = xn_values[i];
	    }
		Matrix<complex<float>,1,8> xnHermitian = xnMat.adjoint(); // This is xH[n]
		
		Matrix<complex<float>,8,8> corr_matrix = xnMat * xnHermitian;

	    for (size_t i = 0; i < 8; ++i) {
			for (size_t j = 0; j < 8; ++j) {
				int idx = i*8;
				Rmatrix[idx + j] = corr_matrix(i,j);
			}
	    }
	    
	    
	    output_energy(Rmatrix, cfar_max);
	

	}
	

	void output_energy(complex<float>* Rmatrix, int* cfar_max) {
		
	    Matrix<complex<float>,8,8> Rmat;
	    for (size_t i = 0; i < 8; ++i) {
			for (size_t j = 0; j < 8; ++j) {
				int idx = i*8;
				Rmat(i,j) = Rmatrix[idx + j];
			}
	    }
	    Matrix<complex<float>,8,8> RinvMat = Rmat.inverse();
	    
	    vector<vector<complex<float>>> steering(8, vector<complex<float>>(1));
	    Matrix<complex<float>,8,1> steer;
	    vector<complex<float>> outpower;
	    
	    
	    for (int ang = -90; ang < 92; ang+=2) {
	    	vector<vector<complex<float>>> steering_vect = steering_mat(steering, ang);

	    	for (size_t i = 0; i < 8; ++i) {
				steer(i,0) = steering_vect[i][0];
			}
			Matrix<complex<float>,1,8> conjtrans = steer.adjoint();
			Matrix<complex<float>,1,1> someMatrix = conjtrans * RinvMat * steer;
			complex<float> complexOne(1,0);
			
			complex<float> outputpower = complexOne / someMatrix(0,0);
			outpower.push_back(outputpower);
	    }
	    
	    float powermag = 0;
	    int idxmaxmag;
	    
	    for (int i = 0; i < outpower.size(); i++) {
	    	float magnitude = abs(outpower[i]);
	    	if (magnitude > powermag) {
	    		powermag = magnitude;
	    		idxmaxmag = i;
	    	}
	    	
	    }

		std::cout << "Index of the complex number with the maximum magnitude: " << idxmaxmag*2 - 90 << std::endl;
		//cfar_max[0] = idxmaxmag*2 - 90;
		
	}

	vector<vector<complex<float>>> steering_mat(vector<vector<complex<float>>>& matrix, int angle) {
	
	    complex<float> im(0.0,1.0);
	    double anglerad = angle * (M_PI / 180);
	    float sineval = sin(anglerad);
	    float NPI = n_pi;
	    for (size_t i = 0; i < matrix.size(); ++i) {
			float inc = i;
			matrix[i][0] = exp(-im*NPI*sineval*inc);
	    }

	    return matrix;
	
	}
*/

	void correlation_matrix(float* rdm_avg, float* prev_rdm_avg, float* cfar_cube, complex<float>* adc_data, int* cfar_max, complex<float>* Rmatrix, float* final_range, float* final_angle) {

	    cfar_max[0] = cfar_matrix(rdm_avg, prev_rdm_avg, cfar_cube);
	    int maxidx = cfar_max[0];

		const int range_bin = (maxidx % FAST_TIME);
		const int RD_bins = SLOW_TIME*FAST_TIME;
		
		Matrix<complex<float>,12,12> sum_mat;
		sum_mat.setZero();
		
		
		for (int j=range_bin; j<RD_bins; j+=FAST_TIME) {
		
			complex<float> xn_values[12] = {0};
			getADCaverage(j, xn_values, adc_data);

			// Create a 8 by 1 matrix from the array
			Matrix<complex<float>,12,1> xnMat; // This is x[n]

			// Initialize the matrix from the array
			for (int i = 0; i < 12; ++i) {
			xnMat(i,0) = xn_values[i];
			}
			Matrix<complex<float>,1,12> xnHermitian = xnMat.adjoint(); // This is xH[n]
			Matrix<complex<float>,12,12> corr_matrix = xnMat * xnHermitian;
			
			sum_mat = sum_mat + corr_matrix;
		
		}

		complex<float> complexsixfour(64,0);
	    for (size_t i = 0; i < 12; ++i) {
			for (size_t j = 0; j < 12; ++j) {
				int idx = i*12;
				Rmatrix[idx + j] = sum_mat(i,j) / complexsixfour;
			}
	    }
	    
	    output_energy(Rmatrix, cfar_max, final_angle);
	

	}

	void output_energy(complex<float>* Rmatrix, int* cfar_max, float* final_angle) {
		
	    Matrix<complex<float>,12,12> Rmat;
	    for (size_t i = 0; i < 12; ++i) {
			for (size_t j = 0; j < 12; ++j) {
				int idx = i*12;
				Rmat(i,j) = Rmatrix[idx + j];
			}
	    }
	    Matrix<complex<float>,12,12> RinvMat = Rmat.inverse();

	    vector<complex<float>> outpower;
	    
	    for (int ang = -90; ang < 91; ang+=1) {

			Matrix<complex<float>,12,1> steer = steering_mat(ang);

			Matrix<complex<float>,1,12> conjtrans = steer.adjoint();

			Matrix<complex<float>,1,1> someMatrix = conjtrans * RinvMat * steer;

			complex<float> complexOne(1,0);
			

			complex<float> outputpower = complexOne / someMatrix(0,0);
			outpower.push_back(outputpower);
	    }
	   
	    
	    float powermag = 0;
	    int idxmaxmag;

	    for (int i = 0; i < outpower.size(); i++) {
	    	float magnitude = abs(outpower[i]);
	    	if (magnitude > powermag) {
	    		powermag = magnitude;
	    		idxmaxmag = i;
	    	}
	    	
	    }
	    

		std::cout << "Index of the complex number with the maximum magnitude: " << idxmaxmag - 90 << std::endl;
		//cfar_max[0] = idxmaxmag*2 - 90;
		final_angle[0] = idxmaxmag - 90;
	}


	Matrix<complex<float>,12,1> steering_mat(int angle) {
	
		complex<float> im(0.0,1.0);
	    double anglerad = angle * (M_PI / 180);
	    float sineval = sin(anglerad);
	    float cosval = cos(anglerad);
	    double elev_angle = 0 * (M_PI / 180);
	    float sinelev = sin(elev_angle);
	    float coselev = cos(elev_angle);
	    float NPI = n_pi;
	    
		Matrix<complex<float>,12,1> matrix;
		Matrix<complex<float>,16,1> matrix16;

		int count = 0;
		for (int n = 0; n < 8; n++) {
			for (int k = 0; k < 2; k++) {
			float nf = n;
			float kf = k;
			matrix16(count,0) = exp(im*NPI*(nf*sineval*coselev + kf*sineval*sinelev));
			count = count + 1;
			}
		}
		
		//int idx[] = {1, 3, 13, 15};
		int idx[] = {1,3,4,5,6,7,8,9,10,11,13,15};
		int idxsize = sizeof(idx) / sizeof(idx[0]);
		for (int i = 0; i < idxsize; i++) {
			matrix(i,0) = matrix16(idx[i],0);
		}
		
		/*
	    for (size_t i = 0; i < matrix.size(); ++i) {
			float inc = i;
			matrix(i,0) = exp(-im*NPI*sineval*inc);
	    }
	    */

	    return matrix;
	
	}

	void getADCaverage(int index_1D, complex<float>* xnvalues, complex<float>* adc_data) {
	    const int RD_bins = SLOW_TIME*FAST_TIME;
	    for(int i=0; i<TX*RX; i++) {
			xnvalues[i] = adc_data[i*RD_bins + index_1D];
		}
	    
	}

	float* getRangeBufferPointer()
	{
	    return final_range; // getting range values
	}

	float* getAngleBufferPointer()
	{
	    return final_angle; // find_azimuth_angle(angle_norm);
	}

	int* getAngleIndexPointer()
	{
	    return cfar_max; // find_azimuth_angle(angle_norm);
	}
	
	float* getAngleMapPointer()
	{
	    return angle_norm; // getting range values
	}

	// Still need to fix this fftshift issue
	void fftshift_ang_est(float* arr){
	    int midRow = 64 / 2;
	    int midColumn = 4 / 2;
	    float fftshifted[256];
	    
	    for (int i = 0; i < 64; i++) {
		for (int j = 0; j < 4; j++) {
		    int newRow = (i + midRow) % 64;          // ROW WISE FFTSHIFT
		    int newColumn = (j + midColumn) % 4;    // COLUMN WISE FFTSHIFT
		    fftshifted[newRow * 4 + j] = arr[i * 4 + j]; // only newRow is used so only row wise fftshift
		}
	    }
	    for(int i = 0; i < 256; i++)
		arr[i] = fftshifted[i];
	}

/*
        void fftshift_rdm(float* arr){
            int midRow = FAST_TIME / 2;
            int midColumn = SLOW_TIME / 2;
            float fftshifted[SLOW_TIME*FAST_TIME];
           
            for (int i = 0; i < FAST_TIME; i++) {
                for (int j = 0; j < SLOW_TIME; j++) {
                    int newRow = (i + midRow) % FAST_TIME;          // ROW WISE FFTSHIFT
                    int newColumn = (j + midColumn) % SLOW_TIME;    // COLUMN WISE FFTSHIFT
                    fftshifted[newRow * SLOW_TIME + j] = arr[i * SLOW_TIME + j]; // only newRow is used so only row wise fftshift
                }
            }
            for(int i = 0; i < FAST_TIME*SLOW_TIME; i++)
                arr[i] = fftshifted[i];
        }
*/


	int cfar_matrix(float* rdm_avg, float* prev_rdm_avg, float* cfar_cube) {
	    for(int i=0; i<SLOW_TIME*FAST_TIME; i++) {
		cfar_cube[i] = rdm_avg[i] - prev_rdm_avg[i];
	    }
	    float max = *std::max_element(cfar_cube, cfar_cube + SLOW_TIME*FAST_TIME);
	    float threshold = max;
	    for(int i=0; i<SLOW_TIME*FAST_TIME; i++) {
		if (cfar_cube[i] >= threshold) {
		    cfar_cube[i] = 1;
		    return i;
		}
		else {
		    cfar_cube[i] = 0;
		}
	    }
	    
	}
	

	void getADCindices(int index_1D, int* indices) {
	    const int RD_bins = SLOW_TIME*FAST_TIME;
	    for(int i=0; i<TX*RX; i++) {
		indices[i] = i*RD_bins + index_1D;
	    }
	}


	float mean_noise_rdm(float* rdm_avg) {
	    float MNF = 0;
	    for(int i=0; i<SLOW_TIME*FAST_TIME; i++) {
		MNF = MNF + rdm_avg[i];
	    }
	    MNF = MNF/(SLOW_TIME*FAST_TIME);
	    return MNF;
	}


	void shape_angle_data(float* rdm_avg, float* prev_rdm_avg, float* cfar_cube, std::complex<float>* adc_data, std::complex<float>* angle_data, int* cfar_max, float* final_range) {

	    cfar_max[0] = cfar_matrix(rdm_avg, prev_rdm_avg, cfar_cube);
	    int maxidx = cfar_max[0];
	    
	    float multiplier = 9.0f / 256.0f;
	    float rangeval = (maxidx%FAST_TIME) * multiplier;
	    final_range[0] = rangeval;
	    
	    //std::cout << "max index: " << maxidx%FAST_TIME << std::endl;

	    int indices[12] = {0};
	    getADCindices(maxidx, indices);
	    
	    //Basically have a 4x64 structure with row 1 and 4 zero padded and columns 1-28 and 35-64 zero padded

	    for(int i=0; i<64; i++) {
		angle_data[i] = 0;
		angle_data[i+192] = 0;
	    }
	    
	    for(int i=0; i<64; i++) {
		if(i<30 || i>33) {
		    angle_data[i+64] = 0;
		}
		else {
		    angle_data[i+64] = adc_data[indices[4 + (i-30)]];
		}
		if(i<28 || i>35) {
		    angle_data[i+128] = 0;
		}
		else if(i>=28 && i<32){
		    angle_data[i+128] = adc_data[indices[8 + (i-28)]];
		}
		else {
		    angle_data[i+128] = adc_data[indices[0 + (i-32)]];
		}

	    }

	}

        // Retrieve outputbuffer pointer
        float* getBufferPointer()
        {
            return zero_rdm_avg;
        }

        void setBufferPointer(uint16_t* arr){
            input = arr;
        }

        // FILE READING METHODS
        void readFile(const std::string& filename) {      //
            std::ifstream file(filename);
            if (file.is_open()) {
                std::string line;
                
                int i = 0;
                while (std::getline(file, line)) {
                    if(i > SIZE_W_IQ){
                        std::cerr << "Error: More samples than SIZE " << filename << std::endl;
                        break;
                    }
                    float value = std::stof(line);
                    adc_data_flat[i] = value;
                    i++;
                }
                std::cout << "File Successfully read!" << std::endl;
                file.close();
            } else {
                std::cerr << "Error: Could not open file " << filename << std::endl;
            }
        }

        int save_1d_array(float* arr, int width, int length, string& filename) {
            std::ofstream outfile(filename);
            for (int i=0; i<length*width; i++) {
                outfile << arr[i] << std::endl;
            }

            //outfile.close();
            std::cout << "Array saved to file. " << std::endl;
            return 0;
        }
        
        // WINDOW TYPES
        void blackman_window(float* arr, int fast_time){
            for(int i = 0; i<fast_time; i++)
                arr[i] = 0.42 - 0.5*cos(2*M_PI*i/(fast_time-1))+0.08*cos(4*M_PI*i/(fast_time-1));
        }

        void hann_window(float* arr, int fast_time){
            for(int i = 0; i<fast_time; i++)
                arr[i] = 0.5 * (1 - cos((2 * M_PI * i) / (fast_time - 1)));
        }
        
        void no_window(float* arr, int fast_time){
            for(int i = 0; i<fast_time; i++)
                arr[i] = 1;
        }
        
        void setSNR(float maxSNR, float minSNR){
            SET_SNR = true;
            max = maxSNR;
            min = minSNR;
        }
        // output indices --> {IQ, FAST_TIME, SLOW_TIME, RX, TX}
        void getIndices(int index_1D, int* indices){
            int i0 = index_1D/(RX*IQ*FAST_TIME*TX);
            int i1 = index_1D%(RX*IQ*FAST_TIME*TX);
            int i2 = i1%(RX*IQ*FAST_TIME);
            int i3 = i2%(RX*IQ);
            int i4 = i3%(RX);
            
            indices[2] = i0;                    // SLOW_TIME | Chirp#
            indices[0] = i1/(RX*IQ*FAST_TIME);  // TX#
            indices[3] = i2/(RX*IQ);            // FAST_TIME | Range#
            indices[4] = i3/(RX);                 // IQ
            indices[1] = i4;                    // RX#
        }

        void shape_cube(float* in, float* mid, std::complex<float>* out) { 
            int rx=0;
            int tx=0;
            int iq=0;
            int fast_time=0;
            int slow_time=0;
            int indices[5] = {0};
            float window[FAST_TIME];
            if(strcmp(WINDOW_TYPE,"blackman") == 0)
                blackman_window(window, FAST_TIME);
            else if(strcmp(WINDOW_TYPE,"hann") == 0)
                hann_window(window, FAST_TIME);
            else
                no_window(window, FAST_TIME);
            
            for (int i =0; i<SIZE_W_IQ; i++) {
                getIndices(i, indices);
                tx=indices[0]*RX*SLOW_TIME*FAST_TIME*IQ;
                rx=indices[1]*SLOW_TIME*FAST_TIME*IQ;
                slow_time=indices[2]*FAST_TIME*IQ;
                fast_time=indices[3]*IQ;
                iq=indices[4];
                mid[tx+rx+slow_time+fast_time+iq]=in[i]*window[fast_time/IQ];
            }

            for(int i=0; i<SIZE; i++){
                out[i]=std::complex<float>(mid[2*i+0], mid[2*i+1]);
            }
        }

        int compute_range_doppler() {
            fftwf_execute(plan);
            return 0;
        }

        
        void scale_rdm_values(float* arr, float max_val, float min_val){
            // fill in the matrix with the values scaled to 0-255 range
            for (int i = 0; i < FAST_TIME*SLOW_TIME; i++) {
                arr[i] = (arr[i] - min_val) / (max_val - min_val) * 255;
                if (arr[i] < 0)
                    arr[i] = 0; 
            }
        }

        void fftshift_rdm(float* arr){
            int midRow = FAST_TIME / 2;
            int midColumn = SLOW_TIME / 2;
            float fftshifted[SLOW_TIME*FAST_TIME];
           
            for (int i = 0; i < FAST_TIME; i++) {
                for (int j = 0; j < SLOW_TIME; j++) {
                    int newRow = (i + midRow) % FAST_TIME;          // ROW WISE FFTSHIFT
                    int newColumn = (j + midColumn) % SLOW_TIME;    // COLUMN WISE FFTSHIFT
                    fftshifted[newRow * SLOW_TIME + j] = arr[i * SLOW_TIME + j]; // only newRow is used so only row wise fftshift
                }
            }
            for(int i = 0; i < FAST_TIME*SLOW_TIME; i++)
                arr[i] = fftshifted[i];
        }

        int compute_mag_norm(std::complex<float>* rdm_complex, float* rdm_magnitude) {
            float norm, log;
            std::complex<float> val; 
            for(int i=0; i<SIZE; i++) {
                val=rdm_complex[i];
                norm=std::norm(val);
                log=log2f(norm)/2.0f;
                rdm_magnitude[i]=log;
            }         
            return 0;
        }
        // rdm_avg should be zero-filled
        int averaged_rdm(float* rdm_norm, float* rdm_avg) {
            int idx;
            const int VIRT_ANTS = TX*RX;
            const int RD_BINS = SLOW_TIME*FAST_TIME;
            if(!SET_SNR){
                float max, min;
            }
            for (int i=0; i<(VIRT_ANTS); i++) {
                for (int j=0; j<(RD_BINS); j++) {
                    idx=i*(RD_BINS)+j;
                    if(i==0)
                        rdm_avg[j] = 0;
                    rdm_avg[j]+=rdm_norm[idx]/((float) RD_BINS);
                    if(i == (VIRT_ANTS-1) && !SET_SNR){
                        if (j==0){
                            max = rdm_avg[0];
                            min =  rdm_avg[0];                            
                        }

                        if (rdm_avg[j] > max)
                            max = rdm_avg[j];
                        else if(rdm_avg[j] < min)
                            min = rdm_avg[j];
                        
                    }
                }
            }

            //std::cout << "MAX: " << max << "      |        MIN:  " << min << std::endl;
            
            scale_rdm_values(rdm_avg, max, min);
            fftshift_rdm(rdm_avg);
            return 0;   
        }
        
        void process() override
        {
        	auto start = chrono::high_resolution_clock::now();

            for(int i = 0; i<SIZE_W_IQ; i++){
                adc_data_flat[i] = (float)input[i];
            }
	    if (frame <=1) {
		for(int i=0; i<SLOW_TIME*FAST_TIME; i++) {
		    prev_rdm_avg[i] = 0;
	        }
	    }
	    else {
		for(int i=0; i<SLOW_TIME*FAST_TIME; i++) {
		    prev_rdm_avg[i] = zero_rdm_avg[i];
	        }
	    }
            shape_cube(adc_data_flat, adc_data_reshaped, adc_data);
            compute_range_doppler();
            compute_mag_norm(rdm_data, rdm_norm);
            averaged_rdm(rdm_norm, rdm_avg);
	    remove_zero_dop(rdm_avg, zero_rdm_avg);
	    //compute_doppler_fft(adc_data, onlyRD_data, preholding_data, postholding_data);
	    compute_range_fft(adc_data, onlyRD_data, preholding_data, postholding_data);
	    shape_angle_data(zero_rdm_avg, prev_rdm_avg, cfar_cube, onlyRD_data, angle_data, cfar_max, final_range);
	    //correlation_matrix(zero_rdm_avg, prev_rdm_avg, cfar_cube, onlyRD_data, cfar_max, Rmatrix, final_range, final_angle);
	    compute_angle_est();
	    compute_angmag_norm(angfft_data, angle_norm);
	    //fftshift_ang_est(angle_norm);
	    find_azimuth_angle(angle_norm, final_angle);
	    

            // string str = ("./out") + to_string(frame) + ".txt";
            // save_1d_array(rdm_avg, FAST_TIME, SLOW_TIME, str);

             auto stop = chrono::high_resolution_clock::now();
             auto duration_rdm_process = duration_cast<microseconds>(stop - start);
             std::cout << "RDM Process Time " << duration_rdm_process.count() << " microseconds" << std::endl;
	    
	    frame ++;
	    std::cout << "Frame: " << frame << std::endl;
        }

        private: 
            float *adc_data_flat, *rdm_avg, *rdm_norm, *adc_data_reshaped, *cfar_cube, *angle_norm, *final_angle, *final_range, *prev_rdm_avg, *zero_rdm_avg;
            std::complex<float> *rdm_data, *adc_data, *angle_data, *angfft_data, *Rmatrix, *onlyRD_data, *preholding_data, *postholding_data;
            fftwf_plan plan, plan2, plan3;
	    int *cfar_max;
            uint16_t* input;
            const char *WINDOW_TYPE;
            bool SET_SNR;
            float max,min;
        
};

// Data Acquisition class 
class DataAcquisition : public RadarBlock
{ 
    public:
        DataAcquisition() : RadarBlock(SIZE,SIZE)
        {
            
            frame_data = reinterpret_cast<uint16_t*>(malloc(SIZE_W_IQ*sizeof(uint16_t)));
            BYTES_IN_FRAME = SLOW_TIME*FAST_TIME*RX*TX*IQ*IQ_BYTES;
            BYTES_IN_FRAME_CLIPPED = BYTES_IN_FRAME/BYTES_IN_PACKET*BYTES_IN_PACKET;
            PACKETS_IN_FRAME_CLIPPED = BYTES_IN_FRAME / BYTES_IN_PACKET;
            UINT16_IN_PACKET = BYTES_IN_PACKET / 2; //728 entries in packet
            UINT16_IN_FRAME = BYTES_IN_FRAME / 2;
            packets_read = 0;
            buffer=reinterpret_cast<char*>(malloc(BUFFER_SIZE*sizeof(char)));
            packet_data=reinterpret_cast<uint16_t*>(malloc(UINT16_IN_PACKET*sizeof(uint16_t)));     
        }

        // create_bind_socket - returns a socket object titled sockfd
        int create_bind_socket(){
            // Create a UDP socket file descriptor which is UNbounded
            if ((sockfd = socket(AF_INET, SOCK_DGRAM, 0)) <  0){
                perror("Socket creation failed"); 
                exit(EXIT_FAILURE);
            }

            memset(&servaddr, 0, sizeof(servaddr)); 
            memset(&cliaddr, 0, sizeof(cliaddr)); 

            // Filling in the servers (DCA1000EVMs) information
            servaddr.sin_family     = AF_INET;      //this means it is a IPv4 address
            servaddr.sin_addr.s_addr= INADDR_ANY;   //sets address to accept incoming messages
            servaddr.sin_port       = htons(PORT);  //port number to accept from
            
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
        
        void close_socket(){
            close(sockfd);
        }

        // read_socket will generate the buffer object that holds all raw ADC data
        void read_socket(){
            auto start = chrono::high_resolution_clock::now();
            // n is the packet size in bytes (including sequence number and byte count)

            n = recvfrom(sockfd, buffer, BUFFER_SIZE, 0, (struct sockaddr *)&cliaddr, &len);
            buffer[n] = '\0'; // Null-terminate the buffer
            // auto stop = chrono::high_resolution_clock::now();
            // auto duration_read_socket = duration_cast<microseconds>(stop - start);
            // std::cout << "Read Socket " << duration_read_socket.count() << std::endl;

            // start = chrono::high_resolution_clock::now();

            // stop = chrono::high_resolution_clock::now();
            // auto duration_set_packet_data = duration_cast<microseconds>(stop - start);
            // std::cout << "Set Packet Data " << duration_set_packet_data.count() << std::endl;
        }

        // get_packet_num will look at the buffer and return the packet number
        uint32_t get_packet_num(){
            uint32_t packet_number = ((buffer[0] & 0xFF) << 0)  |
                                    ((buffer[1] & 0xFF) << 8)  |
                                    ((buffer[2] & 0xFF) << 16) |
                                    ((long) (buffer[3] & 0xFF) << 24);
            return packet_number;
        }
        // get_byte_count will look at the buffer and return the byte count of the packet
        uint64_t get_byte_count(){
            uint64_t byte_count = ((buffer[4] & 0xFF) << 0)  |
                                ((buffer[5] & 0xFF) << 8)  |
                                ((buffer[6] & 0xFF) << 16) |
                                ((buffer[7] & 0xFF) << 24) |
                                ((unsigned long long) (buffer[8] & 0xFF) << 32) |
                                ((unsigned long long) (buffer[9] & 0xFF) << 40) |
                                ((unsigned long long) (0x00) << 48) |
                                ((unsigned long long) (0x00) << 54);
            return byte_count;
        }

        /*void set_packet_data(){
            // printf("Size of packet data = %d \n", BYTES_IN_PACKET);
            for (int i = 0; i< UINT16_IN_PACKET; i++)
            {
                packet_data[i] =  buffer[2*i+10] | (buffer[2*i+11] << 8);
            }
        }*/

        void set_frame_data(){
            //Add packet_data to frame_data
            for (int i = UINT16_IN_PACKET*packets_read; i < (UINT16_IN_PACKET*(packets_read+1)); i++)
            {
                frame_data[i] = buffer[2*(i-UINT16_IN_PACKET*packets_read)+10] | (buffer[2*(i-UINT16_IN_PACKET*packets_read)+11] << 8);
                // frame_data[i] = packet_data[i%UINT16_IN_PACKET];
                
            }
            packets_read++;
        }

        int end_of_frame(){
            uint64_t byte_mod = (packets_read*BYTES_IN_PACKET) % BYTES_IN_FRAME_CLIPPED;
            if (byte_mod == 0) //end of frame found
                return 1;           
            return 0;
        }

        int save_1d_array(uint16_t* arr, int width, int length, string& filename) {
            std::ofstream outfile(filename);
            for (int i=0; i<length*width; i++) {
                outfile << arr[i] << std::endl;
            }

            //outfile.close();
            std::cout << "Array saved to file. " << std::endl;
            return 0;
        }


        uint16_t* getBufferPointer(){
            return frame_data;
        }

        void listen() override
        {
             for(;;)
            {
                if(frame==0){
                    break;
                }
                if(*inputframeptr != lastframe)
                {   
                    lastframe = *inputframeptr;
                    break;
                }
            }
        }

        void process() override
        {

            auto start = chrono::high_resolution_clock::now();

            create_bind_socket();
            

            // while true loop to get a single frame of data from UDP 
            // std::cout<< "DAQ PROCESS ACTIVATED" << std::endl;
            // std::cout << "FRAME #: " << frame << "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~" << std::endl;
            //start = chrono::high_resolution_clock::now();
            while (true)
                {
                    read_socket();
                    //start = chrono::high_resolution_clock::now();
                    set_frame_data();
                    //stop = chrono::high_resolution_clock::now();
                    //duration_set_frame_data = duration_cast<microseconds>(stop - start);
                    //std::cout << "Set Frame Data " << duration_set_frame_data.count() << std::endl;
                    //std::cout << std::endl;   
 
                    if (end_of_frame() == 1){
                        //string str = ("./out") + to_string(frame) + ".txt";
                        // save_1d_array(frame_data, FAST_TIME*TX*RX*IQ_DATA, SLOW_TIME, str);
                        packets_read = 0;
                        // first_packet = true;
                        //start = chrono::high_resolution_clock::now();

                        close_socket();
                        //stop = chrono::high_resolution_clock::now();
                        //auto duration_close_socket = duration_cast<microseconds>(stop - start);

                        break;
                    }
                }
            //auto stop = chrono::high_resolution_clock::now();
            //auto duration = duration_cast<microseconds>(stop - start);
            //std::cout << "Create Socket " << duration_create_socket.count() << std::endl;
            //std::cout << std::endl;
            // auto stop = chrono::high_resolution_clock::now();
            // auto duration = duration_cast<microseconds>(stop - start);
            // std::cout << "Process Time " << duration.count() << std::endl;
            // std::cout << std::endl;
            auto stop = chrono::high_resolution_clock::now();
            auto duration_daq_process = duration_cast<microseconds>(stop - start);
            std::cout << "DAQ Process Time " << duration_daq_process.count() << " microseconds" << std::endl;
            std::cout << "~~~~~~~~~~~~~~~~~~~END OF SINGLE FRAME~~~~~~~~~~~~~~~~~~~~" << std::endl;


        }

        private:  
            
            int sockfd;                             // socket file descriptor
            struct sockaddr_in servaddr, cliaddr;   // initialize socket
            socklen_t len;
            
            char* buffer;
            int n;  // n is the packet size in bytes (including sequence number and byte count)
            
            uint16_t *packet_data, *frame_data;  
            uint32_t packet_num;
            uint64_t BYTES_IN_FRAME, BYTES_IN_FRAME_CLIPPED, PACKETS_IN_FRAME_CLIPPED, UINT16_IN_PACKET, UINT16_IN_FRAME, packets_read;
            
            std::complex<float> *rdm_data, *adc_data;
            float *adc_data_flat, *rdm_avg, *rdm_norm, *adc_data_reshaped;
            
        
};
