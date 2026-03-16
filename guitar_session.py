#!/usr/bin/env python3
# /// script
# requires-python = ">=3.6,<3.13"
# dependencies = [
#     "numpy",
#     "librosa>=0.10.2",
#     "scipy",
#     "numba>=0.59",
#     "llvmlite>=0.42",
#     "soundfile",
# ]
# ///
"""
🎸 ギターセッション・パル v5
- コード検出 + BPM自動検出 + スタイル自動推定
- 4パターン: rock / jazz / bossa / ballad
- ベース: 基音のみ（低音）
"""

import subprocess, sys, os, time, tempfile, wave, signal, threading, atexit, fcntl
import builtins
_original_print = builtins.print
def print(*args, **kwargs):
    kwargs.setdefault('flush', True)
    _original_print(*args, **kwargs)
import numpy as np

SPEAKER = "pulse"  # PulseAudio経由（BT/USB自動）
PULSE_MIC = "alsa_input.usb-C-Media_Electronics_Inc._USB_PnP_Sound_Device-00.analog-mono"
SR = 22050
DEFAULT_BPM = 100
BARS = 4
CHUNK = 1.5
TEMPO_BUF_SEC = 8
MIN_BPM = 60
MAX_BPM = 180
STYLES = ['rock', 'jazz', 'bossa', 'ballad']

running = True
def sig(s, f):
    global running; running = False
    print("\n🛑 終了！"); sys.exit(0)
signal.signal(signal.SIGINT, sig)
signal.signal(signal.SIGTERM, sig)
signal.signal(signal.SIGHUP, signal.SIG_IGN)

CHORDS = {
    'C': [1,0,0,0,1,0,0,1,0,0,0,0], 'Cm': [1,0,0,1,0,0,0,1,0,0,0,0],
    'D': [0,0,1,0,0,0,1,0,0,1,0,0], 'Dm': [0,0,1,0,0,1,0,0,0,1,0,0],
    'E': [0,0,0,0,1,0,0,0,1,0,0,1], 'Em': [0,0,0,0,1,0,0,1,0,0,0,1],
    'F': [1,0,0,0,0,1,0,0,0,1,0,0], 'Fm': [1,0,0,0,0,1,0,0,1,0,0,0],
    'G': [0,0,1,0,0,0,0,1,0,0,0,1], 'Gm': [0,0,1,0,0,0,0,1,0,0,1,0],
    'A': [0,0,0,0,1,0,0,0,0,1,0,1], 'Am': [1,0,0,0,0,0,0,0,0,1,0,0],
    'B': [0,0,0,0,0,0,1,0,0,0,0,1], 'Bm': [0,0,1,0,0,0,1,0,0,0,0,1],
}
# ベース用周波数（低め: C2-B2帯域, 65-123Hz）
FREQS_LOW = {'C':65.41,'D':73.42,'E':82.41,'F':87.31,'G':98.00,'A':110.00,'B':123.47}

noise_chroma = None
_all_players = []

