#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <unistd.h>
#include "ftd2xx.h"

// MPSSE Commands
#define MPSSE_CMD_SET_DATA_BITS_LOWBYTE     0x80
#define MPSSE_CMD_DATA_OUT_BITS_NEG_EDGE    0x13
#define MPSSE_CMD_DATA_IN_BITS_POS_EDGE     0x22
#define MPSSE_CMD_SEND_IMMEDIATE            0x87

// SCL & SDA directions
#define DIRECTION_SCLOUT_SDAOUT             0x13
#define DIRECTION_SCLOUT_SDAIN              0x11

// SCL & SDA values
#define VALUE_SCLLOW_SDALOW                 0x00
#define VALUE_SCLLOW_SDAHIGH                0x02

// Data sizes
#define DATA_SIZE_8BITS                     0x07
#define DATA_SIZE_1BIT                      0x00

static FT_STATUS test_write8bits_read1bit(FT_HANDLE handle, uint8_t data_out, uint8_t *bit_in)
{
    FT_STATUS status;
    uint8_t buffer[32] = {0};
    uint8_t inBuffer[2] = {0};
    uint32_t noOfBytes = 0;
    DWORD noOfBytesTransferred;

    // Purge buffers
    status = FT_Purge(handle, FT_PURGE_RX | FT_PURGE_TX);
    if (status != FT_OK) {
        printf("Purge failed: %d\n", status);
        return status;
    }

    // Set direction: SCL and SDA as outputs
    buffer[noOfBytes++] = MPSSE_CMD_SET_DATA_BITS_LOWBYTE;
    buffer[noOfBytes++] = VALUE_SCLLOW_SDAHIGH;
    buffer[noOfBytes++] = DIRECTION_SCLOUT_SDAOUT;

    // Clock out 8 bits on negative edge
    buffer[noOfBytes++] = MPSSE_CMD_DATA_OUT_BITS_NEG_EDGE;
    buffer[noOfBytes++] = DATA_SIZE_8BITS;
    buffer[noOfBytes++] = data_out;

    // Set SDA to input mode before reading
    buffer[noOfBytes++] = MPSSE_CMD_SET_DATA_BITS_LOWBYTE;
    buffer[noOfBytes++] = VALUE_SCLLOW_SDALOW;
    buffer[noOfBytes++] = DIRECTION_SCLOUT_SDAIN;

    // Clock in 1 bit on positive edge
    buffer[noOfBytes++] = MPSSE_CMD_DATA_IN_BITS_POS_EDGE;
    buffer[noOfBytes++] = DATA_SIZE_1BIT;

    // Send immediate
    buffer[noOfBytes++] = MPSSE_CMD_SEND_IMMEDIATE;

    // Write command buffer
    status = FT_Write(handle, buffer, noOfBytes, &noOfBytesTransferred);
    if (status != FT_OK) {
        printf("Write failed: %d\n", status);
        return status;
    }

    if (noOfBytes != noOfBytesTransferred) {
        printf("Write size mismatch: sent %u/%u bytes\n", 
               (unsigned)noOfBytesTransferred, (unsigned)noOfBytes);
        return FT_IO_ERROR;
    }

    // Read response
    status = FT_Read(handle, inBuffer, 1, &noOfBytesTransferred);
    if (status != FT_OK) {
        printf("Read failed: %d\n", status);
        return status;
    }

    if (noOfBytesTransferred != 1) {
        printf("Read size mismatch: got %u bytes\n", (unsigned)noOfBytesTransferred);
        return FT_IO_ERROR;
    }

    // Extract the bit (LSB)
    *bit_in = inBuffer[0] & 0x01;
    
    return FT_OK;
}

