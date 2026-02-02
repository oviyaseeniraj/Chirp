import time

import cv2
import numpy as np
import pyfftw
from new_pipe.cfar import cfar_pytorch

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
        self.norm = np.zeros(SIZE_W_IQ, dtype=np.float32)
        self.avg = np.zeros(SIZE_W_IQ, dtype=np.float32)

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

        t2 = time.perf_counter()

        mag2 = rdm.real * rdm.real + rdm.imag * rdm.imag
        self.norm = np.log2(mag2) * 0.5

        t3 = time.perf_counter()

        # avg = self.avg_rdm()
        avg = self.norm.reshape(RX * TX, SLOW_TIME * FAST_TIME).mean(axis=0)
        # print(np.mean(avg))
        # avg *= 255.0 / avg.max()
        avg = (avg - avg.min()) / (avg.max() - avg.min()) * 255.0
        # avg = avg.astype(np.uint8)

        t4 = time.perf_counter()

        avg = avg.reshape((SLOW_TIME, FAST_TIME))
        avg = np.fft.fftshift(avg, axes=(0))
        t5 = time.perf_counter()

        dt = (time.perf_counter() - t0) * 1e6
        dt2 = (t1 - t0) * 1e6
        dt3 = (t2 - t1) * 1e6
        dt4 = (t3 - t2) * 1e6
        dt5 = (t4 - t3) * 1e6
        dt6 = (t5 - t4) * 1e6
        # print(f"RDM frame processed in {dt:.0f} us")
        # print(f"Cube frame processed in {dt2:.0f} us")
        # print(f"FFT frame processed in {dt3:.0f} us")
        # print(f"Norm frame processed in {dt4:.0f} us")
        # print(f"Average frame processed in {dt5:.0f} us")
        # print(f"Shift frame processed in {dt6:.0f} us")

        return avg.ravel()

    def get_clean_rdm(self):
        rdm_complex = self.fftw_out.copy()  # Shape: (TX * RX, SLOW_TIME, FAST_TIME)

        # Reshape from (TX * RX, SLOW_TIME, FAST_TIME) to (TX, RX, SLOW_TIME, FAST_TIME)
        rdm_reshaped = rdm_complex.reshape((TX, RX, SLOW_TIME, FAST_TIME))

        # Transpose to (SLOW_TIME, RX, TX, FAST_TIME) to match angle.py expectations
        rdm_final = rdm_reshaped.transpose(2, 1, 0, 3)

        rdm_final = np.fft.fftshift(rdm_final, axes=0)

        return rdm_final

    def process_with_mimo_data(self):
        """
        Process and return both averaged RDM and clean MIMO data.

        Returns:
            tuple: (averaged_rdm_flat, clean_mimo_rdm)
            - averaged_rdm_flat: 1D array for visualization/CFAR
            - clean_mimo_rdm: 4D complex array for angle estimation
        """
        # Run normal processing
        avg_rdm = self.process()

        # Get clean MIMO data
        clean_mimo = self.get_clean_rdmap_post_bpm()

        return avg_rdm, clean_mimo

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
        print(avg.dtype)
        return avg.ravel()


if __name__ == "__main__":
    rd = RangeDoppler()
    test = np.linspace(0, 1, SIZE_W_IQ, dtype=np.float32)
    rd.set_buffer(test)
    out = rd.process()
    print(out[:8])
