#!/usr/bin/env python3
"""ドラムサンプル生成 — 各スタイルのデモWAV"""
import numpy as np, wave, os

SR = 22050
BPM = 110
BARS = 4

def sine(freq, dur, sr=SR, vol=0.3):
    t = np.linspace(0, dur, int(sr*dur), endpoint=False)
    w = vol * np.sin(2*np.pi*freq*t)
    a, r = int(0.01*sr), int(0.05*sr)
    if len(w)>a+r: w[:a]*=np.linspace(0,1,a); w[-r:]*=np.linspace(1,0,r)
    return w

def save_wav(audio, path, sr=SR):
    a16 = np.int16(np.clip(audio, -1, 1)*32767)
    with wave.open(path,'w') as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr); wf.writeframes(a16.tobytes())

def mix(out, src, p):
    p=int(p); e=min(p+len(src),len(out))
    if 0<=p<len(out): out[p:e]+=src[:e-p]

# === ROCK ===
def gen_rock(chord='A', bpm=BPM):
    from scipy.signal import lfilter
    bd=60.0/bpm; total=int(SR*bd*4*BARS); out=np.zeros(total)
    def kick():
        dur=0.2; t=np.linspace(0,dur,int(SR*dur),endpoint=False)
        freq=55+80*np.exp(-t*35); phase=2*np.pi*np.cumsum(freq)/SR
        body=0.3*np.sin(phase)*np.exp(-t*12)
        click=np.zeros_like(t); cn=min(int(SR*0.005),len(t))
        click[:cn]=0.15*np.random.randn(cn)
        return body+click
    def snare():
        dur=0.15; n=int(SR*dur); t=np.linspace(0,dur,n,endpoint=False)
        return 0.15*np.sin(2*np.pi*185*t)*np.exp(-t*20)+0.12*np.random.randn(n)*np.exp(-t*18)+0.06*np.random.randn(n)*np.exp(-np.linspace(3,15,n))
    def hh():
        n=int(SR*0.06); return 0.08*np.random.randn(n)*np.exp(-np.linspace(0,15,n))
    k,s,h=kick(),snare(),hh()
    bf=220.0
    for bar in range(BARS):
        off=int(bar*bd*4*SR)
        for beat in range(4):
            p=off+int(beat*bd*SR)
            if beat in[0,2]: mix(out,k,p)
            if beat in[1,3]: mix(out,s,p)
            for sub in[0,0.5]: mix(out,h,int(p+sub*bd*SR))
            nd=bd*0.8
            f=[bf, bf*1.5, bf, bf*1.25][beat]
            mix(out,sine(f,nd,SR,0.12),p)
    mx=np.max(np.abs(out))
    if mx>0: out*=0.35/max(mx,0.35)
    return out

# === JAZZ ===
def gen_jazz(chord='Am', bpm=BPM):
    from scipy.signal import lfilter
    bd=60.0/bpm; total=int(SR*bd*4*BARS); out=np.zeros(total); swing=2.0/3.0
    def ride(vol=0.20):
        dur=0.25; n=int(SR*dur); t=np.linspace(0,dur,n,endpoint=False)
        s=(0.3*np.sin(2*np.pi*680*t)+0.25*np.sin(2*np.pi*1360*t)+0.15*np.sin(2*np.pi*2800*t)+0.1*np.sin(2*np.pi*4200*t))*np.exp(-t*12)
        noise=np.random.randn(n)*np.exp(-np.linspace(0,15,n))
        noise=lfilter([1,-0.85],[1.0],noise)
        return vol*(s*0.5+noise*0.5)
    def brush(vol=0.12):
        dur=0.18; n=int(SR*dur); t=np.linspace(0,dur,n,endpoint=False)
        noise=lfilter([0.15,0.15,0.15,0.15,0.15,0.1,0.05],[1.0],np.random.randn(n))
        body=0.3*np.sin(2*np.pi*180*t)*np.exp(-t*25)
        wire=0.2*np.random.randn(n)*np.exp(-np.linspace(5,20,n))
        return vol*(noise*0.5+body+wire)*np.exp(-t*12)
    def skick(vol=0.25):
        dur=0.2; t=np.linspace(0,dur,int(SR*dur),endpoint=False)
        freq=55+65*np.exp(-t*30); phase=2*np.pi*np.cumsum(freq)/SR
        return vol*(np.sin(phase)*np.exp(-t*15)+0.5*np.sin(2*np.pi*50*t)*np.exp(-t*12))
    bf=220.0
    for bar in range(BARS):
        off=bar*bd*4*SR
        for beat in range(4):
            bp=off+beat*bd*SR; sp=bp+bd*swing*SR
            mix(out,ride(),bp); mix(out,ride(0.14),sp)
            if beat in[1,3]: mix(out,brush(),bp)
            if beat==0: mix(out,skick(),bp)
            elif beat==2 and bar%2==0: mix(out,skick(0.18),bp)
        for beat in range(4):
            bp=off+beat*bd*SR; nd=bd*0.75
            f=[bf, bf*1.189, bf*1.498, bf*0.944][beat]
            t=np.linspace(0,nd,int(SR*nd),endpoint=False)
            bass=0.12*np.sin(2*np.pi*f*t)+0.04*np.sin(2*np.pi*f*2*t)
            att=min(int(0.008*SR),len(t)); bass[:att]*=np.linspace(0,1,att)
            dec=int(0.1*SR)
            if len(bass)>dec: bass[-dec:]*=np.linspace(1,0,dec)
            mix(out,bass,int(bp))
    mx=np.max(np.abs(out))
    if mx>0: out*=0.35/max(mx,0.35)
    return out

