#ifndef CONFIG_H
#define CONFIG_H

// GPIO Configuration
#define OUTPUT_PIN 8
#define PULSE_WIDTH_NS 50

// Trigger Timing
#define PULSE_PERIOD 100  // Period in milliseconds

// Networking (used by networked_trigger.c)
#define MASTER_IP "169.231.42.44"
#define MASTER_PORT 1210
#define SYNC_INTERVAL_SEC 5

#endif // CONFIG_H
