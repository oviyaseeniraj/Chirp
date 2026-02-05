
import jetgpio
import time

# Initialize JetGPIO
Init = jetgpio.gpioInitialise()
if Init < 0:
    print(f"JetGPIO initialisation failed. Error code: {Init}")
    exit(Init)
else:
    print(f"JetGPIO initialisation OK. Return code: {Init}")

# Set pin 8 as OUTPUT, pin 7 as INPUT
if jetgpio.gpioSetMode(10, 1) < 0:  # JET_OUTPUT = 1
    print("Failed to set pin 8 as output")
    exit(1)
if jetgpio.gpioSetMode(7, 0) < 0:  # JET_INPUT = 0
    print("Failed to set pin 7 as input")
    exit(1)

# Toggle pin 8, read pin 7
for _ in range(50):
    jetgpio.gpioWrite(10, 1)
    time.sleep(0.001)
    print("level:", jetgpio.gpioRead(7))
    time.sleep(1)

    jetgpio.gpioWrite(8, 0)
    time.sleep(0.001)
    print("level:", jetgpio.gpioRead(7))
    time.sleep(1)

# Terminate
jetgpio.gpioTerminate()