#!/usr/bin/env python3
"""Swar live demo: speak a keyword, see it recognised through three converters side by side.

  16-bit reference microphone  |  plain 8-bit ADC at 16 kS/s  |  Swar: post-layout ADC model at 2 MS/s + CIC/FIR

The browser records the microphone and posts raw audio here; this server runs exactly the same ADC, decimation
and CNN code as model/kws_eval.py (the numbers in results/KWS_EVAL.txt), so the demo and the report agree.

usage: python3 demo/live_demo.py [--port 8765] [--host 127.0.0.1] [--corner NOM]
then open http://localhost:8765 in Chrome or Edge.

With the Basys3 prototype (fpga/proto) the audio can come from the board instead of the laptop microphone:
  python3 demo/live_demo.py --bridge 8791      and, in Windows PowerShell:  demo\board_bridge.ps1 -Port COM5
  python3 demo/live_demo.py --serial COM5      (when Python itself can open the port)
"""
import argparse
import base64
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import numpy as np
import torch
from scipy import signal

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "model"))
import kws_eval as ke          # noqa: E402  (features, KWSNet, through_adc, KW)
import voice_model as vm       # noqa: E402

SR = ke.SR
PAD = 800
SWEEP_LEVELS = [-6, -12, -18, -24, -30, -36]
PATHS = [("ref16", "16-bit reference"), ("nyq8", "Plain 8-bit ADC"), ("adc", "Swar")]

# the globals kws_eval.through_adc expects (it sets them in its own __main__)
ke.LEV = {c: vm.adc_levels(c) for c in ("NOM", "SLOW", "FAST")}
ke.HFIR = vm.decimator()
ke.DELAY = int(round(((len(ke.HFIR) - 1) / 2) / 5 + 2.0 * 25 / 125))

torch.set_num_threads(2)
NET = ke.KWSNet()
NET.load_state_dict(torch.load(os.path.join(ROOT, "model", "kws_cnn.pt"), map_location="cpu"))
NET.eval()
LOCK = threading.Lock()


def best_second(x):
    """The 1 s window of the recording that holds the most energy (where the word is)."""
    if len(x) <= SR:
        return np.pad(x, (0, SR - len(x)))
    e = np.concatenate([[0.0], np.cumsum(x.astype(np.float64) ** 2)])
    starts = np.arange(0, len(x) - SR + 1, 160)
    s = starts[np.argmax(e[starts + SR] - e[starts])]
    return x[s:s + SR]


def classify(clips):
    """clips: (B, 16000) float32 -> (probabilities (B, 10), normalised log-mel (B, 40, T))"""
    with torch.no_grad():
        f = ke.features(torch.tensor(np.asarray(clips, dtype=np.float32)))
        p = torch.softmax(NET(f), dim=1).numpy()
    return p, f[:, 0].numpy()


def b64(a):
    return base64.b64encode(a.tobytes()).decode()


def cards(clips, probs, mels, ti):
    out = []
    for j, (key, name) in enumerate(PATHS):
        p, clip = probs[j], clips[j]
        mel = np.clip((mels[j] + 2.0) / 5.0, 0, 1)
        audio = clip / (np.max(np.abs(clip)) + 1e-9) * 0.9          # level-matched for listening
        top = int(np.argmax(p))
        out.append({
            "key": key, "name": name, "label": ke.KW[top], "conf": float(p[top]), "ok": bool(top == ti),
            "probs": [float(v) for v in p],
            "mel": b64((mel * 255).astype(np.uint8)), "melT": int(mel.shape[1]),
            "audio": b64((audio * 32767).astype("<i2")),
        })
    return out


def run(x, level, corner, target, sweep_on=True):
    t0 = time.time()
    x = best_second(x - np.mean(x))
    if np.max(np.abs(x)) < 1e-4:
        return {"error": "The recording is silent. Check that the browser is using the right microphone."}
    levels = [level] + ([l for l in SWEEP_LEVELS if l != level] if sweep_on else [])
    clips = []
    for lv in levels:
        for kind, _ in PATHS:
            rng = np.random.default_rng(0)     # same microphone noise for the three converters
            # 50 ms of silence on both sides: the decimation filter's start-up step (and the part np.roll wraps
            # round in through_adc) lands in the padding instead of the clip
            clips.append(ke.through_adc(np.pad(x, PAD), kind, float(lv), corner, 0.35, rng)[PAD:-PAD])
    clips = np.stack(clips).astype(np.float32)
    probs, mels = classify(clips)
    n = len(PATHS)
    if target not in ke.KW:                    # no word chosen: trust the 16-bit reference
        target = ke.KW[int(np.argmax(probs[0]))]
    ti = ke.KW.index(target)

    paths = cards(clips[:n], probs[:n], mels[:n], ti)
    sweep = []
    for j, (key, name) in enumerate(PATHS if sweep_on else []):
        cells = []
        for lv in SWEEP_LEVELS:
            p = probs[levels.index(lv) * n + j]
            top = int(np.argmax(p))
            cells.append({"label": ke.KW[top], "conf": float(p[top]), "ok": bool(top == ti)})
        sweep.append({"key": key, "name": name, "cells": cells})
    return {"level": level, "corner": corner, "target": target, "words": ke.KW, "paths": paths,
            "sweep": {"levels": SWEEP_LEVELS, "rows": sweep}, "ms": int(1000 * (time.time() - t0))}


