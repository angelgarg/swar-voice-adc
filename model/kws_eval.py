#!/usr/bin/env python3
"""Keyword-spotting accuracy through the post-layout ADC (voice application: Basys3 decimation -> ESP32-S3 KWS).
Google Speech Commands v0.02, 10 keywords (yes no up down left right on off stop go). A small CNN on log-mel features
(~30k parameters, ESP32-S3 sized) is trained on the original 16-bit clips, then the test clips are passed through:
  ref16   - original 16-bit
  nyq8    - ideal 8-bit converter sampling at 16 kS/s directly (no oversampling)
  adc_<c> - post-layout ADC model (voice_model.py: extracted DAC levels + comparator offsets + noise sigma) at 2 MS/s,
            CIC/R25 + FIR/R5 decimation to 16 kS/s, corners NOM / SLOW / FAST
at speech level -6 dBFS peak and -26 dBFS peak (quiet talker / far microphone).
usage: kws_eval.py <speech_commands dir> [--epochs 12] [--ntest 1000] [--threads 2] [--out results/KWS_EVAL.txt]"""
import os, sys, argparse, time
import numpy as np
from scipy.io import wavfile
from scipy import signal
import torch, torch.nn as nn, torch.nn.functional as F

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import voice_model as vm

MIC_NOISE = 10 ** (-66 / 20)   # rms, relative to the ADC half range (-66 dBFS: electret mic + preamp, 16 kHz band)
KW = ["yes", "no", "up", "down", "left", "right", "on", "off", "stop", "go"]
SR = 16000; NMEL = 40; NFFT = 512; HOP = 160; WIN = 400

def load_list(d, name):
    return [l.strip() for l in open(os.path.join(d, name)) if l.split("/")[0] in KW]
def load_wav(d, rel):
    sr, x = wavfile.read(os.path.join(d, rel)); x = x.astype(np.float32) / 32768.0
    return np.pad(x, (0, max(0, SR - len(x))))[:SR]