int main(int argc, char *argv[])
{
    FT_STATUS status;
    FT_HANDLE handle;
    DWORD dwNumDevices;
    
    int device_index = 0;
    uint32_t clock_divisor = 0x40; // Default clock divisor
    
    // Parse command line arguments
    if (argc > 1) {
        device_index = atoi(argv[1]);
    }
    if (argc > 2) {
        clock_divisor = atoi(argv[2]);
    }

    printf("Opening FTDI device %d with clock divisor 0x%X\n", 
           device_index, clock_divisor);

    // Get number of devices
    status = FT_CreateDeviceInfoList(&dwNumDevices);
    if (status != FT_OK || dwNumDevices == 0) {
        fprintf(stderr, "No FTDI devices found\n");
        return 1;
    }
    printf("Found %u FTDI device(s)\n", (unsigned)dwNumDevices);

    // Open device
    status = FT_Open(device_index, &handle);
    if (status != FT_OK) {
        fprintf(stderr, "Failed to open device: %d\n", status);
        return 1;
    }

    // Initialize MPSSE
    uint8_t byOutputBuffer[8];
    uint8_t byInputBuffer[8];
    DWORD dwNumBytesSent, dwNumBytesRead, dwNumBytesToRead;
    DWORD dwNumBytesToSend = 0;

    status = FT_ResetDevice(handle);
    printf("FT_ResetDevice %d\n", status);
    // Purge receive buffer
    status |= FT_GetQueueStatus(handle, &dwNumBytesToRead);
    if ((status == FT_OK) && (dwNumBytesToRead > 0)) {
        FT_Read(handle, byInputBuffer, dwNumBytesToRead, &dwNumBytesRead);
        
    }
    printf("FT_GetQueueStatus %d\n", status);
    status |= FT_SetUSBParameters(handle, 64, 64);
    printf("FT_SetUSBParameters %d\n", status);
    status |= FT_SetChars(handle, 0, 0, 0, 0);
    printf("FT_SetChars %d\n", status);
    status |= FT_SetTimeouts(handle, 5000, 5000);
    printf("FT_SetTimeouts %d\n", status);
    status |= FT_SetLatencyTimer(handle, 1);
    printf("FT_SetLatencyTimer %d\n", status);
    status |= FT_SetFlowControl(handle, FT_FLOW_RTS_CTS, 0x00, 0x00);
    printf("FT_SetFlowControl %d\n", status);
    status |= FT_SetBitMode(handle, 0x0, 0x00);  // Reset
    printf("FT_SetBitMode %d\n", status);
    status |= FT_SetBitMode(handle, 0x0, 0x02);  // Enable MPSSE
    
    if (status != FT_OK) {
        fprintf(stderr, "MPSSE initialization failed: %d\n", status);
        FT_Close(handle);
        return 1;
    }

    status = FT_Purge(handle, FT_PURGE_RX | FT_PURGE_TX);

    // Synchronize MPSSE with bad command
    dwNumBytesToSend = 0;
    byOutputBuffer[dwNumBytesToSend++] = 0xAB;
    status = FT_Write(handle, byOutputBuffer, dwNumBytesToSend, &dwNumBytesSent);
    dwNumBytesToSend = 0;
    
    dwNumBytesToRead = 2;
    status = FT_Read(handle, byInputBuffer, dwNumBytesToRead, &dwNumBytesRead);
    
    if (!((byInputBuffer[0] == 0xFA) && (byInputBuffer[1] == 0xAB))) {
        fprintf(stderr, "MPSSE sync failed\n");
        FT_Close(handle);
        return 1;
    }

    // Configure MPSSE
    byOutputBuffer[dwNumBytesToSend++] = 0x8A;  // 60MHz clock
    byOutputBuffer[dwNumBytesToSend++] = 0x97;  // Disable adaptive clocking
    byOutputBuffer[dwNumBytesToSend++] = 0x8C;  // Enable 3-phase clocking
    status = FT_Write(handle, byOutputBuffer, dwNumBytesToSend, &dwNumBytesSent);
    dwNumBytesToSend = 0;

    // Set clock divisor
    byOutputBuffer[dwNumBytesToSend++] = 0x86;
    byOutputBuffer[dwNumBytesToSend++] = clock_divisor & 0xFF;
    byOutputBuffer[dwNumBytesToSend++] = (clock_divisor >> 8) & 0xFF;
    status = FT_Write(handle, byOutputBuffer, dwNumBytesToSend, &dwNumBytesSent);

    printf("MPSSE initialized successfully\n");
    printf("Starting test loop (Ctrl+C to exit)...\n\n");

    // Test loop
    uint32_t iteration = 0;
    uint32_t errors = 0;
    uint8_t test_data = 0xAA;
    uint8_t bit_result;

    while (1) {
        status = test_write8bits_read1bit(handle, test_data, &bit_result);
        
        if (status != FT_OK) {
            errors++;
            printf("Iteration %u FAILED (total errors: %u)\n", iteration, errors);
        }
        
        iteration++;
        
        if (iteration % 1000 == 0) {
            printf("Iteration %u OK (errors: %u, bit read: %u)\n", 
                   iteration, errors, bit_result);
        }
        if(errors == 1) break;
        // Vary test data
        test_data++;
    }

    FT_Close(handle);
    return 0;
}