# ============================================================
# LoopPlayer
# ============================================================
class LoopPlayer:
    def __init__(self, wav_path, device):
        self.wav_path = wav_path
        self.device = device
        self._stop = threading.Event()
        self._proc = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                self._proc = subprocess.Popen(
                    ['aplay', '-D', self.device, self.wav_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                self._proc.wait()
            except Exception:
                break
        self._proc = None

    def stop(self):
        self._stop.set()
        p = self._proc
        if p:
            try: p.kill()
            except: pass
            try: p.wait(timeout=2)
            except: pass
        self._thread.join(timeout=3)

    @property
    def is_playing(self):
        return self._thread.is_alive() and not self._stop.is_set()

def kill_all_players():
    for p in _all_players:
        try: p.stop()
        except: pass
    subprocess.run(['killall', '-9', 'aplay'], capture_output=True)

atexit.register(kill_all_players)

# ============================================================
# TempoTracker + StyleDetector
# ============================================================
class TempoTracker:
    def __init__(self, sr, buf_sec, min_bpm, max_bpm):
        self.sr = sr
        self.max_samples = int(sr * buf_sec)
        self.min_bpm = min_bpm
        self.max_bpm = max_bpm
        self.buffer = np.array([], dtype=np.float32)
        self.current_bpm = DEFAULT_BPM
        self._update_count = 0

    def add(self, audio):
        self.buffer = np.concatenate([self.buffer, audio])
        if len(self.buffer) > self.max_samples:
            self.buffer = self.buffer[-self.max_samples:]

    def estimate(self):
        import librosa
        if len(self.buffer) < self.sr * 4:
            return self.current_bpm
        self._update_count += 1
        if self._update_count % 3 != 0:
            return self.current_bpm
        try:
            onset_env = librosa.onset.onset_strength(y=self.buffer, sr=self.sr)
            tempo = librosa.feature.tempo(onset_envelope=onset_env, sr=self.sr, start_bpm=self.current_bpm)
            new_bpm = float(tempo[0]) if hasattr(tempo, '__len__') else float(tempo)
            new_bpm = max(self.min_bpm, min(self.max_bpm, new_bpm))
            smoothed = self.current_bpm * 0.6 + new_bpm * 0.4
            if abs(smoothed - self.current_bpm) >= 5:
                old = self.current_bpm
                self.current_bpm = round(smoothed)
                print(f"🥁 BPM: {old} → {self.current_bpm}")
        except Exception as e:
            print(f"⚠️ テンポ推定エラー: {e}")
        return self.current_bpm

    def reset(self):
        self.buffer = np.array([], dtype=np.float32)


class StyleDetector:
    """ギターの弾き方からスタイルを推定"""
    def __init__(self, sr):
        self.sr = sr
        self.buffer = np.array([], dtype=np.float32)
        self.max_samples = int(sr * 10)
        self.current_style = 'rock'
        self._count = 0

    def add(self, audio):
        self.buffer = np.concatenate([self.buffer, audio])
        if len(self.buffer) > self.max_samples:
            self.buffer = self.buffer[-self.max_samples:]

    def estimate(self, bpm):
        """
        スタイル推定ロジック:
        - BPM < 80 → ballad
        - onset密度低い + BPM低め → ballad
        - onset間隔にスウィング感（3連符比率）→ jazz
        - シンコペーション多い → bossa
        - それ以外 → rock
        """
        import librosa
        if len(self.buffer) < self.sr * 3:
            return self.current_style

        self._count += 1
        if self._count % 4 != 0:  # 4回に1回推定
            return self.current_style

        try:
            onset_env = librosa.onset.onset_strength(y=self.buffer, sr=self.sr)
            onsets = librosa.onset.onset_detect(
                onset_envelope=onset_env, sr=self.sr, units='time'
            )

            if len(onsets) < 3:
                # ほとんど弾いてない → ballad
                new_style = 'ballad'
            else:
                # onset密度（1秒あたりのonset数）
                duration = len(self.buffer) / self.sr
                density = len(onsets) / duration

                # onset間隔
                intervals = np.diff(onsets)

                if bpm < 80:
                    new_style = 'ballad'
                elif density < 1.5 and bpm < 95:
                    new_style = 'ballad'
                elif len(intervals) >= 3:
                    # スウィング検出: 長短の交互パターン
                    beat_dur = 60.0 / bpm
                    # 3連符の比率（長:短 = 2:1）
                    swing_ratios = []
                    for i in range(0, len(intervals)-1, 2):
                        if intervals[i+1] > 0.05:
                            swing_ratios.append(intervals[i] / intervals[i+1])
                    if swing_ratios:
                        avg_ratio = np.mean(swing_ratios)
                        # スウィング比 1.5-2.5 → jazz
                        if 1.4 < avg_ratio < 2.8:
                            new_style = 'jazz'
                        # シンコペーション: 拍の裏にonsetが多い
                        elif density > 2.5 and bpm > 90:
                            # 裏拍の割合
                            off_beats = 0
                            for o in onsets:
                                pos_in_beat = (o % beat_dur) / beat_dur
                                if 0.3 < pos_in_beat < 0.7:
                                    off_beats += 1
                            offbeat_ratio = off_beats / len(onsets)
                            if offbeat_ratio > 0.4:
                                new_style = 'bossa'
                            else:
                                new_style = 'rock'
                        else:
                            new_style = 'rock'
                    else:
                        new_style = 'rock'
                else:
                    new_style = 'rock'

            if new_style != self.current_style:
                old = self.current_style
                self.current_style = new_style
                style_names = {'rock':'🎸ロック','jazz':'🎷ジャズ','bossa':'🌴ボサノバ','ballad':'🕯️バラード'}
                print(f"🎵 スタイル: {style_names.get(old,old)} → {style_names.get(new_style,new_style)}")

        except Exception as e:
            print(f"⚠️ スタイル推定エラー: {e}")

        return self.current_style

    def reset(self):
        self.buffer = np.array([], dtype=np.float32)


# ============================================================
# 録音・検出
# ============================================================
def record(dur, sr):
    p = '/tmp/pal_guitar_rec.wav'
    try:
        r = subprocess.run([
            'ffmpeg','-y','-loglevel','error','-f','pulse','-i',PULSE_MIC,
            '-t',str(dur),'-ar',str(sr),'-ac','1','-acodec','pcm_s16le',
            '-filter:a','volume=10.0', p
        ], timeout=dur+10, capture_output=True, text=True,
           start_new_session=True)
        if r.returncode != 0 or not os.path.exists(p) or os.path.getsize(p) < 100:
            return np.zeros(int(sr*dur))
        with wave.open(p,'r') as wf:
            return np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32)/32768.0
    except:
        return np.zeros(int(sr*dur))

def detect(audio, sr):
    import librosa
    if len(audio) < sr*0.3: return None, 0
    chroma = np.mean(librosa.feature.chroma_stft(y=audio, sr=sr, n_fft=min(2048,len(audio))), axis=1)
    if noise_chroma is not None:
        chroma = np.maximum(chroma - noise_chroma, 0)
    if np.sum(chroma) < 0.05: return None, 0
    best, sc = None, -1
    for nm, t in CHORDS.items():
        t = np.array(t[:12], dtype=float)
        s = np.dot(chroma, t) / (np.linalg.norm(chroma)*np.linalg.norm(t)+1e-8)
        if s > sc: sc, best = s, nm
    return best, sc

def save_wav(audio, path, sr=22050):
    a16 = np.int16(np.clip(audio, -1, 1)*32767)
    with wave.open(path,'w') as wf:
        wf.setnchannels(1);wf.setsampwidth(2);wf.setframerate(sr);wf.writeframes(a16.tobytes())

# ============================================================
# ドラム音色（共通）
# ============================================================
def _kick(sr, vol=0.22):
    dur=0.2; t=np.linspace(0,dur,int(sr*dur),endpoint=False)
    freq=55+70*np.exp(-t*30); phase=2*np.pi*np.cumsum(freq)/sr
    body=np.sin(phase)*np.exp(-t*13)
    sub=0.4*np.sin(2*np.pi*50*t)*np.exp(-t*10)
    return vol*(body+sub)

def _snare(sr, vol=0.14):
    dur=0.15; n=int(sr*dur); t=np.linspace(0,dur,n,endpoint=False)
    body=0.4*np.sin(2*np.pi*185*t)*np.exp(-t*20)
    noise=0.5*np.random.randn(n)*np.exp(-t*18)
    wire=0.2*np.random.randn(n)*np.exp(-np.linspace(3,15,n))
    return vol*(body+noise+wire)

def _hh_closed(sr, vol=0.07):
    n=int(sr*0.05); return vol*np.random.randn(n)*np.exp(-np.linspace(0,18,n))

def _ride(sr, vol=0.10):
    from scipy.signal import lfilter
    dur=0.2; n=int(sr*dur); t=np.linspace(0,dur,n,endpoint=False)
    s=(0.3*np.sin(2*np.pi*680*t)+0.2*np.sin(2*np.pi*1360*t)+0.1*np.sin(2*np.pi*2800*t))*np.exp(-t*12)
    noise=np.random.randn(n)*np.exp(-np.linspace(0,15,n))*0.2
    noise=lfilter([1,-0.85],[1.0],noise)
    return vol*(s+noise)

def _brush(sr, vol=0.10):
    from scipy.signal import lfilter
    dur=0.15; n=int(sr*dur); t=np.linspace(0,dur,n,endpoint=False)
    noise=lfilter([0.15,0.15,0.15,0.15,0.15],[1.0],np.random.randn(n))
    body=0.3*np.sin(2*np.pi*180*t)*np.exp(-t*25)
    return vol*(noise*0.5+body)*np.exp(-t*12)

def _rimshot(sr, vol=0.12):
    dur=0.04; n=int(sr*dur); t=np.linspace(0,dur,n,endpoint=False)
    return vol*(0.5*np.sin(2*np.pi*800*t)+0.15*np.random.randn(n))*np.exp(-t*40)

def _shaker(sr, vol=0.05):
    from scipy.signal import lfilter
    dur=0.07; n=int(sr*dur)
    return vol*lfilter([1,-0.6],[1.0],np.random.randn(n)*np.exp(-np.linspace(0,18,n)))

def _bass_pure(freq, dur, sr, vol=0.25):
    """基音のみベース（クリーン）"""
    t = np.linspace(0, dur, int(sr*dur), endpoint=False)
    s = vol * np.sin(2*np.pi*freq*t)
    # スムーズなアタック（10ms）
    att = min(int(0.01*sr), len(t)); s[:att] *= np.linspace(0,1,att)
    # スムーズなリリース（150ms）
    dec = min(int(0.15*sr), len(s)//2)
    if dec > 0: s[-dec:] *= np.linspace(1,0,dec)
    return s

# ============================================================
# ループ生成（4スタイル）
# ============================================================
def _mix(out, src, p):
    p=int(p); e=min(p+len(src),len(out))
    if 0<=p<len(out): out[p:e]+=src[:e-p]

def _add_bass(out, chord, bpm, bars, sr, style):
    """共通ベースライン（基音のみ）"""
    bd = 60.0/bpm
    root = chord[0]; bf = FREQS_LOW.get(root, 110.0)
    mi = 'm' in chord and len(chord) > 1

    for bar in range(bars):
        off = bar*bd*4*sr
        if style == 'bossa':
            # ボサノバ: シンコペーションベース
            pattern = [(0, bf), (1.5, bf*(1.189 if mi else 1.26)), (2, bf*1.498), (3.5, bf*0.944)]
            for pos, f in pattern:
                _mix(out, _bass_pure(f, bd*0.6, sr), int(off+pos*bd*sr))
        elif style == 'ballad':
            # バラード: ロングノート（1拍目と3拍目）
            for beat, f in [(0, bf), (2, bf*1.498)]:
                _mix(out, _bass_pure(f, bd*1.5, sr, 0.20), int(off+beat*bd*sr))
        else:
            # ロック/ジャズ: ウォーキングベース
            walk = [bf, bf*(1.189 if mi else 1.26), bf*1.498, bf*0.944]
            for beat in range(4):
                _mix(out, _bass_pure(walk[beat], bd*0.75, sr), int(off+beat*bd*sr))

def make_loop(chord, bpm, bars, sr, style):
    bd = 60.0/bpm; total = int(sr*bd*4*bars); out = np.zeros(total)

    # ドラム
    if style == 'rock':
        _drums_rock(out, bd, bars, sr)
    elif style == 'jazz':
        _drums_jazz(out, bd, bars, sr)
    elif style == 'bossa':
        _drums_bossa(out, bd, bars, sr)
    elif style == 'ballad':
        _drums_ballad(out, bd, bars, sr)

    # ベース
    _add_bass(out, chord, bpm, bars, sr, style)

    # マスター音量（クリッピング防止）
    mx = np.max(np.abs(out))
    if mx > 0.7: out *= 0.7/mx
    return out

def _drums_rock(out, bd, bars, sr):
    for bar in range(bars):
        off = int(bar*bd*4*sr)
        for beat in range(4):
            p = off+int(beat*bd*sr)
            if beat in [0,2]: _mix(out, _kick(sr), p)
            if beat in [1,3]: _mix(out, _snare(sr), p)
            _mix(out, _hh_closed(sr), p)
            _mix(out, _hh_closed(sr, 0.04), int(p+0.5*bd*sr))

def _drums_jazz(out, bd, bars, sr):
    sw = 2.0/3.0
    for bar in range(bars):
        off = bar*bd*4*sr
        for beat in range(4):
            bp = int(off+beat*bd*sr)
            sp = int(off+(beat+sw)*bd*sr)
            _mix(out, _ride(sr), bp)
            _mix(out, _ride(sr, 0.06), sp)
            if beat in [1,3]: _mix(out, _brush(sr), bp)
            if beat == 0: _mix(out, _kick(sr, 0.15), bp)
            elif beat == 2 and bar%2 == 0: _mix(out, _kick(sr, 0.12), bp)

def _drums_bossa(out, bd, bars, sr):
    rim_pos = [0, 0.5, 1.5, 2, 3, 3.5]
    for bar in range(bars):
        off = bar*bd*4*sr
        for pos in rim_pos:
            _mix(out, _rimshot(sr), int(off+pos*bd*sr))
        for beat in [0, 2]:
            _mix(out, _kick(sr, 0.15), int(off+beat*bd*sr))
        for i in range(8):
            _mix(out, _shaker(sr), int(off+i*0.5*bd*sr))

def _drums_ballad(out, bd, bars, sr):
    for bar in range(bars):
        off = int(bar*bd*4*sr)
        for beat in range(4):
            bp = off+int(beat*bd*sr)
            if beat == 0: _mix(out, _kick(sr, 0.18), bp)
            if beat == 2: _mix(out, _snare(sr, 0.08), bp)
            _mix(out, _hh_closed(sr, 0.04), bp)

# ============================================================
# メインループ
# ============================================================
def main():
    global noise_chroma
    import librosa, gc

    print("="*50)
    print("🎸 ギターセッション・パル v5")
    print(f"   BPM自動検出 | スタイル自動推定")
    print(f"   パターン: rock / jazz / bossa / ballad")
    print(f"   Ctrl+C で終了")
    print("="*50)
    print()
    print("🔧 キャリブレーション中...（3秒静かに）")
    cal = record(3.0, SR)
    nr = np.sqrt(np.mean(cal**2))
    if len(cal) > SR*0.5:
        noise_chroma = np.mean(librosa.feature.chroma_stft(y=cal, sr=SR, n_fft=min(2048,len(cal))), axis=1)
    base_threshold = 0.15
    play_threshold = 0.30
    print(f"✅ ノイズRMS: {nr:.4f}")
    print(f"   閾値: 待機={base_threshold} / 再生中={play_threshold}")
    print()
    print("🎵 準備OK！ギターを弾いてね！")
    print()

    wav_path = os.path.join(tempfile.gettempdir(), 'pal_drum_loop.wav')
    player = None
    cur_chord = None
    cur_bpm = DEFAULT_BPM
    cur_style = 'rock'
    tempo_tracker = TempoTracker(SR, TEMPO_BUF_SEC, MIN_BPM, MAX_BPM)
    style_detector = StyleDetector(SR)
    no_sound = 0
    lc = 0

    while running:
        try:
            lc += 1
            audio = record(CHUNK, SR)
            rms = np.sqrt(np.mean(audio**2))

            playing = player is not None and player.is_playing
            threshold = play_threshold if playing else base_threshold

            if rms < threshold:
                no_sound += 1
                if no_sound == 1:
                    print(f"🔇 (RMS:{rms:.3f} < {threshold:.3f})")
                if no_sound >= 6 and cur_chord:
                    if player: player.stop()
                    player = None
                    cur_chord = None
                    tempo_tracker.reset()
                    style_detector.reset()
                    print("⏸️ 待機中...")
                continue

            # テンポ・スタイル推定
            tempo_tracker.add(audio)
            style_detector.add(audio)
            new_bpm = tempo_tracker.estimate()
            new_style = style_detector.estimate(new_bpm)

            chord, conf = detect(audio, SR)

            need_rebuild = False
            if chord and conf > 0.65:
                no_sound = 0
                if chord != cur_chord:
                    style_label = {'rock':'🎸','jazz':'🎷','bossa':'🌴','ballad':'🕯️'}.get(new_style,'')
                    print(f"🎵 {chord} (確信度:{conf:.2f} RMS:{rms:.3f} BPM:{new_bpm} {style_label}{new_style})")
                    cur_chord = chord
                    need_rebuild = True
                elif new_bpm != cur_bpm or new_style != cur_style:
                    need_rebuild = True

                if need_rebuild:
                    cur_bpm = new_bpm
                    cur_style = new_style
                    loop = make_loop(cur_chord, cur_bpm, BARS, SR, cur_style)
                    save_wav(loop, wav_path, SR)
                    if player: player.stop()
                    player = LoopPlayer(wav_path, SPEAKER)
                    _all_players.append(player)
            else:
                no_sound += 1
                if no_sound >= 6 and cur_chord:
                    if player: player.stop()
                    player = None
                    cur_chord = None
                    tempo_tracker.reset()
                    style_detector.reset()
                    print("⏸️ 待機中...")

            if lc % 50 == 0: gc.collect()

        except KeyboardInterrupt:
            break
        except Exception as e:
            import traceback
            print(f"⚠️ {e}"); traceback.print_exc()
            time.sleep(1)

    kill_all_players()
    print("👋 またね！")

if __name__ == '__main__':
    # Pythonレベルでも排他ロック
    lock_fp = open('/tmp/guitar_session_py.lock', 'w')
    try:
        fcntl.flock(lock_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        print(f"⚠️ 既に別インスタンスが起動中。終了。 PID={os.getpid()}")
        sys.exit(0)

    try: main()
    except Exception as e:
        import traceback; print(f"💀 {e}"); traceback.print_exc()
    finally:
        print(f"🔚 終了 PID={os.getpid()}")
        lock_fp.close()