class Board:
    """The Basys3 prototype (fpga/proto): two 16 kS/s streams over its USB-UART, reference and Swar.
    Bytes arrive either from a serial port (pyserial) or from demo/board_bridge.ps1 over TCP (Windows -> WSL)."""
    FS = 100e6 / 104 / 60                      # 16025.6 S/s, treated as 16 kS/s (0.16 % fast)

    def __init__(self, serial_port="", bridge_port=0, baud=921600):
        self.serial_port, self.bridge_port, self.baud = serial_port, bridge_port, baud
        self.lock = threading.Lock()
        self.ref, self.swar = np.zeros(0), np.zeros(0)
        self.total, self.last_rx, self.tx = 0, 0.0, None
        self.srv = None
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                if self.serial_port:
                    import serial
                    with serial.Serial(self.serial_port, self.baud, timeout=0.05) as sp:
                        self.tx = sp.write
                        self._pump(lambda: sp.read(sp.in_waiting or 1))
                else:
                    import socket
                    if self.srv is None:                        # the listener stays open: the bridge may reconnect
                        self.srv = socket.socket()
                        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        self.srv.bind(("0.0.0.0", self.bridge_port))
                        self.srv.listen(2)
                    conn, addr = self.srv.accept()
                    print(f"board: bridge connected from {addr[0]}", flush=True)
                    conn.settimeout(3.0)                        # 3 s without data: drop it and wait for a new one
                    self.tx = conn.sendall
                    try:
                        self._pump(lambda: conn.recv(65536) or (_ for _ in ()).throw(ConnectionError("bridge closed")))
                    finally:
                        conn.close()
            except Exception as e:
                print(f"board: {type(e).__name__}: {e}; retrying", flush=True)
            self.tx = None
            time.sleep(0.2)

    def _pump(self, read):
        left = b""
        while True:
            chunk = read()
            if not chunk:
                continue
            by = np.frombuffer(left + chunk, dtype=np.uint8)
            sync = np.flatnonzero(by >= 128)
            if len(sync) == 0:
                left = b""
                continue
            by = by[sync[0]:]
            n = len(by) // 4
            left = by[4 * n:].tobytes()
            fr = by[:4 * n].reshape(-1, 4).astype(np.int32)
            fr = fr[(fr[:, 0] >= 128) & np.all(fr[:, 1:] < 128, axis=1)]      # drop frames that lost sync
            if len(fr) == 0:
                continue
            dec = lambda hi, lo: (((hi & 0x7F) << 7 | lo) ^ 0x2000) - 0x2000   # 14-bit two's complement
            with self.lock:
                self.ref = np.concatenate([self.ref, dec(fr[:, 0], fr[:, 1])])[-8 * SR:]
                self.swar = np.concatenate([self.swar, dec(fr[:, 2], fr[:, 3])])[-8 * SR:]
                self.total += len(fr)
                self.last_rx = time.time()

    def status(self):
        with self.lock:
            live = time.time() - self.last_rx < 0.5
            tail = self.ref[-SR // 4:]
            pk = float(np.max(np.abs(tail - tail.mean()))) / 4096 if live and len(tail) else 0.0
        return {"enabled": True, "connected": live, "level_db": round(20 * np.log10(pk + 1e-6), 1),
                "how": self.serial_port or f"bridge on port {self.bridge_port}"}

    def record(self, seconds):
        need = int(seconds * SR)
        with self.lock:
            start = self.total
        t0 = time.time()
        while time.time() - t0 < seconds + 2.0:
            with self.lock:
                got = self.total - start
                if got >= need:
                    k = got - need
                    end = len(self.ref) - k
                    return self.ref[end - need:end].copy(), self.swar[end - need:end].copy()
            time.sleep(0.02)
        raise RuntimeError("no audio from the board: check the USB cable, the COM port and that the design is loaded")

    def send(self, b):
        if self.tx:
            try:
                self.tx(bytes([b]))
            except Exception:
                pass


def run_board(target):
    """Record from the Basys3. Reference and Swar come from the hardware; the plain 8-bit path is the reference
    quantised to 8 bits at 16 kS/s (what an 8-bit converter without oversampling would give)."""
    t0 = time.time()
    ref, swar = BOARD.record(1.6)
    ref, swar = (ref - ref.mean()) / 4096.0, (swar - swar.mean()) / 4096.0      # +-1 = ADC full scale
    e = np.concatenate([[0.0], np.cumsum(ref ** 2)])
    st = np.arange(0, len(ref) - SR + 1, 160)
    s0 = int(st[np.argmax(e[st + SR] - e[st])])
    ref, swar = ref[s0:s0 + SR], swar[s0:s0 + SR]
    nyq8 = (np.clip(np.floor(128 + 128 * ref), 0, 255) + 0.5 - 128) / 128
    clips = np.stack([ref, nyq8, swar]).astype(np.float32)
    probs, mels = classify(clips)
    if target not in ke.KW:
        target = ke.KW[int(np.argmax(probs[0]))]
    out = cards(clips, probs, mels, ke.KW.index(target))
    BOARD.send(ord("0") + ke.KW.index(out[2]["label"]))           # the Swar result lights the board LED
    pk = float(np.max(np.abs(ref)))
    return {"level": int(round(20 * np.log10(pk + 1e-6))), "target": target, "words": ke.KW, "paths": out,
            "sweep": {"levels": [], "rows": []}, "source": "board", "ms": int(1000 * (time.time() - t0))}


BOARD = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlparse(self.path).path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif urlparse(self.path).path == "/api/board/raw" and BOARD:      # raw samples, for measurements
            try:
                ref, swar = BOARD.record(float(parse_qs(urlparse(self.path).query).get("sec", ["2"])[0]))
                out = {"fs": Board.FS, "ref": ref.astype(int).tolist(), "swar": swar.astype(int).tolist()}
            except Exception as e:
                out = {"error": f"{type(e).__name__}: {e}"}
            self._send(200, json.dumps(out).encode(), "application/json")
        elif urlparse(self.path).path == "/api/board":
            st = BOARD.status() if BOARD else {"enabled": False}
            self._send(200, json.dumps(st).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/api/board/record" and BOARD:
            try:
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                out = run_board(parse_qs(u.query).get("target", [""])[0])
            except Exception as e:
                out = {"error": f"{type(e).__name__}: {e}"}
            return self._send(200, json.dumps(out).encode(), "application/json")
        if u.path != "/api/classify":
            return self._send(404, b"not found", "text/plain")
        try:
            q = parse_qs(u.query)
            n = int(self.headers.get("Content-Length", "0"))
            if not 0 < n <= 4 * 48000 * 6:
                raise ValueError("recording is empty or too long")
            x = np.frombuffer(self.rfile.read(n), dtype="<f4").astype(np.float64)
            sr = int(float(q.get("sr", [SR])[0]))
            if sr != SR:
                x = signal.resample_poly(x, SR, sr)
            level = max(-40, min(-3, int(float(q.get("level", ["-6"])[0]))))
            corner = q.get("corner", [ARGS.corner])[0]
            corner = corner if corner in ke.LEV else "NOM"
            with LOCK:
                out = run(x, level, corner, q.get("target", [""])[0], q.get("sweep", ["1"])[0] != "0")
        except Exception as e:                                    # report to the page instead of a dead request
            out = {"error": f"{type(e).__name__}: {e}"}
        self._send(200, json.dumps(out).encode(), "application/json")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--corner", default="NOM", choices=["NOM", "SLOW", "FAST"])
    ap.add_argument("--serial", default="", help="Basys3 serial port (COM5, /dev/ttyUSB1); needs pyserial")
    ap.add_argument("--bridge", type=int, default=0, metavar="PORT",
                    help="wait for demo/board_bridge.ps1 on this TCP port (Basys3 on Windows, server in WSL)")
    ARGS = ap.parse_args()
    if ARGS.serial or ARGS.bridge:
        BOARD = Board(ARGS.serial, ARGS.bridge)
    srv = ThreadingHTTPServer((ARGS.host, ARGS.port), Handler)
    print(f"Swar live demo: open http://localhost:{ARGS.port} in Chrome or Edge  (Ctrl+C to stop)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
