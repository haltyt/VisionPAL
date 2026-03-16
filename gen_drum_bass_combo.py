#!/usr/bin/env python3
"""低音ベース固定 + ドラムパターン比較"""
import numpy as np, wave, os
from scipy.signal import lfilter

SR = 22050
BPM = 110
BARS = 4

def save_wav(audio, path, sr=SR):
    a16 = np.int16(np.clip(audio, -1, 1)*32767)
    with wave.open(path,'w') as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr); wf.writeframes(a16.tobytes())

def mix(out, src, p):
    p=int(p); e=min(p+len(src),len(out))
    if 0<=p<len(out): out[p:e]+=src[:e-p]

NOTES = [110.0, 130.81, 164.81, 103.83]

# === 共通ベース（基音のみ） ===
def bass_pure(freq, dur):
    t = np.linspace(0, dur, int(SR*dur), endpoint=False)
    s = 0.25 * np.sin(2*np.pi*freq*t)
    att = min(int(0.005*SR), len(t)); s[:att] *= np.linspace(0,1,att)
    dec = int(0.1*SR)
    if len(s)>dec: s[-dec:] *= np.linspace(1,0,dec)
    return s

# === ドラム音色 ===
def kick(vol=0.22):
    dur=0.2; t=np.linspace(0,dur,int(SR*dur),endpoint=False)
    freq=55+70*np.exp(-t*30); phase=2*np.pi*np.cumsum(freq)/SR
    body=np.sin(phase)*np.exp(-t*13)
    sub=0.4*np.sin(2*np.pi*50*t)*np.exp(-t*10)
    return vol*(body+sub)

def snare(vol=0.14):
    dur=0.15; n=int(SR*dur); t=np.linspace(0,dur,n,endpoint=False)
    body=0.4*np.sin(2*np.pi*185*t)*np.exp(-t*20)
    noise=0.5*np.random.randn(n)*np.exp(-t*18)
    wire=0.2*np.random.randn(n)*np.exp(-np.linspace(3,15,n))
    return vol*(body+noise+wire)

def hh_closed(vol=0.07):
    n=int(SR*0.05); return vol*np.random.randn(n)*np.exp(-np.linspace(0,18,n))

def hh_open(vol=0.06):
    n=int(SR*0.12); return vol*np.random.randn(n)*np.exp(-np.linspace(0,8,n))

def ride(vol=0.10):
    dur=0.2; n=int(SR*dur); t=np.linspace(0,dur,n,endpoint=False)
    s=(0.3*np.sin(2*np.pi*680*t)+0.2*np.sin(2*np.pi*1360*t)+0.1*np.sin(2*np.pi*2800*t))*np.exp(-t*12)
    noise=np.random.randn(n)*np.exp(-np.linspace(0,15,n))*0.2
    return vol*(s+noise)

def brush(vol=0.10):
    dur=0.15; n=int(SR*dur); t=np.linspace(0,dur,n,endpoint=False)
    noise=lfilter([0.15,0.15,0.15,0.15,0.15],[1.0],np.random.randn(n))
    body=0.3*np.sin(2*np.pi*180*t)*np.exp(-t*25)
    return vol*(noise*0.5+body)*np.exp(-t*12)

def rimshot(vol=0.12):
    dur=0.04; n=int(SR*dur); t=np.linspace(0,dur,n,endpoint=False)
    return vol*(0.5*np.sin(2*np.pi*800*t)+0.3*np.random.randn(n)*0.3)*np.exp(-t*40)

def shaker(vol=0.05):
    dur=0.07; n=int(SR*dur)
    return vol*lfilter([1,-0.6],[1.0],np.random.randn(n)*np.exp(-np.linspace(0,18,n)))

def gen(name, drum_fn):
    bd=60.0/BPM; total=int(SR*bd*4*BARS); out=np.zeros(total)
    for bar in range(BARS):
        off=bar*bd*4*SR
        for beat in range(4):
            bp=off+beat*bd*SR
            f=NOTES[beat%len(NOTES)]
            mix(out, bass_pure(f, bd*0.75), int(bp))
        drum_fn(out, off, bd, bar)
    mx=np.max(np.abs(out))
    if mx>0: out*=0.4/max(mx,0.4)
    return out

# === 1. ロック: キック(1,3)+スネア(2,4)+HH8分 ===
def drums_rock(out, off, bd, bar):
    for beat in range(4):
        bp=off+beat*bd*SR
        if beat in[0,2]: mix(out,kick(),bp)
        if beat in[1,3]: mix(out,snare(),bp)
        mix(out,hh_closed(),bp)
        mix(out,hh_closed(0.04),bp+0.5*bd*SR)

# === 2. ジャズスウィング: ライド+ブラシ(2,4)+キック控えめ ===
def drums_jazz(out, off, bd, bar):
    sw=2.0/3.0
    for beat in range(4):
        bp=off+beat*bd*SR
        mix(out,ride(),bp)
        mix(out,ride(0.06),bp+bd*sw*SR)
        if beat in[1,3]: mix(out,brush(),bp)
        if beat==0: mix(out,kick(0.15),bp)
        elif beat==2 and bar%2==0: mix(out,kick(0.12),bp)

# === 3. ボサノバ: リムショット+シェイカー ===
def drums_bossa(out, off, bd, bar):
    rim_pos=[0,0.5,1.5,2,3,3.5]
    for pos in rim_pos:
        mix(out,rimshot(),off+pos*bd*SR)
    for beat in[0,2]:
        mix(out,kick(0.15),off+beat*bd*SR)
    for i in range(8):
        mix(out,shaker(),off+i*0.5*bd*SR)

# === 4. バラード: キック(1)+スネア(3)+HH控えめ ===
def drums_ballad(out, off, bd, bar):
    for beat in range(4):
        bp=off+beat*bd*SR
        if beat==0: mix(out,kick(0.18),bp)
        if beat==2: mix(out,snare(0.08),bp)
        mix(out,hh_closed(0.04),bp)

outdir=os.path.expanduser('~/drum_samples')
os.makedirs(outdir,exist_ok=True)

for name,fn,desc in [
    ('combo_rock.wav', drums_rock, 'ロック'),
    ('combo_jazz.wav', drums_jazz, 'ジャズスウィング'),
    ('combo_bossa.wav', drums_bossa, 'ボサノバ'),
    ('combo_ballad.wav', drums_ballad, 'バラード'),
]:
    audio=gen(name,fn)
    save_wav(audio, os.path.join(outdir,name))
    print(f"✅ {name}: {desc}")
print("Done!")
