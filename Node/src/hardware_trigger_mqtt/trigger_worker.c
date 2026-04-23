#define _GNU_SOURCE

#include <errno.h>
#include <jetgpio.h>
#include <sched.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#include "config.h"

typedef struct runtime_config {
  long long start_epoch_ms;
  int pulse_period_ms;
  int max_pulses; // -1 means run forever.
  int cpu_core;
} runtime_config_t;

static volatile sig_atomic_t keep_running = 1;

static void handle_signal(int signum) {
  (void)signum;
  keep_running = 0;
}

static void print_usage(const char *prog) {
  printf("Usage:\n");
  printf("  %s --start-epoch-ms <epoch_ms> [options]\n\n", prog);
  printf("Required:\n");
  printf("  --start-epoch-ms <ms>   Absolute CLOCK_REALTIME epoch in milliseconds.\n\n");
  printf("Optional:\n");
  printf("  --pulse-period-ms <ms>  Pulse period in milliseconds (default: %d).\n",
         DEFAULT_PULSE_PERIOD_MS);
  printf("  --max-pulses <n>        Emit n pulses then exit (default: run forever).\n");
  printf("  --cpu-core <id>         CPU core affinity index (default: %d).\n", DEFAULT_CPU_CORE);
  printf("  --help                  Show this message.\n");
}

static int parse_int(const char *value, int *out) {
  char *end = NULL;
  long parsed = strtol(value, &end, 10);
  if (end == value || *end != '\0') {
    return -1;
  }
  if (parsed < INT32_MIN || parsed > INT32_MAX) {
    return -1;
  }
  *out = (int)parsed;
  return 0;
}

static int parse_long_long(const char *value, long long *out) {
  char *end = NULL;
  long long parsed = strtoll(value, &end, 10);
  if (end == value || *end != '\0') {
    return -1;
  }
  *out = parsed;
  return 0;
}

static int parse_args(int argc, char *argv[], runtime_config_t *cfg) {
  int i = 1;
  int has_start_epoch = 0;

  cfg->start_epoch_ms = 0;
  cfg->pulse_period_ms = DEFAULT_PULSE_PERIOD_MS;
  cfg->max_pulses = -1;
  cfg->cpu_core = DEFAULT_CPU_CORE;

  while (i < argc) {
    if (strcmp(argv[i], "--help") == 0) {
      print_usage(argv[0]);
      return 1;
    }

    if (strcmp(argv[i], "--start-epoch-ms") == 0) {
      if (i + 1 >= argc || parse_long_long(argv[i + 1], &cfg->start_epoch_ms) != 0 ||
          cfg->start_epoch_ms <= 0) {
        fprintf(stderr, "Invalid --start-epoch-ms value.\n");
        return -1;
      }
      has_start_epoch = 1;
      i += 2;
      continue;
    }

    if (strcmp(argv[i], "--pulse-period-ms") == 0) {
      if (i + 1 >= argc || parse_int(argv[i + 1], &cfg->pulse_period_ms) != 0 ||
          cfg->pulse_period_ms <= 0) {
        fprintf(stderr, "Invalid --pulse-period-ms value.\n");
        return -1;
      }
      i += 2;
      continue;
    }

    if (strcmp(argv[i], "--max-pulses") == 0) {
      if (i + 1 >= argc || parse_int(argv[i + 1], &cfg->max_pulses) != 0 || cfg->max_pulses == 0) {
        fprintf(stderr, "Invalid --max-pulses value.\n");
        return -1;
      }
      i += 2;
      continue;
    }

    if (strcmp(argv[i], "--cpu-core") == 0) {
      if (i + 1 >= argc || parse_int(argv[i + 1], &cfg->cpu_core) != 0 || cfg->cpu_core < 0) {
        fprintf(stderr, "Invalid --cpu-core value.\n");
        return -1;
      }
      i += 2;
      continue;
    }

    fprintf(stderr, "Unknown argument: %s\n", argv[i]);
    return -1;
  }

  if (!has_start_epoch) {
    fprintf(stderr, "Missing required --start-epoch-ms argument.\n");
    return -1;
  }

  return 0;
}

