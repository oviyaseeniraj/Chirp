#ifndef MAIN_H
#define MAIN_H

#include <stdint.h>
#include <stdlib.h>
#include <cstring>
#include <arpa/inet.h> // inet_addr()
#include <stdio.h>
#include <errno.h>
#include <time.h>
#include <chrono>
#include <fstream>
#include <iostream>
#include <complex>
#include <unistd.h>

#define n_pi 3.14159265358979323846

// Initializes the number of fast time samples | # of range samples

#ifndef FAST_TIME
#define FAST_TIME 512 
#endif 

#ifndef SLOW_TIME
#define SLOW_TIME 64
#endif
                                   // Initializes the number of slow time samples | # of doppler samples
#define RX 4                                           // # of Rx
#define TX 3                                           // # of Tx
#define IQ 2                                           // Types of IQ (I and Q)
#define SIZE_W_IQ TX * RX * FAST_TIME * SLOW_TIME * IQ // Size of the total number of separate IQ sampels from ONE frame
#define SIZE TX * RX * FAST_TIME *SLOW_TIME            // Size of the total number of COMPLEX samples from ONE frame

#define CARRIER_FREQ 77e9       // Carrier frequency in Hz (77 GHz)
#define SPEED_OF_LIGHT 3e8      // Speed of light in m/s
#define LAMBDA (SPEED_OF_LIGHT / CARRIER_FREQ)  // Wavelength in meters (~0.0039m)
#define CHIRP_DURATION 100e-6   // Chirp duration in seconds (100 microseconds typical)
#define FRAME_PERIOD (SLOW_TIME * CHIRP_DURATION)  // Frame period = num_chirps * chirp_duration
#define MAX_VELOCITY (LAMBDA / (4.0 * CHIRP_DURATION))  // Maximum unambiguous velocity
#define VELOCITY_RES (2.0 * MAX_VELOCITY / SLOW_TIME)   // Velocity resolution per bin

#define BUFFER_SIZE 2048
#define PORT 4098
#define BYTES_IN_PACKET 1456 // Max packet size - sequence number and byte count = 1466-10

#define IQ_BYTES 2

#define IP "169.231.217.32" // server IP
#define SERVER_PORT 1210
#define MAXLINE 1024

#endif