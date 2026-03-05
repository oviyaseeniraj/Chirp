# CFAR Detection (Constant False Alarm Rate)

Once we have an RDM heatmap, we need to distinguish "real" targets from the random noise Floor. CFAR is an adaptive thresholding algorithm.

## 1. The Problem: Dynamic Noise
Radar noise isn't constant. Interference, thermal noise, and ground clutter change the "brightness" of the RDM map constantly. A fixed threshold (e.g., "anything above 50 is a target") would either miss faint targets or be overwhelmed by noise.

## 2. Cell-Averaging CFAR (CA-CFAR)

For every single pixel (Cell Under Test - **CUT**) in the RDM map, we look at its neighbors:
1.  **Guard Cells**: A small border immediately around the CUT that we ignore. This prevents the target's own energy from "leaking" into the noise estimate.
2.  **Training Cells**: A larger outer window. We calculate the **average power** of these cells.
3.  **The Test**: If `CUT > (Training_Average * Factor)`, we mark it as a detection.

## 3. Optimization: Integral Images

Calculating a sliding window average for a 512x64 map is slow ($O(N \times M \times \text{window\_size})$). To achieve high FPS, we use **Integral Images** (also known as Summed Area Tables).

-   **Pre-computation**: We create a new map where each pixel $(x, y)$ stores the sum of all pixels above and to the left of it.
-   **The Magic**: The sum of *any* rectangular window can now be calculated using only **4 lookups** and **3 subtractions**, regardless of how big the window is!
-   **Speed**: This reduces the complexity to $O(N \times M)$, allowing the entire RDM to be processed in a few milliseconds on a single CPU core.

## 4. PyTorch Acceleration
The entire process is vectorized using PyTorch tensors. If a GPU (CUDA) is available, the threshold test for all 32,768 pixels happens simultaneously in parallel.
