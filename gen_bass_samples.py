#!/usr/bin/env python3
"""ベース音色サンプル比較"""
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

# Am のウォーキングベース: A→C→E→G#
ROOT = 110.0  # A2 (低い方)
NOTES = [110.0, 130.81, 164.81, 103.83]  # A2, C3, E3, Ab2

def make_bass_sample(name, bass_fn):
    bd = 60.0/BPM; total = int(SR*bd*4*BARS); out = np.zeros(total)
    # ジャズドラム（軽く）
    from scipy.signal import lfilter
    def ride(vol=0.12):
        dur=0.2; n=int(SR*dur); t=np.linspace(0,dur,n,endpoint=False)
        s=(0.3*np.sin(2*np.pi*680*t)+0.2*np.sin(2*np.pi*1360*t))*np.exp(-t*12)
        noise=np.random.randn(n)*np.exp(-np.linspace(0,15,n))*0.3
        return vol*(s+noise)
    swing = 2.0/3.0
    for bar in range(BARS):
        off = bar*bd*4*SR
        for beat in range(4):
            bp = off+beat*bd*SR
            mix(out, ride(), bp)
            mix(out, ride(0.08), bp+bd*swing*SR)
            # ベース
            f = NOTES[beat % len(NOTES)]
            bass = bass_fn(f, bd*0.75)
            mix(out, bass, int(bp))
    mx = np.max(np.abs(out))
    if mx > 0: out *= 0.4/max(mx, 0.4)
    return out

# === ベース1: 現在の音（C3帯域, 1オクターブ上） ===
def bass_current(freq, dur):
    f = freq * 2  # 1オクターブ上
    t = np.linspace(0, dur, int(SR*dur), endpoint=False)
    s = 0.12*np.sin(2*np.pi*f*t) + 0.04*np.sin(2*np.pi*f*2*t)
    att=min(int(0.008*SR),len(t)); s[:att]*=np.linspace(0,1,att)
    dec=int(0.1*SR)
    if len(s)>dec: s[-dec:]*=np.linspace(1,0,dec)
    return s

# === ベース2: サブベース（原音域 + サチュレーション） ===
def bass_sub(freq, dur):
    t = np.linspace(0, dur, int(SR*dur), endpoint=False)
    # 基音（低い）+ 倍音で存在感
    s = (0.20*np.sin(2*np.pi*freq*t) +       # 基音
         0.10*np.sin(2*np.pi*freq*2*t) +      # 2倍音
         0.05*np.sin(2*np.pi*freq*3*t) +      # 3倍音
         0.03*np.sin(2*np.pi*freq*4*t))        # 4倍音
    # ソフトサチュレーション（倍音追加で小さいスピーカーでも聞こえやすく）
    s = np.tanh(s * 3) * 0.3
    att=min(int(0.005*SR),len(t)); s[:att]*=np.linspace(0,1,att)
    dec=int(0.08*SR)
    if len(s)>dec: s[-dec:]*=np.linspace(1,0,dec)
    return s

# === ベース3: ファットベース（低域+倍音+コンプレッション風） ===
def bass_fat(freq, dur):
    t = np.linspace(0, dur, int(SR*dur), endpoint=False)
    # 基音 + オクターブ上を混ぜる（小スピーカー対策）
    low = 0.15*np.sin(2*np.pi*freq*t)
    mid = 0.12*np.sin(2*np.pi*freq*2*t)  # オクターブ上
    # パルス波っぽいハーモニクス（ファットな音）
    harm = 0.04*np.sin(2*np.pi*freq*3*t) + 0.03*np.sin(2*np.pi*freq*5*t)
    s = low + mid + harm
    # ソフトクリップ
    s = np.clip(s * 2.5, -0.35, 0.35)
    # アタックにクリック
    click_n = min(int(0.003*SR), len(t))
    s[:click_n] += 0.1*np.random.randn(click_n)*np.exp(-np.linspace(0,20,click_n))
    dec=int(0.1*SR)
    if len(s)>dec: s[-dec:]*=np.linspace(1,0,dec)
    return s

# === ベース4: シンセベース（のこぎり波ベース） ===
def bass_synth(freq, dur):
    t = np.linspace(0, dur, int(SR*dur), endpoint=False)
    # のこぎり波近似（倍音豊富 → 小スピーカーでも存在感）
    s = np.zeros_like(t)
    for h in range(1, 8):
        s += ((-1)**(h+1)) * np.sin(2*np.pi*freq*h*t) / h
    s *= 0.15
    # ローパスっぽくデケイ（高倍音が先に消える感じ）
    env = np.exp(-t*4)
    s *= env
    # サチュレーション
    s = np.tanh(s * 2) * 0.25
    att=min(int(0.003*SR),len(t)); s[:att]*=np.linspace(0,1,att)
    return s

outdir = os.path.expanduser('~/drum_samples')
os.makedirs(outdir, exist_ok=True)

samples = [
    ('bass1_current.wav', bass_current, '現在の音（高め）'),
    ('bass2_sub.wav', bass_sub, 'サブベース（低域+サチュレーション）'),
    ('bass3_fat.wav', bass_fat, 'ファット（低域+オクターブ+クリップ）'),
    ('bass4_synth.wav', bass_synth, 'シンセ（のこぎり波）'),
]

for name, fn, desc in samples:
    path = os.path.join(outdir, name)
    audio = make_bass_sample(name, fn)
    save_wav(audio, path)
    print(f"✅ {name}: {desc}")

print("Done!")
