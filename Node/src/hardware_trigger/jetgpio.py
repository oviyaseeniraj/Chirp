import ctypes

# Load the library
_lib = ctypes.CDLL("/lib/libjetgpio.so")  # adjust path if needed

# --------------------------
# Function declarations
# --------------------------
gpioInitialise = _lib.gpioInitialise
gpioInitialise.argtypes = []
gpioInitialise.restype = ctypes.c_int

gpioSetMode = _lib.gpioSetMode
gpioSetMode.argtypes = [ctypes.c_uint, ctypes.c_uint]
gpioSetMode.restype = ctypes.c_int

gpioWrite = _lib.gpioWrite
gpioWrite.argtypes = [ctypes.c_uint, ctypes.c_uint]
gpioWrite.restype = ctypes.c_int

gpioRead = _lib.gpioRead
gpioRead.argtypes = [ctypes.c_uint]
gpioRead.restype = ctypes.c_int

gpioTerminate = _lib.gpioTerminate
gpioTerminate.argtypes = []
gpioTerminate.restype = None

# --------------------------
# Optional constants
# --------------------------
JET_INPUT = 0
JET_OUTPUT = 1

if __name__ == "__main__":
    """# Initialize JetGPIO
    Init = jetgpio.gpioInitialise()
    if Init < 0:
        print(f"JetGPIO initialisation failed. Error code: {Init}")
        exit(Init)
    else:
        print(f"JetGPIO initialisation OK. Return code: {Init}")

    # Set pin 8 as OUTPUT, pin 7 as INPUT
    if jetgpio.gpioSetMode(8, 1) < 0:  # JET_OUTPUT = 1
        print("Failed to set pin 8 as output")
        exit(1)
    if jetgpio.gpioSetMode(7, 0) < 0:  # JET_INPUT = 0
        print("Failed to set pin 7 as input")
        exit(1)

    # Toggle pin 8, read pin 7
    for _ in range(5):
        jetgpio.gpioWrite(8, 1)
        time.sleep(0.001)
        print("level:", jetgpio.gpioRead(7))
        time.sleep(1)

        jetgpio.gpioWrite(8, 0)
        time.sleep(0.001)
        print("level:", jetgpio.gpioRead(7))
        time.sleep(1)

    # Terminate
    jetgpio.gpioTerminate()
    """
