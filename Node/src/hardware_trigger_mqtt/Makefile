all: trigger_worker

trigger_worker: trigger_worker.c config.h
	gcc -Wall -Wextra -O2 -o trigger_worker trigger_worker.c -ljetgpio

clean:
	rm -f trigger_worker
