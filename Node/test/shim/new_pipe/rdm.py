import time

import numpy as np
import pyfftw

FAST_TIME = 512
SLOW_TIME = 64
RX = 4
TX = 3
IQ = 2

SIZE_W_IQ = TX * RX * SLOW_TIME * FAST_TIME * IQ
SIZE = TX * RX * SLOW_TIME * FAST_TIME


def getIndices(index_1D):
    i0 = index_1D // (RX * IQ * FAST_TIME * TX)
    i1 = index_1D % (RX * IQ * FAST_TIME * TX)
    i2 = i1 % (RX * IQ * FAST_TIME)
    i3 = i2 % (RX * IQ)
    i4 = i3 % RX

    slow = i0
    tx = i1 // (RX * IQ * FAST_TIME)
    fast = i2 // (RX * IQ)
    iq = i3 // RX
    rx = i4

    return tx, rx, slow, fast, iq


class RangeDoppler:
    SIZE = SIZE_W_IQ  # total number of samples

    # Create index array
    idx = np.arange(SIZE)

    # replicate getIndices logic
    i0 = idx // (RX * IQ * FAST_TIME * TX)
    i1 = idx % (RX * IQ * FAST_TIME * TX)
    i2 = i1 % (RX * IQ * FAST_TIME)
    i3 = i2 % (RX * IQ)
    i4 = i3 % RX

    slow = i0
    tx = i1 // (RX * IQ * FAST_TIME)
    fast = i2 // (RX * IQ)
    iq = i3 // RX
    rx = i4

    # Compute flat indices for self.mid exactly like your loop
    tx_o = tx * RX * SLOW_TIME * FAST_TIME * IQ
    rx_o = rx * SLOW_TIME * FAST_TIME * IQ
    slow_o = slow * FAST_TIME * IQ
    fast_o = fast * IQ

    mid_idx = tx_o + rx_o + slow_o + fast_o + iq

    def __init__(self, window="blackman"):
        self.window_type = window.lower()

        self.adc_data_flat = np.zeros(SIZE_W_IQ, dtype=np.float32)
        self.mid = np.zeros(SIZE_W_IQ, dtype=np.float32)
        self.adc_complex = np.zeros(SIZE, dtype=np.complex64)

        if self.window_type == "blackman":
            self.window = np.blackman(FAST_TIME).astype(np.float32)
        elif self.window_type == "hann":
            self.window = np.hanning(FAST_TIME).astype(np.float32)
        else:
            self.window = np.ones(FAST_TIME, dtype=np.float32)

        # FFTW setup
        self.fftw_in = pyfftw.empty_aligned(
            (TX * RX, SLOW_TIME, FAST_TIME), dtype=np.complex64
        )
        self.fftw_out = pyfftw.empty_aligned(
            (TX * RX, SLOW_TIME, FAST_TIME), dtype=np.complex64
        )
        self.plan = pyfftw.FFTW(
            self.fftw_in,
            self.fftw_out,
            axes=(1, 2),
            direction="FFTW_FORWARD",
            flags=("FFTW_ESTIMATE",),
        )

    def set_buffer(self, buf):
        arr = np.asarray(buf, dtype=np.float32)
        if arr.size != SIZE_W_IQ:
            raise ValueError("Invalid input buffer size")
        self.adc_data_flat[:] = arr

    def set_cube(self, cube):
        arr = np.asarray(cube, dtype=np.complex64)
        self.adc_complex[:] = arr.flatten()

    def shape_cube_vect(self):
        # Fill mid vectorized
        self.mid.fill(0.0)
        np.put(self.mid, self.mid_idx, self.adc_data_flat * self.window[self.fast])

        # Form complex AFTER reorder
        self.adc_complex.real = self.mid[0::2]
        self.adc_complex.imag = self.mid[1::2]

        return self.adc_complex.reshape((TX * RX, SLOW_TIME, FAST_TIME))

    def process(self):
        t0 = time.perf_counter()

        cube = self.shape_cube_vect()
        t1 = time.perf_counter()
        np.copyto(self.fftw_in, cube)
        self.plan()
        rdm = self.fftw_out

        mag2 = rdm.real * rdm.real + rdm.imag * rdm.imag
        mag = np.log2(mag2) * 0.5

        avg = mag.reshape((TX * RX, SLOW_TIME * FAST_TIME)).mean(axis=0)

        mn = avg.min()
        mx = avg.max()
        if mx != mn:
            avg = (avg - mn) * (255.0 / (mx - mn))
        else:
            avg[:] = 0.0

        avg = avg.reshape((SLOW_TIME, FAST_TIME))
        avg = np.fft.fftshift(avg, axes=(0, 1))

        dt = (time.perf_counter() - t0) * 1e6
        dt2 = (t1 - t0) * 1e6
        print(f"RDM frame processed in {dt:.0f} us")
        print(f"Cube frame processed in {dt2:.0f} us")

        return avg.ravel()

    def rdm_process_cube(self):
        np.copyto(
            self.fftw_in, self.adc_complex.reshape((TX * RX, SLOW_TIME, FAST_TIME))
        )
        self.plan()
        rdm = self.fftw_out

        # compute mag norm
        mag2 = rdm.real * rdm.real + rdm.imag * rdm.imag
        mag = np.log2(mag2) * 0.5

        avg = mag.reshape((TX * RX, SLOW_TIME * FAST_TIME)).mean(axis=0)

        mn = avg.min()
        mx = avg.max()
        if mx != mn:
            avg = (avg - mn) * (255.0 / (mx - mn))
        else:
            avg[:] = 0.0

        avg = avg.reshape((SLOW_TIME, FAST_TIME))
        avg = np.fft.fftshift(avg, axes=(0, 1))
        return avg.ravel()


if __name__ == "__main__":
    rd = RangeDoppler()
    test = np.linspace(0, 1, SIZE_W_IQ, dtype=np.float32)
    rd.set_buffer(test)
    out = rd.process()
    print(out[:8])
