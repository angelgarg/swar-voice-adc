#!/usr/bin/env python3
"""Measure the live Basys3 streams through the running demo server (demo/live_demo.py --bridge ...).
With SW15 up (built-in 1 kHz tone) it reports the voice-band SNDR of both paths on real hardware.
usage: measure_board.py [seconds] [server url]"""
import json, sys, urllib.request
import numpy as np
sec = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0
url = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8765"
r = json.load(urllib.request.urlopen(f"{url}/api/board/raw?sec={sec}", timeout=sec + 10))
if "error" in r: sys.exit(r["error"])
FS = r["fs"]
for name in ("ref", "swar"):
    y = np.array(r[name], float); n = len(y)
    w = np.array([0.35875, -0.48829, 0.14128, -0.01168]) @ np.cos(2 * np.pi * np.outer(np.arange(4), np.arange(n)) / n)
    X = np.abs(np.fft.rfft((y - y.mean()) * w)) ** 2; f = np.fft.rfftfreq(n, 1 / FS)
    band = (f > 50) & (f <= 7000)
    k0 = int(np.argmax(np.where(band, X, 0))); sig = X[k0 - 6:k0 + 7].sum()
    m = band.copy(); m[k0 - 6:k0 + 7] = False
    sndr = 10 * np.log10(sig / X[m].sum())
    print(f"{name:5s} mean {y.mean():8.1f}  peak {np.abs(y - y.mean()).max():7.1f} ({20*np.log10(np.abs(y-y.mean()).max()/4096+1e-9):6.1f} dBFS)  rms {y.std():7.2f}  "
          f"strongest tone {f[k0]:7.1f} Hz  SNDR {sndr:5.1f} dB  ENOB {(sndr - 1.76) / 6.02:5.2f}   ({n} samples)")
