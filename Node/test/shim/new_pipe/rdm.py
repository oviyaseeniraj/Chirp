# Chirp/Node/test/shim/new_pipe/rdm.py
# CPU-only RangeDoppler implemented with NumPy + pyFFTW (pyfftw optional, falls back to numpy.fft)
#
# This file is a clean, CPU-only rewrite of the previous RangeDoppler shim.
# Goals:
#  - Use pyFFTW for repeated 2D FFTs when available (FFTW_MEASURE plan).
#  - Use NumPy for all array ops and as fallback for FFT.
#  - Keep a small, clear API:
#      - set_buffer(flat_iq_floats)
#      - process() -> returns averaged, scaled, fftshifted RDM (flattened)
#      - accessors for intermediate arrays for testing/inspection.
#
# Notes:
#  - The input layout expected is interleaved I/Q floats with shape:
#        (TX, RX, SLOW_TIME, FAST_TIME, IQ)
#    flattened in C-order (TX major -> RX -> SLOW_TIME -> FAST_TIME -> IQ)
#  - shape_cube applies a window across the FAST_TIME axis (range axis) and
#    converts interleaved floats to complex samples (I + jQ).
#  - compute_range_doppler performs a 2D FFT across (SLOW_TIME, FAST_TIME)
#    for each virtual antenna (TX*RX), using a precomputed FFTW plan when possible.
#  - compute_mag_norm computes log2(|X|^2) / 2 analogous to the earlier implementation.
#
# Author: Assistant (converted to CPU-only, pyFFTW + NumPy)
# Location: Chirp/Node/test/shim/new_pipe/rdm.py

from __future__ import annotations

import time
import typing
import warnings

import numpy as np

# Try to import pyfftw for accelerated FFTs. If not available, we fall back to numpy.fft.
import pyfftw

HAS_PYFFTW = pyfftw is not None

# Keep constants consistent with the rest of the project
FAST_TIME = 512
SLOW_TIME = 64
RX = 4
TX = 3
IQ = 2

SIZE_W_IQ = (
    TX * RX * SLOW_TIME * FAST_TIME * IQ
)  # number of float entries (I/Q interleaved)
SIZE = TX * RX * SLOW_TIME * FAST_TIME  # number of complex samples


