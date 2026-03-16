#!/usr/bin/env python3
"""純粋な低音ベース — 基音のみ、倍音なし"""
import numpy as np, wave, os

SR = 22050
BPM = 110
BARS = 2

def save_wav(audio, path, sr=SR):
    a16 = np.int16(np.clip(audio, -1, 1)*32767)
    with wave.open(path,'w') as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr); wf.writeframes(a16.tobytes())

def mix(out, src, p):
    p=int(p); e=min(p+len(src),len(out))
    if 0<=p<len(out): out[p:e]+=src[:e-p]

# ウォーキングベース: A→C→E→Ab
NOTES = [110.0, 130.81, 164.81, 103.83]

def bass_pure(freq, dur):
    """基音のみのシンプルベース"""
    t = np.linspace(0, dur, int(SR*dur), endpoint=False)
    s = 0.25 * np.sin(2*np.pi*freq*t)
    att = min(int(0.005*SR), len(t)); s[:att] *= np.linspace(0,1,att)
    dec = int(0.1*SR)
    if len(s)>dec: s[-dec:] *= np.linspace(1,0,dec)
    return s

# ジャズドラム+ベース
from scipy.signal import lfilter
bd = 60.0/BPM; total = int(SR*bd*4*BARS); out = np.zeros(total)
swing = 2.0/3.0

def ride(vol=0.12):
    dur=0.2; n=int(SR*dur); t=np.linspace(0,dur,n,endpoint=False)
    s=(0.3*np.sin(2*np.pi*680*t)+0.2*np.sin(2*np.pi*1360*t))*np.exp(-t*12)
    noise=np.random.randn(n)*np.exp(-np.linspace(0,15,n))*0.3
    return vol*(s+noise)

for bar in range(BARS):
    off = bar*bd*4*SR
    for beat in range(4):
        bp = off+beat*bd*SR
        mix(out, ride(), bp)
        mix(out, ride(0.08), bp+bd*swing*SR)
        f = NOTES[beat % len(NOTES)]
        mix(out, bass_pure(f, bd*0.75), int(bp))

mx = np.max(np.abs(out))
if mx > 0: out *= 0.4/max(mx, 0.4)

outdir = os.path.expanduser('~/drum_samples')
os.makedirs(outdir, exist_ok=True)
path = os.path.join(outdir, 'bass_pure_low.wav')
save_wav(out, path)
print(f"✅ bass_pure_low.wav (基音のみ A2=110Hz)")
