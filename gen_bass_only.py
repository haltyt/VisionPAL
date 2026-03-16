#!/usr/bin/env python3
"""キック+ベースのみ（中音リズムなし）"""
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

NOTES = [110.0, 130.81, 164.81, 103.83]

def bass_pure(freq, dur):
    t = np.linspace(0, dur, int(SR*dur), endpoint=False)
    s = 0.25 * np.sin(2*np.pi*freq*t)
    att = min(int(0.005*SR), len(t)); s[:att] *= np.linspace(0,1,att)
    dec = int(0.1*SR)
    if len(s)>dec: s[-dec:] *= np.linspace(1,0,dec)
    return s

def soft_kick(vol=0.20):
    dur=0.2; t=np.linspace(0,dur,int(SR*dur),endpoint=False)
    freq=55+65*np.exp(-t*30); phase=2*np.pi*np.cumsum(freq)/SR
    return vol*(np.sin(phase)*np.exp(-t*15)+0.5*np.sin(2*np.pi*50*t)*np.exp(-t*12))

bd = 60.0/BPM; total = int(SR*bd*4*BARS); out = np.zeros(total)

for bar in range(BARS):
    off = bar*bd*4*SR
    for beat in range(4):
        bp = off+beat*bd*SR
        # キックは1,3拍のみ
        if beat in [0, 2]:
            mix(out, soft_kick(), bp)
        # ベース（基音のみ）
        f = NOTES[beat % len(NOTES)]
        mix(out, bass_pure(f, bd*0.75), int(bp))

mx = np.max(np.abs(out))
if mx > 0: out *= 0.4/max(mx, 0.4)

outdir = os.path.expanduser('~/drum_samples')
os.makedirs(outdir, exist_ok=True)
save_wav(out, os.path.join(outdir, 'kick_bass_only.wav'))
print("✅ kick_bass_only.wav")
