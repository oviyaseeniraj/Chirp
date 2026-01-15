#include "RadarBlock.h"
#include <stdio.h>
#include <typeinfo>
#include <iostream>
#include <chrono>

RadarBlock::RadarBlock(int size_in, int size_out, bool v) : outputbuffer(new float[size_out]) {
    inputsize = size_in;
    outputsize = size_out;
    verbose = v;
    printf("New %s created.\n", typeid(*this).name());
}

RadarBlock::~RadarBlock() {
    delete[] outputbuffer;
    printf("%s destroyed.\n", typeid(*this).name());
}

void RadarBlock::setBufferPointer(float *ptr) {
    inputbufferptr = ptr;
}

void RadarBlock::setRangeBufferPointer(float *ptr) {
    inputrangebuffptr = ptr;
}

void RadarBlock::setAngleBufferPointer(float *ptr) {
    inputangbufferptr = ptr;
}

void RadarBlock::setAngleIndexPointer(int *ptr) {
    inputangindexptr = ptr;
}

// Sets the input frame pointer
void RadarBlock::setFramePointer(unsigned int *ptr) {
    inputframeptr = ptr;
    lastframe = *ptr;
}

// Retrieve outputbuffer pointer
float* RadarBlock::getBufferPointer() {
    return outputbuffer;
}

// Retrieve frame pointer
unsigned int* RadarBlock::getFramePointer() {
    return &frame;
}

// Complete desired calculations / data manipulation
void RadarBlock::process() {
    printf("Process done!\n");
}

// Iterates
void RadarBlock::iteration() {
    for (;;) {
        listen();
        // start timer
        auto start = std::chrono::high_resolution_clock::now();
        process();
        // stop timer
        auto stop = std::chrono::high_resolution_clock::now();
        if (verbose) {
            // calculate elapsed time in microseconds
            auto duration = std::chrono::duration_cast<std::chrono::microseconds>(stop - start);
            // print elapsed time
            std::cout << "Elapsed time: " << duration.count() << " microseconds" << std::endl;
        }
        increment_frame();
    }
}

void RadarBlock::listen() {
    for (;;) {
        if (*inputframeptr != lastframe) {
            lastframe = *inputframeptr;
            break;
        }
    }
}

void RadarBlock::increment_frame() {
    frame++;
}