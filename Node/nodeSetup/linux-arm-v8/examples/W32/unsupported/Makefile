TOPDIR  := $(shell cd ..; cd ..; pwd)
include $(TOPDIR)/Rules.make

APP = w32_unsupported

all: $(APP)

$(APP): main.c	
	$(CC) -o $(APP) $(CFLAGS) $(DYNAMIC_LIB)  main.c
	
clean:
	-rm -f *.o ; rm $(APP)
