TOPDIR  := $(shell cd ..; cd ..; pwd)
include $(TOPDIR)/Rules.make

APP = w32_simple

all: $(APP)

$(APP): main.c	
	$(CC) main.c -o $(APP) $(CFLAGS) $(DYNAMIC_LIB)  -g
	
clean:
	-rm -f *.o ; rm $(APP)
