# Angle of Arrival (AoA) Estimation

After detecting a target at a specific Range and Doppler, we need to know **where** it is (Azimuth/Angle). We use MIMO (Multiple-Input Multiple-Output) beamforming.

## 1. The Virtual Array (MIMO)

A standard radar might have 1 TX and 4 RX antennas. By using 3 TX antennas firing sequentially, we can synthesize a **Virtual Array** of up to 12 antennas ($3 \times 4$):
-   **Horizontal (Azimuth)**: The code uses `tx=1` and `tx=3` which are on the same horizontal row to build an 8-element horizontal virtual array.
-   **Vertical (Elevation)**: `tx=2` is typically offset vertically. While the code *builds* a 2D virtual array structure in `buildVirtualArray`, the current processing only uses the horizontal components.

## 2. Phase-Based Direction Finding (1D vs 2D)

When a signal hits the antennas at an angle, it arrives at each antenna at a slightly different time. This causes a **phase shift** across the array.
-   If the target is dead ahead, the phase is the same across all antennas.
-   If the target is to the left, the signal hits antenna 1 first, antenna 2 second, etc.

By performing an **FFT across the antennas** for a specific detection point, we can identify the frequency of this phase shift, which directly maps to the physical angle.

## 3. Super-Resolution (Zero-Padding)

Physical antenna arrays are small (usually only a few elements). A raw 12-point FFT would give very "chunky" angle steps (e.g., 15-degree increments).

-   **The Trick**: We **Zero-Pad** the 12 antenna samples to 256 or 512 points before the FFT.
-   **Effect**: This doesn't add "new" information, but it **interpolates** the result, allowing us to find the peak far more precisely (e.g., 0.5-degree resolution).

## 4. Current Implementation Status: Azimuth Only

Currently, the `angle_fft` function is optimized for **horizontal detection (Azimuth)**:
-   It only extracts the phase data from the horizontal transmit pair (`tx=1`).
-   It performs a **1D FFT**, mapping the target to a position on the horizon.

### Roadmap: Adding Elevation
To add elevation (2D AoA), the pipeline would need:
1.  **2D Virtual Array Extraction**: Using `tx=2` data to fill the vertically offset slots.
2.  **2D FFT or 2D MUSIC**: Performing a Fourier transform across both the horizontal and vertical dimensions of the data cube.
3.  **Spherical Mapping**: Converting the 2D FFT peaks into both $\theta$ (azimuth) and $\phi$ (elevation) degrees.
