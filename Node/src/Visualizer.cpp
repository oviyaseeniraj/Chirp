#include "Visualizer.h"
#include "main.h"
#include <chrono>
#include <opencv2/opencv.hpp>

Visualizer::Visualizer(int size_in, int size_out, bool verbose) : RadarBlock(size_in, size_out, verbose),
                                                                  image(px_height * height / 2, px_width * width, CV_8UC1, cv::Scalar(255))
{
    frame = 1;
    cv::namedWindow("Image", cv::WINDOW_NORMAL);
    cv::setWindowProperty("Image", cv::WND_PROP_FULLSCREEN, cv::WINDOW_NORMAL);
}

void Visualizer::process()
{
    auto start = std::chrono::high_resolution_clock::now();

    // if(frame <= 1){
    cv::Scalar borderColor(0, 0, 0);

    // Add the padded border
    // TOP | BOTTOM | LEFT | RIGHT
    cv::copyMakeBorder(image, borderedImage, borderSize, borderSize, borderLeft, borderRight,
                       cv::BORDER_CONSTANT, borderColor);

    cv::Point zeroZero(0, 0);
    cv::Point maxMax(1080, 632);

    cv::rectangle(borderedImage, zeroZero, maxMax, borderColor, -1);

    cv::Point xEnd(borderedImage.cols - borderLeft, borderedImage.rows - borderSize);
    cv::Point yEnd(borderLeft, borderSize);

    cv::Point originRDM(120, 316);
    cv::Point xEndRDM(440, 316);
    cv::Point yEndRDM(120, 60);

    cv::Point originXY(640, 316);
    cv::Point cornerXY(960, 60);
    cv::rectangle(borderedImage, originXY, cornerXY, borderColor, -1);
    cv::Point origin(borderLeft, borderedImage.rows - borderSize);
    // cv::line(borderedImage, originRDM, xEndRDM, cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);
    //		//cv::line(borderedImage, originRDM, yEndRDM, cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);

    cv::rectangle(borderedImage, originRDM, cv::Point(440, 60), cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);
    cv::rectangle(borderedImage, originXY, cornerXY, cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);

    cv::rectangle(borderedImage, cv::Point(795, 321), cv::Point(805, 311), cv::Scalar(130, 34, 34), -1);

    std::string label_x = "-     Velocity     +";
    std::string label_RDM = "RDM";
    std::string label_XY = "XY Plot";
    std::string label_xXY = "x position";

    int fontFace = cv::FONT_HERSHEY_SIMPLEX;
    double fontScale = 1.0;
    int thickness = 4;
    int baseline = 0;

    cv::Size textSize = cv::getTextSize(label_x, fontFace, fontScale, thickness, &baseline);
    // cv::Point textPosition_x((image.cols - textSize.width)/2, image.rows - baseline - 10);
    // madness begins here
    cv::Point textPosition_x(110, 370);
    cv::Point textPosition_RDM(240, 50);

    cv::Point textPosition_XY(240 + 500, 50);
    cv::Point textPosition_xXY(110 + 600, 370);

    cv::Point textPosition_r(50, 130);
    cv::Point textPosition_a(50, 160);
    cv::Point textPosition_n(50, 190);
    cv::Point textPosition_g(50, 220);
    cv::Point textPosition_e(50, 250);

    cv::Point textPosition_y(50 + 520, 60);
    cv::Point textPosition_p(50 + 520, 120);
    cv::Point textPosition_o(50 + 520, 150);
    cv::Point textPosition_s(50 + 520, 180);
    cv::Point textPosition_i(50 + 520, 210);
    cv::Point textPosition_t(50 + 520, 240);
    cv::Point textPosition_i2(50 + 520, 270);
    cv::Point textPosition_o2(50 + 520, 300);
    cv::Point textPosition_n2(50 + 520, 330);

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

    // cv::Point textPosition_ang(borderLeft - 200, (borderedImage.rows-60+4*(textSize.height+24))/2);
    // cv::putText(borderedImage, "F", textPosition_ang, fontFace, fontScale, cv::Scalar(169, 169, 169), thickness);
    cv::Point textPosition_angtxt(borderLeft + 650, (borderedImage.rows - 60 + 2 * (textSize.height + 300)) / 2); // Angle
                                                                                                                  // cv::putText(borderedImage, "Est. Angle (Degrees)", textPosition_angtxt, cv::FONT_HERSHEY_PLAIN, 1.0, cv::Scalar(169, 169, 169), 2); //  ANGLE VISUALIZER

    for (int i = -5; i <= 5; i += 1)
    {
        std::ostringstream stream;
        stream << std::fixed << std::setprecision(0) << i;
        cv::Point pt(i * 32 + 160 + 220 - 100, 316);
        cv::line(borderedImage, pt, pt - cv::Point(0, -5), cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);
        cv::putText(borderedImage, stream.str(), pt + cv::Point(-10, 20),
                    cv::FONT_HERSHEY_SIMPLEX, 0.5, cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);

        cv::line(borderedImage, pt + cv::Point(520, 0), pt - cv::Point(0, -5) + cv::Point(520, 0), cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);
        cv::putText(borderedImage, stream.str(), pt + cv::Point(-10, 20) + cv::Point(520, 0),
                    cv::FONT_HERSHEY_SIMPLEX, 0.5, cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);
    }
    for (int i = 0; i <= 9; i += 1)
    {
        std::ostringstream stream;
        stream << std::fixed << std::setprecision(0) << 9 - i;
        cv::Point pt(220 - 100, i * 28 + 60);
        cv::line(borderedImage, pt, pt + cv::Point(-5, 0), cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);
        cv::putText(borderedImage, stream.str(), pt + cv::Point(-30, 10),
                    cv::FONT_HERSHEY_SIMPLEX, 0.5, cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);

        cv::line(borderedImage, pt + cv::Point(520, 0), pt + cv::Point(-5, 0) + cv::Point(520, 0), cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);
        cv::putText(borderedImage, stream.str(), pt + cv::Point(-30, 10) + cv::Point(520, 0),
                    cv::FONT_HERSHEY_SIMPLEX, 0.5, cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);
    }

    /*for (int i = 90; i >= -90; i -= stepSizeAng) { //angle scale
                std::ostringstream stream;
                stream << std::fixed << std::setprecision(0) << i;
                cv::Point pt(origin.x + 65+720, origin.y - 512/2 + i*2.875);
                cv::line(borderedImage, pt, pt + cv::Point(5, 0), cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 5);
                cv::putText(borderedImage, stream.str(), pt,
                            cv::FONT_HERSHEY_SIMPLEX, 0.5, cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 2);
    }*/

    //}
    // cv::Point originXY(640,316);
    // cv::Point cornerXY(960, 60);
    // cv::rectangle(borderedImage, originXY, cornerXY, cv::Scalar(0,0,0), -1);

    int half_offset = 0;
    if (true)
        half_offset = height / 2;

    cv::Size textSize1 = cv::getTextSize("-           Velocity           +", cv::FONT_HERSHEY_SIMPLEX, 1.0, 4, 0);

    /*cv::Point textPosition_ang(borderLeft + 650, (borderedImage.rows-60+4*(textSize.height+24))/2); // OLD ANGLE VISUALIZER
    cv::line(borderedImage, textPosition_ang, textPosition_ang + cv::Point(150, 0), cv::Scalar(0, 0, 0), 70);
    float anglefloat = *inputangbufferptr;
    setprecision(1);
    std::string anglestr = to_string(anglefloat);
    cv::putText(borderedImage, anglestr, textPosition_ang, cv::FONT_HERSHEY_SIMPLEX, 1.0, cv::Scalar(169, 169, 169), 2); */

    cv::Point textPosition_slow(borderLeft + 200, 100 + (borderedImage.rows - 60 + 4 * (textSize1.height + 24)) / 2);
    cv::Point textPosition_fast(borderLeft + 200, 100 + (borderedImage.rows - 60 + 6 * (textSize1.height + 24)) / 2);
    // cv::line(borderedImage, textPosition_slow - cv::Point(150, 0), textPosition_slow + cv::Point(150, 0), cv::Scalar(0, 0, 0), 100);
    float anglefloat = *inputangbufferptr;
    int cfar_slow = *inputangindexptr / FAST_TIME;
    int cfar_fast = *inputangindexptr % FAST_TIME;
    float rangefloat = *inputrangebuffptr;
    std::setprecision(1);
    std::string anglestr = std::to_string(anglefloat);
    std::string slow_str = std::to_string(cfar_slow);
    std::string fast_str = std::to_string(cfar_fast);
    std::string rangestr = std::to_string(rangefloat);
    // std::string fast_str = to_string(*inputangindexptr);  // Testing out the MVDR Angle Estimation
    cv::putText(borderedImage, anglestr, textPosition_slow, cv::FONT_HERSHEY_SIMPLEX, 1.0, cv::Scalar(169, 169, 169), 2);
    // cv::putText(borderedImage, slow_str, textPosition_slow, cv::FONT_HERSHEY_SIMPLEX, 1.0, cv::Scalar(169, 169, 169), 2);
    // cv::putText(borderedImage, fast_str, textPosition_fast, cv::FONT_HERSHEY_SIMPLEX, 1.0, cv::Scalar(169, 169, 169), 2);
    cv::putText(borderedImage, rangestr, textPosition_fast, cv::FONT_HERSHEY_SIMPLEX, 1.0, cv::Scalar(169, 169, 169), 2);

    // took j to height/2 to height in order to cut Range on RDM in half
    for (int i = 0; i < width; i++)
    {
        for (int j = half_offset; j < height; j++)
        {
            for (int x = 0; x < px_width / 2; x++)
            {
                for (int y = 0; y < px_height / 2; y++)
                {
                    borderedImage.at<uint8_t>(px_height / 2 * (j - height / 2) + y + borderSize, px_width / 2 * i + x + borderLeft - 100) = static_cast<uint8_t>(inputbufferptr[width * (height) - ((width - 1) * height - height * i + j)]);
                }
            }
        }
    }
    cv::Point detection1(borderLeft - 100 + cfar_slow * px_width / 2 - px_width / 2, 316 - (cfar_fast * px_height / 2 - px_height / 2));
    cv::Point detection2(borderLeft - 100 + cfar_slow * px_width / 2, 316 - cfar_fast * px_height / 2);
    cv::rectangle(borderedImage, detection1, detection2, cv::Scalar(169, 169, 169), 3);

    float angrad = anglefloat * (M_PI / 180);
    int xcoord = 800 + rangefloat * sin(angrad) * 32;
    int ycoord = 316 - rangefloat * cos(angrad) * 28;

    cv::Point xyPoint(xcoord, ycoord);

    cv::line(borderedImage, xyPoint, xyPoint, cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 9);
    cv::line(borderedImage, cv::Point(800, 316), xyPoint, cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), 3);

    // cv::rectangle(borderedImage, xyPoint, xyPoint + cv::Point(2,2), cv::Scalar(AXES_COLOR, AXES_COLOR, AXES_COLOR), -1);
    // cv::line(borderedImage, xyPoint, xyPoint, cv::Scalar(0, 0, 0), 9);

    // cv::Rect roi(borderLeft, borderedImage.row - borderSize, px_width*width, px_height*height);
    // cv::Mat roiImage = borderedImage(roi);
    // Convert the matrix to a color image for visualization
    applyColorMap(borderedImage, colorImage, cv::COLORMAP_JET);
    // Display the color image
    imshow("Image", colorImage);

    // Waits 1ms
    cv::waitKey(wait_time);
    auto stop = std::chrono::high_resolution_clock::now();
    auto duration_vis_process = std::chrono::duration_cast<std::chrono::microseconds>(stop - start);
    std::cout << "VIS Process Time " << duration_vis_process.count() << " microseconds" << std::endl;
    frame++;
}

void Visualizer::setWaitTime(int num)
{
    wait_time = num;
}

void Visualizer::listen()
{
    return;
}