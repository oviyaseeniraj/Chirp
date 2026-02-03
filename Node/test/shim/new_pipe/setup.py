import numpy as np
import pybind11
from setuptools import Extension, setup

# C++ extension module
ext_modules = [
    Extension(
        "daq_fast",
        ["daq_fast.cpp"],
        include_dirs=[
            pybind11.get_include(),
            pybind11.get_include(user=True),
            np.get_include(),
        ],
        language="c++",
        extra_compile_args=[
            "-std=c++17",
            "-O3",  # Maximum optimization
            "-march=native",  # Optimize for current CPU
            "-mtune=native",  # Tune for current CPU
            "-ffast-math",  # Fast math operations
            "-funroll-loops",  # Unroll loops
            "-finline-functions",  # Aggressive inlining
            "-fomit-frame-pointer",  # Remove frame pointer
            "-flto",  # Link-time optimization
            "-fno-strict-aliasing",  # Allow pointer aliasing
            # "-msse4.2",  # Enable SSE4.2 instructions
            # "-mavx",  # Enable AVX if available
            "-fprefetch-loop-arrays",  # Auto prefetch
            "-Wall",  # All warnings
            "-Wno-unused-result",  # Suppress unused result warnings
        ],
        extra_link_args=[
            "-lpthread",
            "-flto",  # Link-time optimization
            "-O3",  # Optimization at link time
        ],
    ),
]

setup(
    name="daq_fast",
    version="1.0.0",
    author="Chirp Team",
    description="High-performance C++ DAQ implementation for Python",
    ext_modules=ext_modules,
    install_requires=[
        "pybind11>=2.6.0",
        "numpy>=1.19.0",
    ],
    zip_safe=False,
    python_requires=">=3.6",
)
