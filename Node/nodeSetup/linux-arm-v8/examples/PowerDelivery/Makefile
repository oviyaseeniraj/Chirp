TOPDIR := $(shell cd ..; pwd)
include $(TOPDIR)/Rules.make

# Define applications and their corresponding source files
APPS = ReadPD WritePD DefaultConfig
SOURCES = $(APPS:=.c)

all: $(APPS)

# Pattern rule for compiling .c files into executables
%: %.c
	$(CC) $< -o $@ $(CFLAGS) $(DYNAMIC_LIB) 

clean:
	-rm -f *.o $(APPS)
