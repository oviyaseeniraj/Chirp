#ifndef RADARBLOCK_H
#define RADARBLOCK_H

class RadarBlock {
    public:
        int inputsize;
        int outputsize;
        bool verbose;

        unsigned int frame = 0;

        unsigned int* inputframeptr;
        float* inputbufferptr;
        float* inputangbufferptr;
        float* inputrangebuffptr;
        int* inputangindexptr;

        unsigned int lastframe;

        // constructor & deconstructor
        RadarBlock(int size_in, int size_out, bool v = false);
        ~RadarBlock();

        // public functions
        void setBufferPointer(float *ptr);
        void setRangeBufferPointer(float *ptr);
        void setAngleBufferPointer(float *ptr);
        void setAngleIndexPointer(int *ptr);

        // Sets the input frame pointer
        void setFramePointer(unsigned int *ptr);

        // Retrieve outputbuffer pointer
        float *getBufferPointer();

        // Retrieve frame pointer
        unsigned int *getFramePointer();

        // Complete desired calculations / data manipulation
        virtual void process();

        // Iterates
        void iteration();

    private:
        float *outputbuffer;

        // private functions
        // Listens for previous block (overwritten in some cases)
        virtual void listen();

        void increment_frame();
};

#endif