static int configure_realtime(int cpu_core) {
  struct sched_param param;
  cpu_set_t cpumask;

  param.sched_priority = sched_get_priority_max(SCHED_FIFO);
  if (sched_setscheduler(0, SCHED_FIFO, &param) == -1) {
    perror("sched_setscheduler failed");
  }

  if (mlockall(MCL_CURRENT | MCL_FUTURE) == -1) {
    perror("mlockall failed");
  }

  CPU_ZERO(&cpumask);
  CPU_SET(cpu_core, &cpumask);
  if (sched_setaffinity(0, sizeof(cpumask), &cpumask) == -1) {
    perror("sched_setaffinity failed");
    return -1;
  }

  return 0;
}

static void add_ms(struct timespec *t, int ms) {
  t->tv_nsec += (long)ms * 1000000L;
  while (t->tv_nsec >= 1000000000L) {
    t->tv_nsec -= 1000000000L;
    t->tv_sec += 1;
  }
}

static long long now_epoch_ms(void) {
  struct timespec now;
  clock_gettime(CLOCK_REALTIME, &now);
  return (long long)now.tv_sec * 1000LL + (long long)(now.tv_nsec / 1000000L);
}

int main(int argc, char *argv[]) {
  runtime_config_t cfg;
  struct timespec next_trigger;
  int init_status;
  int mode_status;
  int pulse_count = 0;

  int parse_result = parse_args(argc, argv, &cfg);
  if (parse_result > 0) {
    return 0;
  }
  if (parse_result < 0) {
    print_usage(argv[0]);
    return 2;
  }

  long long now_ms = now_epoch_ms();
  if (cfg.start_epoch_ms <= now_ms) {
    fprintf(stderr,
            "start_epoch_ms (%lld) must be in the future. Current epoch_ms=%lld\n",
            cfg.start_epoch_ms,
            now_ms);
    return 3;
  }

  signal(SIGINT, handle_signal);
  signal(SIGTERM, handle_signal);

  init_status = gpioInitialise();
  if (init_status < 0) {
    fprintf(stderr, "Jetgpio initialization failed. Error code: %d\n", init_status);
    return 4;
  }

  mode_status = gpioSetMode(OUTPUT_PIN, JET_OUTPUT);
  if (mode_status < 0) {
    fprintf(stderr, "GPIO setup failed. Error code: %d\n", mode_status);
    gpioTerminate();
    return 5;
  }

  (void)configure_realtime(cfg.cpu_core);

  next_trigger.tv_sec = (time_t)(cfg.start_epoch_ms / 1000LL);
  next_trigger.tv_nsec = (long)((cfg.start_epoch_ms % 1000LL) * 1000000LL);

  gpioWrite(OUTPUT_PIN, 0);
  printf(
      "Trigger worker armed: startEpochMs=%lld periodMs=%d cpuCore=%d maxPulses=%d\n",
      cfg.start_epoch_ms,
      cfg.pulse_period_ms,
      cfg.cpu_core,
      cfg.max_pulses);

  while (keep_running && (cfg.max_pulses < 0 || pulse_count < cfg.max_pulses)) {
    int sleep_result = clock_nanosleep(CLOCK_REALTIME, TIMER_ABSTIME, &next_trigger, NULL);
    if (sleep_result != 0) {
      if (sleep_result == EINTR) {
        continue;
      }
      fprintf(stderr, "clock_nanosleep failed: %s\n", strerror(sleep_result));
      break;
    }

    gpioWrite(OUTPUT_PIN, 1);
    if (PULSE_WIDTH_NS > 0) {
      struct timespec pulse_width = {
          .tv_sec = 0,
          .tv_nsec = PULSE_WIDTH_NS,
      };
      nanosleep(&pulse_width, NULL);
    }
    gpioWrite(OUTPUT_PIN, 0);

    if (pulse_count < 10) {
      struct timespec pulse_time;
      clock_gettime(CLOCK_REALTIME, &pulse_time);
      printf("Pulse %d at %ld.%09ld\n", pulse_count, pulse_time.tv_sec, pulse_time.tv_nsec);
    }
    pulse_count++;
    add_ms(&next_trigger, cfg.pulse_period_ms);
  }

  gpioTerminate();
  printf("Trigger worker exiting after %d pulse(s).\n", pulse_count);
  return 0;
}
