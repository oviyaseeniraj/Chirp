import time

import cv2
import numpy as np
import pyfftw
from .. import config

class RangeDoppler:
    SIZE = config.BYTES_IN_FRAME // config.IQ_BYTES  # total number of samples

    # Create index array
    idx = np.arange(SIZE)

    # replicate getIndices logic
    i0 = idx // (config.RX * config.IQ * config.FAST_TIME * config.TX)
    i1 = idx % (config.RX * config.IQ * config.FAST_TIME * config.TX)
    i2 = i1 % (config.RX * config.IQ * config.FAST_TIME)
    i3 = i2 % (config.RX * config.IQ)
    i4 = i3 % config.RX

    slow = i0
    tx = i1 // (config.RX * config.IQ * config.FAST_TIME)
    fast = i2 // (config.RX * config.IQ)
    iq = i3 // config.RX
    rx = i4

    # Compute flat indices for self.mid exactly like your loop
    tx_o = tx * config.RX * config.SLOW_TIME * config.FAST_TIME * config.IQ
    rx_o = rx * config.SLOW_TIME * config.FAST_TIME * config.IQ
    slow_o = slow * config.FAST_TIME * config.IQ
    fast_o = fast * config.IQ

    mid_idx = tx_o + rx_o + slow_o + fast_o + iq

    def __init__(self, window="blackman", alpha=0.5):
        self.window_type = window.lower()

        self.adc_data_flat = np.zeros(self.SIZE, dtype=np.float32)
        self.mid = np.zeros(self.SIZE, dtype=np.float32)
        self.adc_complex = np.zeros(self.SIZE // 2, dtype=np.complex64)
        self.norm = np.zeros(self.SIZE, dtype=np.float32)
        self.avg = np.zeros(self.SIZE, dtype=np.float32)
        self.background = np.zeros((config.TX * config.RX, config.SLOW_TIME, config.FAST_TIME), dtype=np.complex64)

        self.alpha = alpha

        if self.window_type == "blackman":
            self.window = np.blackman(config.FAST_TIME).astype(np.float32)
        elif self.window_type == "hann":
            self.window = np.hanning(config.FAST_TIME).astype(np.float32)
        else:
            self.window = np.ones(config.FAST_TIME, dtype=np.float32)

        # FFTW setup
        self.fftw_in = pyfftw.empty_aligned(
            (config.TX * config.RX, config.SLOW_TIME, config.FAST_TIME), dtype=np.complex64
        )
        self.fftw_out = pyfftw.empty_aligned(
            (config.TX * config.RX, config.SLOW_TIME, config.FAST_TIME), dtype=np.complex64
        )
        self.plan = pyfftw.FFTW(
            self.fftw_in,
            self.fftw_out,
            axes=(1, 2),
            direction="FFTW_FORWARD",
            flags=("FFTW_ESTIMATE",),
        )

    def set_buffer(self, buf):
        arr = np.asarray(buf, dtype=np.int16)
        if arr.size != self.SIZE:
            raise ValueError(f"Invalid input buffer size: {arr.size} != {self.SIZE}")
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

        return self.adc_complex.reshape((config.TX * config.RX, config.SLOW_TIME, config.FAST_TIME))

    def iir_filter(self, rdm_complex):
        self.background = self.alpha * rdm_complex + (1 - self.alpha) * self.background
        clean_rdm = rdm_complex - self.background
        return clean_rdm

    def process(self):
        t0 = time.perf_counter()

        cube = self.shape_cube_vect()

        t1 = time.perf_counter()

        np.copyto(self.fftw_in, cube)
        self.plan()
        rdm = self.fftw_out

        t2 = time.perf_counter()

        # Apply IIR filter on complex data
        rdm = self.iir_filter(rdm)

        # Now compute magnitude squared
        mag2 = rdm.real * rdm.real + rdm.imag * rdm.imag
        self.norm = np.log2(mag2 + 1e-10) * 0.5

        t3 = time.perf_counter()

        avg = self.norm.reshape(config.RX * config.TX, config.SLOW_TIME * config.FAST_TIME).mean(axis=0)
        avg = (avg - avg.min()) / (avg.max() - avg.min()) * 255.0

        t4 = time.perf_counter()

        avg = avg.reshape((config.SLOW_TIME, config.FAST_TIME))
        avg = np.fft.fftshift(avg, axes=(0))
        t5 = time.perf_counter()

        return avg.ravel()

    def get_clean_rdm(self):
        rdm_complex = self.fftw_out.copy()  # Shape: (TX * RX, SLOW_TIME, FAST_TIME)

        # Reshape from (TX * RX, SLOW_TIME, FAST_TIME) to (TX, RX, SLOW_TIME, FAST_TIME)
        rdm_reshaped = rdm_complex.reshape((config.TX, config.RX, config.SLOW_TIME, config.FAST_TIME))

        # Transpose to (SLOW_TIME, RX, TX, FAST_TIME) to match angle.py expectations
        rdm_final = rdm_reshaped.transpose(2, 1, 0, 3)

        rdm_final = np.fft.fftshift(rdm_final, axes=0)

        return rdm_final

    def rdm_process_cube(self):
        np.copyto(
            self.fftw_in, self.adc_complex.reshape((config.TX * config.RX, config.SLOW_TIME, config.FAST_TIME))
        )
        self.plan()
        rdm = self.fftw_out

        # compute mag norm
        mag2 = rdm.real * rdm.real + rdm.imag * rdm.imag
        mag = np.log2(mag2) * 0.5

        avg = mag.reshape((config.TX * config.RX, config.SLOW_TIME * config.FAST_TIME)).mean(axis=0)

        mn = avg.min()
        mx = avg.max()
        if mx != mn:
            avg = (avg - mn) * (255.0 / (mx - mn))
        else:
            avg[:] = 0.0

        avg = avg.reshape((config.SLOW_TIME, config.FAST_TIME))
        avg = np.fft.fftshift(avg, axes=(0, 1))
        # print(avg.dtype)
        return avg.ravel()


if __name__ == "__main__":
    rd = RangeDoppler()
    # test = np.linspace(0, 1, SIZE_W_IQ, dtype=np.float32)
    # rd.set_buffer(test)
    # out = rd.process()
    # print(out[:8])
