#!/usr/bin/env python3
"""Decode tb_uart.txt (UART bytes from the testbench) and measure the voice-band SNDR of both streams."""
import os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "model"))
import voice_model as vm

by = np.array([int(l, 16) for l in open(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "tb_uart.txt")) if l.strip()])
i0 = int(np.argmax(by >= 128)); by = by[i0:len(by) - (len(by) - i0) % 4].reshape(-1, 4)
assert np.all(by[:, 0] >= 128) and np.all(by[:, 1:] < 128), "frame sync lost"
def s14(hi, lo):
    v = ((hi & 0x7F) << 7) | lo
    return np.where(v >= 8192, v - 16384, v).astype(float)
ref, swar = s14(by[:, 0], by[:, 1]), s14(by[:, 2], by[:, 3])
FS = 100e6 / 104 / 60
print(f"{len(ref)} frames at {FS:.2f} S/s; ref peak {np.abs(ref[300:]).max():.0f}, swar peak {np.abs(swar[300:]).max():.0f} (full scale 4096)")
# 4-term Blackman-Harris window (-92 dB sidelobes): the tone is not coherent with the record length
def sndr(y, fin=1000.0, band=7000.0):
    n = len(y); w = np.array([0.35875, -0.48829, 0.14128, -0.01168]) @ np.cos(2 * np.pi * np.outer(np.arange(4), np.arange(n)) / n)
    X = np.abs(np.fft.rfft((y - y.mean()) * w)) ** 2; f = np.fft.rfftfreq(n, 1 / FS)
    k0 = int(round(fin * n / FS)); sig = X[k0 - 6:k0 + 7].sum()
    m = (f > 50) & (f <= band); m[k0 - 6:k0 + 7] = False
    return 10 * np.log10(sig / X[m].sum())
y0 = 300
for name, y in (("reference (12-bit XADC path)", ref), ("Swar (chip LUT, 8-bit)", swar)):
    d = sndr(y[y0:])
    print(f"{name:30s} SNDR {d:5.1f} dB  ENOB {(d - 1.76) / 6.02:5.2f}   ({len(y) - y0} samples, 50 Hz - 7 kHz)")
