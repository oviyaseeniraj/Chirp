# Convert from Anirban's data to Matrix

"convert.py" outputs each frame in Anirban's data to a separate text file inside AnirbanVerification/outputdata/
1. cd Chirp/Node/test/AnirbanVerification
2. source virtual/bin/activate
3. Open convert.py and configure the .mat file you want to convert to fusionsense format. I did not include the .mat files because they are pretty large, but you should be able to download them from the google drive where Anirban uploaded them.
4. Run "python3 convert.py" and wait for the script to stop writing text files.
5. run "make" to build the fusionsense visualizer
6. If this is your first time building, you may need to run:
    chmod +x test
7. run "./test {filename}"  - by default, this will look for "output_DAQ2.txt" if no filename is provided

requirements.txt contains all the packages needed for convert.py. 