# === BOSSA NOVA ===
def gen_bossa(chord='Am', bpm=100):
    from scipy.signal import lfilter
    bd=60.0/bpm; total=int(SR*bd*4*BARS); out=np.zeros(total)
    def rimshot(vol=0.15):
        dur=0.04; n=int(SR*dur); t=np.linspace(0,dur,n,endpoint=False)
        return vol*(0.5*np.sin(2*np.pi*800*t)+0.5*np.random.randn(n)*0.3)*np.exp(-t*40)
    def shaker(vol=0.06):
        dur=0.08; n=int(SR*dur)
        noise=np.random.randn(n)*np.exp(-np.linspace(0,20,n))
        return vol*lfilter([1,-0.6],[1.0],noise)
    def skick(vol=0.20):
        dur=0.15; t=np.linspace(0,dur,int(SR*dur),endpoint=False)
        freq=50+60*np.exp(-t*30); phase=2*np.pi*np.cumsum(freq)/SR
        return vol*np.sin(phase)*np.exp(-t*12)
    bf=220.0
    # ボサノバパターン: 1-and-2-and-3-and-4-and → リムショットは特定位置
    rim_pattern = [0, 0.5, 1.5, 2, 3, 3.5]  # 拍単位
    kick_pattern = [0, 2]
    for bar in range(BARS):
        off=bar*bd*4*SR
        # リムショット
        for pos in rim_pattern:
            mix(out, rimshot(), off+pos*bd*SR)
        # キック
        for pos in kick_pattern:
            mix(out, skick(), off+pos*bd*SR)
        # シェイカー（8分音符）
        for i in range(8):
            mix(out, shaker(), off+i*0.5*bd*SR)
        # ベース（ボサノバ風）
        bass_pattern = [(0, bf), (1.5, bf*1.189), (2, bf*1.498), (3.5, bf*1.26)]
        for pos, f in bass_pattern:
            nd=bd*0.6
            t=np.linspace(0,nd,int(SR*nd),endpoint=False)
            bass=0.10*np.sin(2*np.pi*f*t)+0.03*np.sin(2*np.pi*f*2*t)
            dec=int(0.08*SR)
            if len(bass)>dec: bass[-dec:]*=np.linspace(1,0,dec)
            mix(out,bass,int(off+pos*bd*SR))
    mx=np.max(np.abs(out))
    if mx>0: out*=0.35/max(mx,0.35)
    return out

# === BALLAD ===
def gen_ballad(chord='C', bpm=75):
    bd=60.0/bpm; total=int(SR*bd*4*BARS); out=np.zeros(total)
    def soft_kick(vol=0.18):
        dur=0.2; t=np.linspace(0,dur,int(SR*dur),endpoint=False)
        freq=50+50*np.exp(-t*25); phase=2*np.pi*np.cumsum(freq)/SR
        return vol*np.sin(phase)*np.exp(-t*10)
    def soft_hh(vol=0.05):
        dur=0.1; n=int(SR*dur)
        return vol*np.random.randn(n)*np.exp(-np.linspace(0,12,n))
    def soft_snare(vol=0.08):
        dur=0.12; n=int(SR*dur); t=np.linspace(0,dur,n,endpoint=False)
        return vol*(0.4*np.sin(2*np.pi*170*t)*np.exp(-t*18)+0.6*np.random.randn(n)*np.exp(-t*15)*0.3)
    bf=130.81
    for bar in range(BARS):
        off=bar*bd*4*SR
        for beat in range(4):
            bp=off+beat*bd*SR
            if beat==0: mix(out,soft_kick(),bp)
            if beat==2: mix(out,soft_snare(),bp)
            mix(out,soft_hh(),bp)
            # ハーフタイムでハイハット裏拍
            if beat in[0,2]: mix(out,soft_hh(0.03),bp+0.5*bd*SR)
        # パッド風ベース（ロングノート）
        for beat in [0, 2]:
            bp=off+beat*bd*SR; nd=bd*1.8
            f=bf if beat==0 else bf*1.498
            t=np.linspace(0,nd,int(SR*nd),endpoint=False)
            bass=0.08*np.sin(2*np.pi*f*t)
            att=int(0.05*SR); bass[:att]*=np.linspace(0,1,att)
            dec=int(0.2*SR)
            if len(bass)>dec: bass[-dec:]*=np.linspace(1,0,dec)
            mix(out,bass,int(bp))
    mx=np.max(np.abs(out))
    if mx>0: out*=0.35/max(mx,0.35)
    return out

# 生成
outdir = os.path.expanduser('~/drum_samples')
os.makedirs(outdir, exist_ok=True)

samples = [
    ('rock_A_110bpm.wav', gen_rock),
    ('jazz_Am_110bpm.wav', gen_jazz),
    ('bossa_Am_100bpm.wav', gen_bossa),
    ('ballad_C_75bpm.wav', gen_ballad),
]

for name, fn in samples:
    path = os.path.join(outdir, name)
    audio = fn()
    save_wav(audio, path)
    print(f"✅ {name} ({len(audio)/SR:.1f}s)")

print("Done!")
