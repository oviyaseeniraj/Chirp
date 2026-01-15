TOPDIR  := $(shell cd ..; pwd)
include $(TOPDIR)/Rules.make

APP = mpsse_read1bitACK

all: $(APP)

$(APP): main.c
	$(CC) main.c -o $(APP) $(CFLAGS) $(DYNAMIC_LIB)

clean:
	-rm -f *.o ; rm $(APP)
