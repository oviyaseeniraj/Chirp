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


#define OUTPUT_PIN 8
#define PULSE_WIDTH_NS 50
#define PULSE_PERIOD_US 60

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
  int level = 0;
  
  struct timespec spec;
  spec.tv_sec = 0;
  spec.tv_nsec = 10000;

  printf("%d\n",x);
  gpioWrite(OUTPUT_PIN, 0);
  while (x<1) {
    gpioWrite(OUTPUT_PIN, 1);
    //nanosleep(&spec,0);
    gpioWrite(OUTPUT_PIN, 0);
    usleep(PULSE_PERIOD_US); 
    //printf("%d\n",x);

    x++;
  }

  // Terminating library 
  gpioTerminate();

  exit(0);
	
}