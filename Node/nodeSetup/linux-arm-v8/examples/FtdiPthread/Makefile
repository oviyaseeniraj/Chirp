TOPDIR := $(shell cd ..; pwd)
include $(TOPDIR)/Rules.make

APP = FtdiPthreadIssue

CXX = g++
CXXFLAGS = $(CFLAGS)

SRCS = Main.cpp CFtdiDevice.cpp
OBJS = $(SRCS:.cpp=.o)

all: $(APP)

$(APP): $(OBJS)
	$(CXX) $(OBJS) -o $(APP) $(CXXFLAGS) $(DYNAMIC_LIB) 

%.o: %.cpp
	$(CXX) -c $< -o $@ $(CXXFLAGS) $(DYNAMIC_LIB) 

clean:
	-rm -f $(OBJS) $(APP)

