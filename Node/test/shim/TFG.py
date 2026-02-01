# test frame gen, creates a frame and then saves it to a files
#

import os

from new_pipe.daq import DataAcquisition


def main():
    daq = DataAcquisition()
    frame = daq.process()
    # save the frame that was taken from daq as a file
    print(len(frame))
    with open(os.path.join(os.path.dirname(__file__), "data", "daq-py.txt"), "w") as f:
        for x in frame:
            f.write(f"{x}\n")


if __name__ == "__main__":
    main()
