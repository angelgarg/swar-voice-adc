#!/usr/bin/env python3
"""ROMs for the Basys3 prototype.
  chip_lut.hex  4096 x 8 bit: 12-bit XADC sample -> the 8-bit code our SAR ADC would give (post-layout transition
                levels from model/voice_model.py, nominal corner). 16 XADC steps per chip LSB.
  sine.hex      4096 x 12 bit: one sine period at -1 dBFS for the built-in test tone.
  fir_coef.hex  copy of ../fir_coef.hex (127 taps, Q1.17)."""
import os, shutil, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "model"))
import voice_model as vm

T, *_ = vm.adc_levels("NOM")
x = (np.arange(4096) + 0.5) / 16.0                       # XADC code centre, in chip LSB
lut = np.clip(np.searchsorted(T[1:], x, side="right"), 0, 255)
open(os.path.join(HERE, "chip_lut.hex"), "w").write("".join(f"{v:02x}\n" for v in lut))
s = np.round(2048 + 0.89 * 2048 * np.sin(2 * np.pi * np.arange(4096) / 4096)).astype(int)
open(os.path.join(HERE, "sine.hex"), "w").write("".join(f"{v:03x}\n" for v in s))
shutil.copy(os.path.join(HERE, "..", "fir_coef.hex"), os.path.join(HERE, "fir_coef.hex"))
ideal = np.clip(np.floor(x), 0, 255)
print(f"chip LUT: codes {lut.min()}..{lut.max()}, max deviation from ideal 8-bit {np.max(np.abs(lut - ideal)):.0f} code, "
      f"{np.sum(lut != ideal)} of 4096 entries differ; sine {s.min()}..{s.max()}")
