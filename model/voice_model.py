#!/usr/bin/env python3
"""Voice / keyword-spotting application model (Basys3 decimation -> ESP32-S3): the post-layout ADC at 2 MS/s, CIC + FIR
decimation to 16 kS/s, voice-band SNR / SNDR / ENOB, compared with an ideal 8-bit and an ideal 16-bit converter.
ADC model (Rev3.2, compensated DAC, extracted RC netlist):
  transition level of code k = DAC level of code k (static DC sweep of the RC-extracted analog core, all 256 codes,
  data/adc_transfer/full_<corner>.txt) + comparator offset (PMOS comparator for trial codes < 64, NMOS from 64:
  from the full-loop RC transistor-level dense runs: T16 = 16.17, T64 = 63.92, T128 = 128.42 LSB at TT)
  + comparator input noise (Gaussian, sigma swept: not characterised yet).
Decimation (what the Basys3 implements): CIC 4th order, R = 25 (2 MS/s -> 80 kS/s), then a 127-tap FIR (passband
0-7 kHz with CIC droop compensation, stopband from 8 kHz) decimating by 5 (-> 16 kS/s).
usage: voice_model.py [--corner NOM] [--out results/voice_model.txt]"""
import os, sys, argparse
import numpy as np
from scipy import signal

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
W = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
FS, R1, R2, FS_OUT = 2.0e6, 25, 5, 16e3
VDD = {"NOM": 5.0, "SLOW": 4.5, "FAST": 5.5}

def adc_levels(corner):
    v = {}
    for l in open(f"{W}/adc_transfer/full_{corner}.txt"):
        t = l.split(); v[int(float(t[0]))] = float(t[1])
    vdd = VDD[corner]; L = (vdd - 1.0) / 256
    dac = np.array([(v[k] - 1.0) / L for k in range(256)])          # DAC level of code k, in LSB
    # comparator offsets from the full-loop RC runs (TT): measured transition - DAC level of that code
    vos_p = 16.17 - dac[16]
    vos_n = np.mean([63.92 - dac[64], 128.42 - dac[128]])
    T = dac.copy()
    T[1:64] += vos_p; T[64:] += vos_n
    return T, vos_p, vos_n, L, vdd

def convert(x_lsb, T, sigma, rng):
    """SAR conversion with transition levels T (T[k] = input in LSB where the code becomes >= k); noise per conversion"""
    xn = x_lsb + rng.normal(0.0, sigma, x_lsb.shape) if sigma > 0 else x_lsb
    return np.clip(np.searchsorted(T[1:], xn, side="right"), 0, 255).astype(float)

def decimator():
    # CIC 4th order R1: transfer (sin(pi f R1/fs)/(R1 sin(pi f/fs)))^4 ; FIR at 80 kS/s with droop compensation
    fs1 = FS / R1; n = 127
    f = np.linspace(0, fs1 / 2, 512)
    cic = np.abs(np.sinc(f * R1 / FS) / np.sinc(f / FS)) ** 4
    gain = np.where(f <= 7000, 1.0 / np.maximum(cic, 1e-6), 0.0)
    gain = np.where((f > 7000) & (f < 8000), 0.0, gain)
    h = signal.firwin2(n, f / (fs1 / 2), gain, window=("kaiser", 8.0))
    return h

def decimate(codes, scale=1):
    """CIC as in hardware: integer arithmetic with wrap-around (int64), exact; scale = input LSBs per code unit"""
    x = np.round(np.asarray(codes) * scale).astype(np.int64)
    with np.errstate(over="ignore"):
        for _ in range(4):                   # 4 integrators at FS
            x = np.cumsum(x, dtype=np.int64)
        x = x[R1 - 1::R1]
        for _ in range(4):                   # 4 combs at FS / R1
            x = np.diff(x, prepend=np.int64(0))
    x = x.astype(float) / (R1 ** 4 * scale)
    return x


def fir(x, h):
    return signal.lfilter(h, 1.0, x)[::R2]

