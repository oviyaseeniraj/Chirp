#define _GNU_SOURCE
/* Usage example of the JETGPIO library
 * Compile with: gcc -Wall -o jetgpio_example jetgpio_example.c -ljetgpio
 * Execute with: sudo ./jetgpio_example
 */

#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <unistd.h>
#include <jetgpio.h>
#include <time.h>
#include <sched.h>
#include <sys/mman.h>
#include "config.h"


int main(int argc, char *argv[])
{
  int Init;

  Init = gpioInitialise();
  if (Init < 0)
    {
      /* jetgpio initialisation failed */
      printf("Jetgpio initialisation failed. Error code:  %d\n", Init);
      exit(Init);
    }
  else
    {
      /* jetgpio initialised okay*/
      printf("Jetgpio initialisation OK. Return code:  %d\n", Init);
    }	

  // Setting up pin 8 as OUTPUT and 7 as INPUT

  int stat1 = gpioSetMode(OUTPUT_PIN, JET_OUTPUT);
  if (stat1 < 0)
    {
      /* gpio setting up failed */
      printf("gpio setting up failed. Error code:  %d\n", stat1);
      exit(Init);
    }
  else
    {
      /* gpio setting up okay*/
      printf("gpio setting up okay. Return code:  %d\n", stat1);
    }

  // Writing 1 and 0 to pin 3 a 1 second intervals while reading pin 7 
  int x = 0;

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
  
  // Synchronize to the next 100ms boundary of CLOCK_REALTIME
  struct timespec next_trigger;
  clock_gettime(CLOCK_REALTIME, &next_trigger);
  
  // Round up to the next boundary
  next_trigger.tv_nsec = (next_trigger.tv_nsec / ((long)PULSE_PERIOD * 1000000) + 1) * ((long)PULSE_PERIOD * 1000000);
  if (next_trigger.tv_nsec >= 1000000000) {
      next_trigger.tv_nsec -= 1000000000;
      next_trigger.tv_sec += 1;
  }

  gpioWrite(OUTPUT_PIN, 0);
  printf("Starting synchronized trigger every %dms...\n", PULSE_PERIOD);

  while (1) {
    // Wait for the next 100ms boundary
    clock_nanosleep(CLOCK_REALTIME, TIMER_ABSTIME, &next_trigger, NULL);
    
    // Pulse GPIO pin
    gpioWrite(OUTPUT_PIN, 1);
    gpioWrite(OUTPUT_PIN, 0);

    // Calculate next boundary
    next_trigger.tv_nsec += (long)PULSE_PERIOD * 1000000;
    if (next_trigger.tv_nsec >= 1000000000) {
        next_trigger.tv_nsec -= 1000000000;
        next_trigger.tv_sec += 1;
    }

    if (x < 10) {
        struct timespec now;
        clock_gettime(CLOCK_REALTIME, &now);
        printf("Pulse %d at %ld.%09ld\n", x, now.tv_sec, now.tv_nsec);
    }
    x++;
  }
  // Terminating library 
  gpioTerminate();
  exit(0);
}