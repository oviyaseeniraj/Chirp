

all: jetgpio_example.c local_trigger networked_trigger
	gcc -Wall -o jetgpio_example jetgpio_example.c -ljetgpio


local_trigger: local_trigger.c
	gcc -Wall -o local_trigger local_trigger.c -ljetgpio

networked_trigger: networked_trigger.c
	gcc -Wall -o networked_trigger networked_trigger.c -ljetgpio