def metrics(y, fin, fs, band=7000.0):
    n = len(y); w = np.blackman(n)
    X = np.abs(np.fft.rfft((y - y.mean()) * w)) ** 2
    f = np.fft.rfftfreq(n, 1 / fs)
    k0 = int(round(fin / (fs / n))); sig = X[k0 - 4:k0 + 5].sum()
    inband = (f > 50) & (f <= band)
    mask = inband.copy(); mask[k0 - 4:k0 + 5] = False
    harm = np.zeros_like(mask)
    for h_ in range(2, 6):
        kh = k0 * h_
        if kh + 5 < len(f) and f[kh] <= band: harm[kh - 4:kh + 5] = True
    nd = X[mask].sum(); dist = X[mask & harm].sum(); noise = X[mask & ~harm].sum()
    sndr = 10 * np.log10(sig / nd); snr = 10 * np.log10(sig / noise)
    return sndr, snr, (sndr - 1.76) / 6.02, 10 * np.log10(dist / sig) if dist > 0 else -200.0

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--corner", default="NOM"); ap.add_argument("--out", default="")
    a = ap.parse_args()
    T, vos_p, vos_n, L, vdd = adc_levels(a.corner)
    Ti = np.concatenate([[0.0], np.arange(1, 256, dtype=float)])     # ideal 8-bit
    h = decimator(); rng = np.random.default_rng(1)
    nout = 4096; fin = FS_OUT * 257 / nout                             # 1003.9 Hz, coherent at 16 kS/s
    nsim = (nout + 200) * R1 * R2
    t = np.arange(nsim) / FS
    amp_lsb = 0.89 * 128                                               # -1 dBFS over the 1.0 V .. VDD input range
    x = 128.0 + amp_lsb * np.sin(2 * np.pi * fin * t)
    lines = [f"Voice-band model ({a.corner}, VDD {vdd} V, LSB {L*1e3:.2f} mV): tone {fin:.1f} Hz at -1 dBFS, ADC 2 MS/s -> CIC/R{R1} + FIR/R{R2} -> 16 kS/s, band 50 Hz - 7 kHz",
             f"post-layout ADC: comparator offsets PMOS {vos_p:+.2f} LSB, NMOS {vos_n:+.2f} LSB (hand-over step {vos_n - vos_p:+.2f} LSB at code 64)",
             f"{'converter':34s} {'noise sigma':>11s} {'SNDR dB':>8s} {'SNR dB':>7s} {'ENOB':>6s} {'THD dBc':>8s}   (before decimation: SNDR over 0-1 MHz)"]
    def raw_sndr(codes):
        seg = codes[-65536:]; Xs = np.abs(np.fft.rfft((seg - seg.mean()) * np.blackman(len(seg)))) ** 2
        k0 = int(round(fin / (FS / len(seg)))); s_ = Xs[k0 - 4:k0 + 5].sum(); return 10 * np.log10(s_ / (Xs.sum() - s_))
    for name, TT in (("ideal 8-bit", Ti), (f"post-layout ADC ({a.corner}, extracted)", T)):
        for sg in (0.0, 0.2, 0.35, 0.5):
            c = convert(x, TT, sg, rng)
            y = fir(decimate(c), h)[-nout:]
            sndr, snr, enob, thd = metrics(y, fin, FS_OUT)
            lines.append(f"{name:34s} {sg:11.2f} {sndr:8.1f} {snr:7.1f} {enob:6.2f} {thd:8.1f}   (raw {raw_sndr(c):5.1f} dB)")
    y16 = fir(decimate(np.round(x * 256) / 256, scale=256), h)[-nout:]
    s16 = metrics(y16, fin, FS_OUT)
    lines.append(f"{'ideal 16-bit (reference)':34s} {'-':>11s} {s16[0]:8.1f} {s16[1]:7.1f} {s16[2]:6.2f} {s16[3]:8.1f}")
    txt = "\n".join(lines); print(txt)
    if a.out: open(a.out, "w").write(txt + "\n")
