#ifndef VISUALIZER_H
#define VISUALIZER_H

#include "RadarBlock.h"
#include <opencv4/opencv2/core.hpp>

// 1024 x 600
// Visualizes range-doppler data
class Visualizer : public RadarBlock {
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
        Visualizer(int size_in, int size_out, bool verbose = false); 
        void process() override;
        void setWaitTime(int num);
        void listen() override;

    private:
        cv::Mat image;
        cv::Mat borderedImage;
        cv::Mat colorImage;
        int wait_time;
};

#endif