TOPDIR  := $(shell cd ..; cd ..; pwd)
include $(TOPDIR)/Rules.make

APP = w32_timeouts

all: $(APP)

$(APP): main.c	
	$(CC) main.c -o $(APP) $(CFLAGS) $(DYNAMIC_LIB) 
	
clean:
	-rm -f *.o ; rm $(APP)
