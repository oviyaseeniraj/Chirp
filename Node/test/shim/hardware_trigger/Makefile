CC      = gcc
CFLAGS  = -Wall
LIBS    = -ljetgpio

EXES = jetgpio_example trigger_test

all: $(EXES)

jetgpio_example: jetgpio_example.o
	$(CC) $(CFLAGS) -o $@ $^ $(LIBS)

trigger_test: trigger_test.o
	$(CC) $(CFLAGS) -o $@ $^ $(LIBS)

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f $(EXES) *.o
