# Range-Doppler Matrix (RDM)

The RDM is the first major step in the signal processing pipeline. It transforms raw time-domain radar data into a 2D map representing **Range** (distance) and **Doppler** (velocity).

## 1. Data Structure

The input data is a 1D stream of complex IQ samples. These are reshaped into a 3D "Data Cube" with dimensions:
-   **TX/RX Channels**: The specific antenna pair.
-   **Slow Time (Chirps)**: Successive pulses (used for velocity).
-   **Fast Time (Samples)**: Samples within a single pulse (used for range).

## 2. The 2D FFT Process

To get from time to frequency, we perform two Fourier Transforms:

1.  **Fast-Time FFT (Range FFT)**: Applied across each individual chirp. It converts the time delay of reflections into frequency peaks. Higher frequency = further distance.
2.  **Slow-Time FFT (Doppler FFT)**: Applied across the same sample index over multiple chirps. It detects phase shifts between chirps caused by moving targets. Higher frequency = faster velocity.

## 3. Optimizations & Enhancements

### Windowing (Blackman)
Before the FFT, we multiply the data by a **Blackman window**.
-   **Why?** Raw FFTs assume the signal is perfectly periodic. Abrupt cuts at the edges cause "spectral leakage" (fake side-lobes).
-   **Effect**: It smooths the edges, sacrificing a tiny bit of resolution for a much cleaner signal with fewer "ghost" detections.

### IIR Filtering (Static Clutter Removal)
We use an Infinite Impulse Response (IIR) filter to track the "stationary" background.
-   **Logic**: `background = alpha * current + (1 - alpha) * background`.
-   **Effect**: By subtracting this background from the current frame, we effectively "delete" static objects like walls and chairs, making moving targets stand out.

### Magnitude & Normalization
Finally, we compute the magnitude squared and convert to a logarithmic scale (`log2`) to ensure we can see both very faint and very strong reflections simultaneously.
