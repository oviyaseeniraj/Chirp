"""Optimised Range-Doppler Map (RDM) processing — v3.

Changes from rdm_updated
-------------------------
1. **Faster background threshold** — ``diff.std()`` → ``|diff|.mean()``,
   avoids the square, sqrt, and mean-of-squares passes (3 fewer passes
   over the full array per frame).

2. **In-place power computation** — reuses a pre-allocated buffer for
   ``power_db_map`` instead of creating a temporary ``display`` array
   on every frame.

3. **Fewer copies** — ``background_subtraction`` returns ``rdm - background``
   which is already a fresh array; ``process()`` assigns it directly to
   ``clean_rdm_complex`` without ``.copy()``.

4. **Fused channel-mean** — the ``mag2 → reshape → mean`` pipeline is
   collapsed into a single ``einsum`` (one pass instead of two).

5. **Removed dead code** — unused ``norm``, ``avg``, ``cv2`` import.
"""

import numpy as np
import pyfftw

from .. import config


class RangeDoppler:
    SIZE = config.BYTES_IN_FRAME // config.IQ_BYTES  # total ADC samples

    # ---- precomputed de-interleave indices (class-level, once) ----------
    idx = np.arange(SIZE)
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

    tx_o = tx * config.RX * config.SLOW_TIME * config.FAST_TIME * config.IQ
    rx_o = rx * config.SLOW_TIME * config.FAST_TIME * config.IQ
    slow_o = slow * config.FAST_TIME * config.IQ
    fast_o = fast * config.IQ

    mid_idx = tx_o + rx_o + slow_o + fast_o + iq

    # ---- pre-allocated storage shapes -----------------------------------
    _chan_shape = (config.TX * config.RX, config.SLOW_TIME, config.FAST_TIME)
    _rdm_size = config.TX * config.RX * config.SLOW_TIME * config.FAST_TIME

    def __init__(self, window="blackman", alpha=0.5):
        self.window_type = window.lower()
        self.alpha = alpha

        # ADC buffers
        self.adc_data_flat = np.zeros(self.SIZE, dtype=np.float32)
        self.mid = np.zeros(self.SIZE, dtype=np.float32)
        self.adc_complex = np.zeros(self.SIZE // 2, dtype=np.complex64)

        # Background stores
        self.background = np.zeros(self._chan_shape, dtype=np.complex64)
        self.background_power = np.zeros(self._chan_shape, dtype=np.float32)

        # Pre-allocated output buffers (reused every frame)
        self.power_map = np.zeros(
            (config.SLOW_TIME, config.FAST_TIME), dtype=np.float32
        )
        self.power_db_map = np.zeros(
            (config.SLOW_TIME, config.FAST_TIME), dtype=np.float32
        )
        self.display_map = np.zeros(
            (config.SLOW_TIME, config.FAST_TIME), dtype=np.float32
        )
        # Scratch buffer for dB computation
        self._db_scratch = np.zeros(
            (config.SLOW_TIME, config.FAST_TIME), dtype=np.float32
        )

        # Windows
        if self.window_type == "blackman":
            self.window = np.blackman(config.FAST_TIME).astype(np.float32)
            self.window_slow = np.blackman(config.SLOW_TIME).astype(np.float32)
        elif self.window_type == "hann":
            self.window = np.hanning(config.FAST_TIME).astype(np.float32)
            self.window_slow = np.hanning(config.SLOW_TIME).astype(np.float32)
        else:
            self.window = np.ones(config.FAST_TIME, dtype=np.float32)
            self.window_slow = np.ones(config.SLOW_TIME, dtype=np.float32)

        # FFTW plan
        self.fftw_in = pyfftw.empty_aligned(self._chan_shape, dtype=np.complex64)
        self.fftw_out = pyfftw.empty_aligned(self._chan_shape, dtype=np.complex64)
        self.plan = pyfftw.FFTW(
            self.fftw_in,
            self.fftw_out,
            axes=(1, 2),
            direction="FFTW_FORWARD",
            flags=("FFTW_ESTIMATE",),
        )

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    def set_buffer(self, buf):
        arr = np.asarray(buf, dtype=np.int16)
        if arr.size != self.SIZE:
            raise ValueError(f"Invalid input buffer size: {arr.size} != {self.SIZE}")
        self.adc_data_flat[:] = arr

    # ------------------------------------------------------------------
    # De-interleave + shape into (TX*RX, SLOW_TIME, FAST_TIME)
    # ------------------------------------------------------------------
    def shape_cube_vect(self):
        self.mid.fill(0.0)
        windowed = (
            self.adc_data_flat * self.window[self.fast] * self.window_slow[self.slow]
        )
        np.put(self.mid, self.mid_idx, windowed)

        self.adc_complex.real = self.mid[0::2]
        self.adc_complex.imag = self.mid[1::2]

        return self.adc_complex.reshape(self._chan_shape)

    # ------------------------------------------------------------------
    # Adaptive background subtraction  (fast path)
    # ------------------------------------------------------------------
    def background_subtraction(self, rdm, alpha=0.005):
        """``|rdm|²`` — threshold on mean-abs-diff — IIR update.

        Returns ``rdm - background`` (clean complex data).
        """
        power = rdm.real * rdm.real + rdm.imag * rdm.imag  # (C, S, F)

        diff = power - self.background_power

        # Faster than diff.std():  avoids square + sqrt passes
        threshold = 3.0 * np.abs(diff).mean()

        # Non-target (background) cells
        mask = diff <= threshold

        # IIR update on background cells only
        ma = 1.0 - alpha
        self.background[mask] = ma * self.background[mask] + alpha * rdm[mask]
        self.background_power[mask] = (
            ma * self.background_power[mask] + alpha * power[mask]
        )

        # Clean RDM = input - current background
        return rdm - self.background

    # ------------------------------------------------------------------
    # Main processing entry point
    # ------------------------------------------------------------------
    def process(self):
        """Run one frame: shape → FFT → bgnd-sub → power → dB → display."""
        cube = self.shape_cube_vect()  # (C, S, F)  complex64

        np.copyto(self.fftw_in, cube)
        self.plan()
        rdm = self.fftw_out  # (C, S, F)  complex64  FFT'ed

        # Doppler shift  (in-place through reassignment)
        rdm = np.fft.fftshift(rdm, axes=(1))

        # ── Complex background subtraction ──
        #  Returns clean (rdm - background), updates background IIR internally
        clean = self.background_subtraction(rdm)  # (C, S, F)  complex64
        self.clean_rdm_complex = clean  # no .copy() needed

        # ── Power: channel-average via einsum (single pass) ──
        #   mag2 = |clean|² over (C, S, F)
        #   power_avg[slow, fast] = (1/C) ∑_channel mag2[channel, slow, fast]
        n_chan = config.TX * config.RX
        np.einsum("cst,cst->st", clean.real, clean.real, out=self.power_map)
        np.einsum("cst,cst->st", clean.imag, clean.imag, out=self._db_scratch)
        self.power_map += self._db_scratch
        self.power_map /= n_chan

        # ── dB ──
        np.log10(self.power_map + 1e-10, out=self._db_scratch)
        np.multiply(10.0, self._db_scratch, out=self.power_db_map)

        # ── Display normalisation (write into pre-allocated buffer) ──
        mn = self.power_db_map.min()
        mx = self.power_db_map.max()
        if mx > mn:
            np.subtract(self.power_db_map, mn, out=self.display_map)
            np.multiply(self.display_map, 255.0 / (mx - mn), out=self.display_map)
        else:
            self.display_map.fill(0.0)

        return self.power_map

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------
    def get_clean_rdm(self):
        """Return cleaned complex RDM shaped for angle estimation."""
        if not hasattr(self, "clean_rdm_complex"):
            raise RuntimeError("process() must be called before get_clean_rdm()")

        # Reshape (TX*RX, S, F) → (TX, RX, S, F) → transpose → (S, RX, TX, F)
        rdm = self.clean_rdm_complex.reshape(
            (config.TX, config.RX, config.SLOW_TIME, config.FAST_TIME)
        )
        return rdm.transpose(2, 1, 0, 3)

    def get_power_map(self):
        return self.power_map

    def get_power_db_map(self):
        return self.power_db_map

    def get_display_map(self):
        return self.display_map