class RangeDoppler:
    """
    CPU-only RangeDoppler processing class using NumPy and pyFFTW (if available).

    Usage:
        rd = RangeDoppler(window="blackman")
        rd.set_buffer(iq_flat)  # length SIZE_W_IQ
        rdm_avg = rd.process()  # returns flattened SLOW_TIME * FAST_TIME float32 array

    Attributes that may be useful for tests/inspection:
        - adc_mid: interleaved float buffer after windowing (flat length SIZE_W_IQ)
        - adc_data: complex samples (flat length SIZE)
        - rdm_data: complex RDM (flat length SIZE)
        - rdm_norm: magnitude/log values (flat length SIZE)
        - rdm_avg: averaged, scaled and fftshifted RDM (flat length SLOW_TIME * FAST_TIME)
    """

    def __init__(self, window: str = "blackman"):
        self.WINDOW_TYPE = window.lower() if window is not None else "none"

        # Buffers (all CPU / NumPy)
        self.adc_data_flat: np.ndarray = np.zeros(SIZE_W_IQ, dtype=np.float32)
        self.adc_mid: np.ndarray = np.zeros(
            SIZE_W_IQ, dtype=np.float32
        )  # interleaved floats after window
        self.adc_data: np.ndarray = np.zeros(
            SIZE, dtype=np.complex64
        )  # complex ADC data per sample

        # RDM and working arrays
        self.rdm_data: np.ndarray = np.zeros(SIZE, dtype=np.complex64)
        self.rdm_norm: np.ndarray = np.zeros(SIZE, dtype=np.float32)
        self.rdm_avg: np.ndarray = np.zeros(SLOW_TIME * FAST_TIME, dtype=np.float32)
        self.prev_rdm_avg: np.ndarray = np.zeros(
            SLOW_TIME * FAST_TIME, dtype=np.float32
        )
        self.zero_rdm_avg: np.ndarray = np.zeros(
            SLOW_TIME * FAST_TIME, dtype=np.float32
        )

        # Precompute windows
        self._blackman = np.blackman(FAST_TIME).astype(np.float32)
        self._hann = np.hanning(FAST_TIME).astype(np.float32)
        self._nowindow = np.ones(FAST_TIME, dtype=np.float32)

        # FFTW plan and aligned buffers (only if pyFFTW is available)
        self._use_pyfftw = HAS_PYFFTW
        self._fftw_plan = None
        self._fftw_in = None
        self._fftw_out = None
        if self._use_pyfftw:
            try:
                # Allocate aligned arrays with shape (howmany, SLOW_TIME, FAST_TIME)
                self._howmany = TX * RX
                fft_shape = (self._howmany, SLOW_TIME, FAST_TIME)
                # Use complex64 aligned arrays for input and output
                self._fftw_in = pyfftw.empty_aligned(fft_shape, dtype="complex64")
                self._fftw_out = pyfftw.empty_aligned(fft_shape, dtype="complex64")
                # Create an FFTW plan (forward) that will be reused.
                # FFT over axes (1,2) which correspond to SLOW_TIME and FAST_TIME in our layout.
                self._fftw_plan = pyfftw.FFTW(
                    self._fftw_in,
                    self._fftw_out,
                    axes=(1, 2),
                    direction="FFTW_FORWARD",
                    flags=("FFTW_MEASURE",),
                )
            except Exception as e:
                warnings.warn(
                    f"pyFFTW plan initialization failed, falling back to numpy.fft: {e}"
                )
                self._use_pyfftw = False

        # Frame counter for parity with previous implementation
        self.frame = 1

    # --------------------
    # Small API helpers
    # --------------------
    def set_buffer(self, arr: typing.Union[np.ndarray, typing.List[float]]):
        """Set the raw interleaved I/Q float buffer (1D length SIZE_W_IQ)."""
        a = np.asarray(arr, dtype=np.float32)
        if a.size != SIZE_W_IQ:
            raise ValueError(
                f"set_buffer expects array of length {SIZE_W_IQ}, got {a.size}"
            )
        self.adc_data_flat = a.copy()

    def get_buffer(self) -> np.ndarray:
        """Return a copy of the raw interleaved I/Q float buffer."""
        return self.adc_data_flat.copy()

    def get_rdm_avg(self) -> np.ndarray:
        """Return a copy of the current averaged RDM (float32, flattened)."""
        return self.rdm_avg.copy()

    # --------------------
    # Window selection
    # --------------------
    def _select_window(self) -> np.ndarray:
        if self.WINDOW_TYPE == "blackman":
            return self._blackman
        elif self.WINDOW_TYPE == "hann":
            return self._hann
        else:
            return self._nowindow

    # ------------------------------
    # shape_cube: vectorized CPU-only implementation
    # ------------------------------
    def shape_cube(
        self, inp: typing.Union[np.ndarray, typing.List[float]]
    ) -> np.ndarray:
        """
        Vectorized conversion from interleaved I/Q floats (flat) to complex samples.

        Input layout assumed: flattened (TX, RX, SLOW_TIME, FAST_TIME, IQ) in C-order.
        Applies window across the FAST_TIME axis (range), same factor for I and Q,
        and converts each pair (I,Q) -> I + j Q. Returns flat complex64 array length SIZE.

        Also updates internal buffers `adc_mid` (interleaved floats after window)
        and `adc_data` (complex samples flattened).
        """
        inp_np = np.asarray(inp, dtype=np.float32)

        # Reshape into (TX, RX, SLOW_TIME, FAST_TIME, IQ)
        arr = inp_np.reshape((TX, RX, SLOW_TIME, FAST_TIME, IQ))

        # Select window across FAST_TIME axis; shape broadcast to match arr
        window = self._select_window()  # length FAST_TIME
        # broadcasting: (1,1,1,FAST_TIME,1)
        arr_windowed = arr * window[np.newaxis, np.newaxis, np.newaxis, :, np.newaxis]

        # Save adc_mid as flattened interleaved floats (same ordering)
        self.adc_mid[:] = arr_windowed.ravel().astype(np.float32)

        # Convert last axis IQ -> complex samples (I + j Q)
        complex_samples = (arr_windowed[..., 0] + 1j * arr_windowed[..., 1]).astype(
            np.complex64
        )

        # Flatten complex samples in the same C-order (TX major ... FAST_TIME, then collapse)
        out = complex_samples.ravel()
        self.adc_data[:] = out
        return out

    # -----------------------------------
    # compute_range_doppler: pyFFTW-accelerated 2D FFT per virtual antenna
    # -----------------------------------
    def compute_range_doppler(
        self, data: typing.Optional[np.ndarray] = None
    ) -> np.ndarray:
        """
        Compute 2D FFT (SLOW_TIME x FAST_TIME) for each virtual antenna (TX*RX).

        Args:
            data: optional complex input flattened length SIZE. If None, uses internal adc_data.

        Returns:
            flattened complex64 array (length SIZE) containing RDM per virtual antenna concatenated.
        """
        if data is None:
            data = self.adc_data

        data_np = np.asarray(data, dtype=np.complex64)
        if data_np.size != SIZE:
            raise ValueError(f"compute_range_doppler expects input length {SIZE}")

        howmany = TX * RX
        # reshape to (howmany, SLOW_TIME, FAST_TIME)
        data_reshaped = data_np.reshape((howmany, SLOW_TIME, FAST_TIME))

        if self._use_pyfftw and self._fftw_plan is not None:
            # copy input into fftw-aligned input and execute plan
            # pyfftw arrays are contiguous; ensure casting to complex64 and C-order
            # copy element-wise into pre-allocated buffer to avoid reallocations
            np.copyto(self._fftw_in, data_reshaped)
            # execute FFTW plan (in-place uses _fftw_out)
            self._fftw_plan()
            rdm = self._fftw_out.copy()
        else:
            # fallback to numpy
            rdm = np.fft.fft2(data_reshaped, axes=(1, 2)).astype(np.complex64)

        rdm_flat = rdm.ravel()
        self.rdm_data[:] = rdm_flat
        return rdm_flat

    # -----------------------------------
    # compute_mag_norm: returns magnitude/log array
    # -----------------------------------
    def compute_mag_norm(
        self, rdm_complex: typing.Optional[np.ndarray] = None
    ) -> np.ndarray:
        """
        Compute log2(|X|^2) / 2 for each sample in the (flattened) RDM complex array.
        """
        if rdm_complex is None:
            rdm_complex = self.rdm_data
        rdm_np = np.asarray(rdm_complex, dtype=np.complex64)
        if rdm_np.size != SIZE:
            raise ValueError(f"compute_mag_norm expects length {SIZE}")

        # magnitude squared
        mag2 = np.abs(rdm_np) ** 2
        # safety floor to avoid log(0)
        mag2_safe = np.maximum(mag2, 1e-12)
        mag_log = (np.log2(mag2_safe) / 2.0).astype(np.float32)
        self.rdm_norm[:] = mag_log
        return mag_log

    # -----------------------------------
    # scale_rdm_values: scale array to 0-255 and return new array
    # -----------------------------------
    @staticmethod
    def scale_rdm_values(arr: np.ndarray, max_val: float, min_val: float) -> np.ndarray:
        if max_val == min_val:
            return np.zeros_like(arr, dtype=np.float32)
        scale = 255.0 / (max_val - min_val)
        return ((arr - min_val) * scale).astype(np.float32)

    # -----------------------------------
    # fftshift_rdm: fftshift 2D flattened array (SLOW_TIME x FAST_TIME)
    # -----------------------------------
    @staticmethod
    def fftshift_rdm(arr: np.ndarray) -> np.ndarray:
        if arr.size != SLOW_TIME * FAST_TIME:
            raise ValueError(
                "fftshift_rdm expects flattened array length SLOW_TIME*FAST_TIME"
            )
        mat = arr.reshape((SLOW_TIME, FAST_TIME))
        shifted = np.fft.fftshift(mat, axes=(0, 1))
        return shifted.ravel()

    # -----------------------------------
    # averaged_rdm: average across virtual antennas, scale, and fftshift
    # -----------------------------------
    def averaged_rdm(self, rdm_norm: np.ndarray) -> np.ndarray:
        """
        Average the rdm_norm across virtual antennas (axis 0) and produce a
        scaled (0-255) and fftshifted flattened output.
        Input:
            rdm_norm: flattened array length (TX*RX * SLOW_TIME * FAST_TIME)
        Returns:
            flattened SLOW_TIME * FAST_TIME float32 array (fftshifted and scaled)
        """
        vants = TX * RX
        rd_bins = SLOW_TIME * FAST_TIME

        arr = np.asarray(rdm_norm, dtype=np.float32)
        if arr.size != vants * rd_bins:
            raise ValueError(f"averaged_rdm expects length {vants * rd_bins}")

        rdm_mat = arr.reshape((vants, rd_bins))
        avg = rdm_mat.mean(axis=0).astype(np.float32)

        max_val = float(avg.max()) if avg.size > 0 else 1.0
        min_val = float(avg.min()) if avg.size > 0 else 0.0

        scaled = self.scale_rdm_values(avg, max_val, min_val)
        shifted = self.fftshift_rdm(scaled)

        self.rdm_avg[:] = shifted
        return shifted

    # ------------------------------
    # remove_zero_dop: parity helper, returns copy
    # ------------------------------
    def remove_zero_dop(self, rdm_avg: np.ndarray) -> np.ndarray:
        return rdm_avg.copy()

    # ------------------------------
    # process: high-level pipeline, returns averaged rdm array (flattened)
    # ------------------------------
    def process(self) -> np.ndarray:
        """
        Full pipeline:
         - shape_cube from adc_data_flat -> complex ADC samples
         - compute_range_doppler -> flattened complex RDM
         - compute_mag_norm -> magnitude/log values
         - averaged_rdm -> scale and shift -> averaged RDM (returned)
        """
        start_ts = time.perf_counter()

        if self.adc_data_flat.size != SIZE_W_IQ:
            raise ValueError(f"adc_data_flat must be length {SIZE_W_IQ}")

        if self.frame <= 1:
            self.prev_rdm_avg.fill(0.0)
        else:
            self.prev_rdm_avg[:] = self.zero_rdm_avg[:]

        adc_complex = self.shape_cube(self.adc_data_flat)

        rdm = self.compute_range_doppler(adc_complex)

        rdm_norm = self.compute_mag_norm(rdm)

        rdm_avg = self.averaged_rdm(rdm_norm)

        # zero-dop copy for next-frame parity
        self.zero_rdm_avg[:] = self.remove_zero_dop(rdm_avg)

        self.frame += 1
        end_ts = time.perf_counter()
        duration_us = (end_ts - start_ts) * 1e6
        # Print a compact processing time message for quick diagnostics
        print(f"Frame: {self.frame} Process Time: {duration_us:.0f} microseconds")

        return rdm_avg


# ------------------------------
# Simple smoke test when run directly
# ------------------------------
if __name__ == "__main__":
    rd = RangeDoppler(window="blackman")
    # synthetic increasing I/Q pattern
    test = np.linspace(0.0, 1.0, SIZE_W_IQ, dtype=np.float32)
    rd.set_buffer(test)
    rdm_avg = rd.process()
    print("rdm_avg[0:8] =", rdm_avg[:8])
    # Show whether pyFFTW was used
    print("pyFFTW used:", rd._use_pyfftw)
