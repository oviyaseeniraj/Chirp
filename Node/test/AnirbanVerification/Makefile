CXX = g++
CXXFLAGS = -std=c++17 -Wall -pedantic -g
LDFLAGS = -lfftw3f -pthread -lm `pkg-config --cflags --libs opencv4`

SRCS = test.cpp ../../src/RangeDoppler.cpp ../../src/RadarBlock.cpp  ../../src/Visualizer.cpp #../../src/DataAcquisition.cpp
OBJS = $(SRCS:.cpp=.o)
EXEC = test

H_INCLUDES = -I/opt/homebrew/include/ -I/opt/homebrew/opt/fftw/include  -I/opt/homebrew/include/opencv4 -I../../src/ -I../../include/
L_INCLUDES = -L/opt/homebrew/opt/fftw/lib

DEFINES = -DFAST_TIME=512 -DSLOW_TIME=60

.PHONY: all clean

all: $(EXEC)

$(EXEC): $(OBJS)
	$(CXX) $(CXXFLAGS) ${L_INCLUDES} $(OBJS) -o $@ $(LDFLAGS)

%.o: %.cpp
	$(CXX) $(CXXFLAGS) ${H_INCLUDES} ${DEFINES} -c $< -o $@

clean:
	rm -f $(OBJS) $(EXEC)