def mel_fb():
    hz = lambda m: 700 * (10 ** (m / 2595) - 1); mel = lambda f: 2595 * np.log10(1 + f / 700)
    pts = hz(np.linspace(mel(20), mel(7600), NMEL + 2)); bins = np.floor((NFFT + 1) * pts / SR).astype(int)
    fb = np.zeros((NMEL, NFFT // 2 + 1), np.float32)
    for m in range(1, NMEL + 1):
        a, b, c = bins[m - 1], bins[m], bins[m + 1]
        fb[m - 1, a:b] = (np.arange(a, b) - a) / max(b - a, 1); fb[m - 1, b:c] = (c - np.arange(b, c)) / max(c - b, 1)
    return torch.tensor(fb)
FB = mel_fb()
def features(x):                                   # x: (B, 16000) float tensor -> (B, 1, NMEL, frames)
    S = torch.stft(x, NFFT, HOP, WIN, window=torch.hann_window(WIN), return_complex=True).abs() ** 2
    M = torch.log(torch.matmul(FB, S) + 1e-4)          # floor ~ -40 dB below a full-scale frame energy
    return ((M - M.mean(dim=(1, 2), keepdim=True)) / (M.std(dim=(1, 2), keepdim=True) + 1e-5)).unsqueeze(1)

class KWSNet(nn.Module):
    def __init__(s, n=len(KW)):
        super().__init__()
        s.c1 = nn.Conv2d(1, 24, 3, padding=1); s.b1 = nn.BatchNorm2d(24)
        s.c2 = nn.Conv2d(24, 32, 3, padding=1); s.b2 = nn.BatchNorm2d(32)
        s.c3 = nn.Conv2d(32, 48, 3, padding=1); s.b3 = nn.BatchNorm2d(48)
        s.fc = nn.Linear(48, n); s.dp = nn.Dropout(0.2)
    def forward(s, x):
        x = F.max_pool2d(F.relu(s.b1(s.c1(x))), 2); x = F.max_pool2d(F.relu(s.b2(s.c2(x))), 2)
        x = F.relu(s.b3(s.c3(x))); x = x.mean(dim=(2, 3))
        return s.fc(s.dp(x))

def through_adc(x16, kind, level_dbfs, corner="NOM", sigma=0.35, rng=None):
    """clip at 16 kS/s (+-1 full scale) -> scaled to the ADC input range -> converter -> back to +-1 at 16 kS/s"""
    pk = np.max(np.abs(x16)) + 1e-9
    xs = x16 / pk * 10 ** (level_dbfs / 20)                       # peak at level_dbfs of the ADC half range
    xs = xs + MIC_NOISE * rng.standard_normal(len(xs))            # microphone + preamp noise floor (same for all)
    if kind == "ref16": return xs
    if kind == "nyq8":                                             # ideal 8-bit at 16 kS/s, input range 0..256 LSB
        c = np.clip(np.floor(128 + 128 * xs), 0, 255); return (c + 0.5 - 128) / 128
    T, *_ = LEV[corner]
    xu = signal.resample_poly(xs, 125, 1)                          # analog input seen at 2 MS/s
    c = vm.convert(128.0 + 128.0 * xu, T, sigma, rng)
    y = vm.fir(vm.decimate(c), HFIR)
    y = np.roll(y, -DELAY)[:len(x16)]
    return (y + 0.5 - 128) / 128

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("data"); ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--ntest", type=int, default=1000); ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "KWS_EVAL.txt"))
    a = ap.parse_args(); torch.set_num_threads(a.threads); torch.manual_seed(0); rng = np.random.default_rng(0)
    test = load_list(a.data, "testing_list.txt"); val = set(load_list(a.data, "validation_list.txt")) | set(test)
    train = [f"{k}/{f}" for k in KW for f in sorted(os.listdir(os.path.join(a.data, k))) if f"{k}/{f}" not in val]
    print(f"train {len(train)} clips, test {len(test)}", flush=True)
    Xtr = np.stack([load_wav(a.data, r) for r in train]); Ytr = np.array([KW.index(r.split("/")[0]) for r in train])
    net = KWSNet(); opt = torch.optim.Adam(net.parameters(), 2e-3); sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, a.epochs)
    print(f"model parameters: {sum(p.numel() for p in net.parameters())}", flush=True)
    for ep in range(a.epochs):
        net.train(); perm = rng.permutation(len(Xtr)); tl = 0; t0 = time.time()
        for i in range(0, len(perm), 128):
            idx = perm[i:i + 128]; xb = torch.tensor(Xtr[idx])
            pk = xb.abs().amax(dim=1, keepdim=True) + 1e-9
            xb = xb / pk * torch.empty(len(idx), 1).uniform_(0.05, 0.5) + MIC_NOISE * torch.randn_like(xb)   # level (-26..-6 dBFS peak) + noise floor
            xb = torch.roll(xb, int(rng.integers(-1600, 1600)), dims=1)
            loss = F.cross_entropy(net(features(xb)), torch.tensor(Ytr[idx])); opt.zero_grad(); loss.backward(); opt.step(); tl += loss.item() * len(idx)
        sched.step(); print(f"epoch {ep + 1}: loss {tl / len(perm):.3f} ({time.time() - t0:.0f} s)", flush=True)
    torch.save(net.state_dict(), os.path.join(os.path.dirname(a.out), "kws_cnn.pt"))
    # evaluation
    LEV = {c: vm.adc_levels(c) for c in ("NOM", "SLOW", "FAST")}
    HFIR = vm.decimator(); DELAY = int(round(((len(HFIR) - 1) / 2) / 5 + 2.0 * 25 / 125))    # FIR group delay at 16 kS/s
    sel = [test[i] for i in rng.permutation(len(test))[:a.ntest]]
    Xte = [load_wav(a.data, r) for r in sel]; Yte = np.array([KW.index(r.split("/")[0]) for r in sel])
    net.eval(); lines = [f"KWS accuracy (10 keywords, {len(sel)} test clips, CNN {sum(p.numel() for p in net.parameters())} params, trained on 16-bit clips)",
                         f"{'converter':28s} {'level':>8s} {'accuracy':>9s}"]
    for lvl in (-6.0, -26.0):
        for kind, corner in (("ref16", None), ("nyq8", None), ("adc", "NOM"), ("adc", "SLOW"), ("adc", "FAST")):
            Xc = np.stack([through_adc(x, kind, lvl, corner or "NOM", 0.35, rng) for x in Xte]).astype(np.float32)
            with torch.no_grad():
                pred = net(features(torch.tensor(Xc))).argmax(1).numpy()
            name = {"ref16": "16-bit reference", "nyq8": "ideal 8-bit @16 kS/s"}.get(kind, f"post-layout ADC {corner} (OSR 125)")
            lines.append(f"{name:28s} {lvl:+6.0f}dB {100 * np.mean(pred == Yte):8.1f}%"); print(lines[-1], flush=True)
    open(a.out, "w").write("\n".join(lines) + "\n"); print("\n".join(lines))
