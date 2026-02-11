#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <unistd.h>
#include <time.h>

int main(int argc, char *argv[])
{
  int x = 0;
  
  struct timespec next_trigger;
  clock_gettime(CLOCK_REALTIME, &next_trigger);
  
  // Round up to the next 100ms boundary
  next_trigger.tv_nsec = (next_trigger.tv_nsec  / 100000000 + 1) * 100000000;
  if (next_trigger.tv_nsec >= 1000000000) {
      next_trigger.tv_nsec -= 1000000000;
      next_trigger.tv_sec += 1;
  }

  printf("Starting synchronized timing test every 100ms...\n");

  while (x < 10) {
    // Wait for the next 100ms boundary
    clock_nanosleep(CLOCK_REALTIME, TIMER_ABSTIME, &next_trigger, NULL);
    
    struct timespec now;
    clock_gettime(CLOCK_REALTIME, &now);
    printf("Pulse %d at %ld.%09ld (Target: %ld.%09ld)\n", x, now.tv_sec, now.tv_nsec, next_trigger.tv_sec, next_trigger.tv_nsec);

    // Calculate next 100ms boundary
    next_trigger.tv_nsec += 100000000;
    if (next_trigger.tv_nsec >= 1000000000) {
        next_trigger.tv_nsec -= 1000000000;
        next_trigger.tv_sec += 1;
    }

    x++;
  }
  return 0;
}
