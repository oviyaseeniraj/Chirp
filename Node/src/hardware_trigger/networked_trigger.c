#define _GNU_SOURCE
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <unistd.h>
#include <jetgpio.h>
#include <time.h>
#include <sched.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include "config.h"


int main(int argc, char *argv[])
{
  int Init;
  int sync_interval = SYNC_INTERVAL_SEC;

  if (argc > 1) {
      sync_interval = atoi(argv[1]);
      if (sync_interval <= 0) sync_interval = SYNC_INTERVAL_SEC;
  }

  Init = gpioInitialise();
  if (Init < 0)
    {
      printf("Jetgpio initialisation failed. Error code:  %d\n", Init);
      exit(Init);
    }
  
  int stat1 = gpioSetMode(OUTPUT_PIN, JET_OUTPUT);
  if (stat1 < 0)
    {
      printf("gpio setting up failed. Error code:  %d\n", stat1);
      exit(Init);
    }

  // Set real-time priority
  struct sched_param param;
  param.sched_priority = sched_get_priority_max(SCHED_FIFO);
  if (sched_setscheduler(0, SCHED_FIFO, &param) == -1) {
      perror("sched_setscheduler failed");
  }

  // Lock memory to prevent swapping
  if (mlockall(MCL_CURRENT | MCL_FUTURE) == -1) {
      perror("mlockall failed");
  }

  // Pin to CPU core 6
  cpu_set_t cpumask;
  CPU_ZERO(&cpumask);
  CPU_SET(5, &cpumask);
  if (sched_setaffinity(0, sizeof(cpumask), &cpumask) == -1) {
      perror("sched_setaffinity failed");
  }

  // Networking Sync Component
  int sock = 0;
  struct sockaddr_in serv_addr;
  if ((sock = socket(AF_INET, SOCK_STREAM, 0)) < 0) {
      printf("\n Socket creation error \n");
      return -1;
  }

  serv_addr.sin_family = AF_INET;
  serv_addr.sin_port = htons(MASTER_PORT);

  if (inet_pton(AF_INET, MASTER_IP, &serv_addr.sin_addr) <= 0) {
      printf("\nInvalid address/ Address not supported \n");
      return -1;
  }

  printf("Connecting to master at %s:%d...\n", MASTER_IP, MASTER_PORT);
  while (connect(sock, (struct sockaddr *)&serv_addr, sizeof(serv_addr)) < 0) {
      printf("Connection Failed. Retrying in 1 seconds...\n");
      sleep(1);
  }
  printf("Connected to master.\n");

  // Calculate next future time modulo sync_interval
  struct timespec now;
  clock_gettime(CLOCK_REALTIME, &now);
  
  long next_sync_sec = ((now.tv_sec / sync_interval) + 1) * sync_interval;
  char sync_msg[128];
  snprintf(sync_msg, sizeof(sync_msg), "%ld", next_sync_sec);

  printf("Proposed start time: %ld (modulo %d)\n", next_sync_sec, sync_interval);
  send(sock, sync_msg, strlen(sync_msg), 0);

  // Wait for initial consensus
  char buffer[1024] = {0};
  int valread = read(sock, buffer, 1024);
  if (valread <= 0) {
      printf("Failed to read consensus from master\n");
      return -1;
  }
  
  long consensus_sec = atol(buffer);
  printf("Received initial consensus start time: %ld\n", consensus_sec);

  // Set socket to non-blocking for subsequent updates
  int flags = fcntl(sock, F_GETFL, 0);
  fcntl(sock, F_SETFL, flags | O_NONBLOCK);

  struct timespec next_trigger;
  next_trigger.tv_sec = consensus_sec;
  next_trigger.tv_nsec = 0;

  gpioWrite(OUTPUT_PIN, 0);
  printf("Starting synchronized trigger every %dms at %ld.000000000...\n", PULSE_PERIOD, consensus_sec);

  int x = 0;
  while (1) {
    // Wait for the next 100ms boundary
    clock_nanosleep(CLOCK_REALTIME, TIMER_ABSTIME, &next_trigger, NULL);
    
    // Pulse GPIO pin
    gpioWrite(OUTPUT_PIN, 1);
    gpioWrite(OUTPUT_PIN, 0);

    // Check for resync updates from the master
    memset(buffer, 0, sizeof(buffer));
    valread = recv(sock, buffer, 1024, 0);
    if (valread > 0) {
        long new_consensus = atol(buffer);
        if (new_consensus > 0) {
            printf("\n--- RESYNC RECEIVED: New start time %ld ---\n", new_consensus);
            next_trigger.tv_sec = new_consensus;
            next_trigger.tv_nsec = 0;
            x = 0; // Reset pulse count for demo logging
            continue; // Immediately wait for new start time
        }
    } else if (valread == 0) {
        printf("Master disconnected\n");
        // Optional: handle disconnection, e.g., continue pulsing or exit
    }

    // Calculate next boundary
    next_trigger.tv_nsec += (long)PULSE_PERIOD * 1000000;
    if (next_trigger.tv_nsec >= 1000000000) {
        next_trigger.tv_nsec -= 1000000000;
        next_trigger.tv_sec += 1;
    }

    if (x < 10) {
        struct timespec pulse_time;
        clock_gettime(CLOCK_REALTIME, &pulse_time);
        printf("Pulse %d at %ld.%09ld\n", x, pulse_time.tv_sec, pulse_time.tv_nsec);
    }
    x++;
  }

  close(sock);
  gpioTerminate();
  return 0;
}

