# Define dependencies
DEPENDENCIES := -lftd2xx -lpthread

# Determine the operating system
UNAME := $(shell uname)

# Current working directory
TOPDIR := $(CURDIR)
CURRENT_DIR := $(TOPDIR)/../build

# Additional dependencies and static lib path based on OS
ifeq ($(UNAME), Darwin)
    DEPENDENCIES += -lobjc -framework IOKit -framework CoreFoundation
    STATIC_LIB_PATH := $(CURRENT_DIR)/libftd2xx.a
    LINKER_OPTIONS := -Wl,-rpath,$(CURRENT_DIR)
else
    DEPENDENCIES += -lrt
    STATIC_LIB_PATH := /usr/local/lib/libftd2xx.a
    LINKER_OPTIONS := -Wl,-rpath,/usr/local/lib
endif

# Compiler flags
CFLAGS := -Wall -Wextra

# Dynamic and static linking options
ifeq ($(UNAME), Darwin)
    DYNAMIC_LIB := $(DEPENDENCIES) $(LINKER_OPTIONS) -L$(CURRENT_DIR)
    STATIC_LIB := $(LINKER_OPTIONS) -L$(CURRENT_DIR) $(STATIC_LIB_PATH)
else
    DYNAMIC_LIB := $(DEPENDENCIES) $(LINKER_OPTIONS) -L/usr/local/lib
    STATIC_LIB := $(LINKER_OPTIONS) -L/usr/local/lib $(STATIC_LIB_PATH)
endif
