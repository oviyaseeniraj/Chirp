TOPDIR  := $(shell cd ..; pwd)
include $(TOPDIR)/Rules.make

APP_SHARED = multiDeviceRW_shared
APP_STATIC = multiDeviceRW_static

all: $(APP_SHARED) $(APP_STATIC)

$(APP_SHARED): main.c
	$(CC) main.c -o $(APP_SHARED) $(CFLAGS) $(DYNAMIC_LIB)

$(APP_STATIC): main.c
	$(CC) main.c -o $(APP_STATIC) $(CFLAGS) $(STATIC_LIB)

clean:
	-rm -f *.o ; rm -f $(APP_SHARED) $(APP_STATIC)
