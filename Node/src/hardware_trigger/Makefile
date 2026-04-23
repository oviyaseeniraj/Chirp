

all:  local_trigger networked_trigger


local_trigger: local_trigger.c config.h
	gcc -Wall -o local_trigger local_trigger.c -ljetgpio

networked_trigger: networked_trigger.c config.h
	gcc -Wall -o networked_trigger networked_trigger.c -ljetgpio



