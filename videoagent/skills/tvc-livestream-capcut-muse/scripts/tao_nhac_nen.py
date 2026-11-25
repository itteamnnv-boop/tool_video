"""Tự tạo NHẠC NỀN gốc (tổng hợp bằng numpy/scipy — không dùng nhạc có bản quyền) cho video livestream.

python -P tao_nhac_nen.py --project D:/CapCut/TenDuAn [--seconds 50] [--style upbeat|chill] [--bpm 112] [--key G] [--seed 7]
Hoặc: python -P tao_nhac_nen.py --out nhac.wav --seconds 30
(build_draft.py --music gọi hàm make_music() với đúng độ dài timeline.)

Cấu trúc: intro 1 ô nhịp → đoạn chính (kick 4/4 + sidechain "nhún", clap 2&4, hi-hat, bass nảy, hợp âm stab,
pad, giai điệu marimba ngũ cung theo seed) → fill cuối mỗi câu 8 ô → fade out. Vòng hợp âm I–V–vi–IV.
Cấu hình trong du_an.json (tuỳ chọn): "music": {"style": "upbeat", "bpm": 112, "key": "G", "seed": 7, "volume": 0.15}
"""
import argparse, json, math
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, fftconvolve, sosfilt

SR = 44100
NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7,
        "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}
STYLES = {
    "upbeat": dict(bpm=112, kick=1.0, clap=0.38, hat=0.14, bass=0.6, stab=0.4, pad=0.22, mel=0.38, swing=0.0),
    "chill": dict(bpm=92, kick=0.7, clap=0.25, hat=0.09, bass=0.5, stab=0.22, pad=0.34, mel=0.32, swing=0.12),
    # "dong_luc": nhạc không lời sôi động, vui tươi, tạo động lực (pop sáng, hợp âm piano rõ, giai điệu bay bổng)
    "dong_luc": dict(bpm=124, kick=0.9, clap=0.45, hat=0.15, bass=0.55, stab=0.6, pad=0.26, mel=0.48, swing=0.0),
    # "shopping": tươi sáng, nảy, giai điệu cao rộn ràng kiểu nhạc nền sàn TMĐT
    "shopping": dict(bpm=120, kick=0.85, clap=0.42, hat=0.16, bass=0.5, stab=0.5, pad=0.14, mel=0.5, swing=0.06),
}


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def lp(x, f, order=2):
    return sosfilt(butter(order, min(f, SR / 2 - 100), "low", fs=SR, output="sos"), x)


def hp(x, f, order=2):
    return sosfilt(butter(order, f, "high", fs=SR, output="sos"), x)


def add(buf, sig, t0, gain=1.0, pan=0.0):
    i = int(t0 * SR)
    if i >= buf.shape[1] or i < 0:
        return
    n = min(len(sig), buf.shape[1] - i)
    l, r = math.cos((pan + 1) * math.pi / 4), math.sin((pan + 1) * math.pi / 4)
    buf[0, i:i + n] += sig[:n] * gain * l * 1.414
    buf[1, i:i + n] += sig[:n] * gain * r * 1.414


def env(n, a=0.003, d=0.2):
    t = np.arange(n) / SR
    return np.minimum(1.0, t / max(a, 1e-4)) * np.exp(-t / max(d, 1e-4))


def additive(freq, dur, harm=6, bright=1.0):
    t = np.arange(int(dur * SR)) / SR
    s = np.zeros_like(t)
    for k in range(1, harm + 1):
        if freq * k > SR / 2.2:
            break
        s += np.sin(2 * np.pi * freq * k * t + k) * (bright ** (k - 1)) / k
    return s


def kick():
    t = np.arange(int(0.4 * SR)) / SR
    f = 48 + 90 * np.exp(-t * 32)
    ph = 2 * np.pi * np.cumsum(f) / SR
    s = np.sin(ph) * np.exp(-t * 7.5) + 0.25 * np.random.default_rng(1).standard_normal(len(t)) * np.exp(-t * 250)
    return np.tanh(1.6 * s)


def clap(rng):
    n = int(0.25 * SR)
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    e = np.exp(-t * 22) + 0.6 * np.exp(-np.maximum(0, t - 0.012) * 60) * (t > 0.012) + 0.5 * np.exp(-np.maximum(0, t - 0.024) * 60) * (t > 0.024)
    return hp(lp(noise, 3200), 800) * e


def hat(rng, open_=False):
    n = int((0.16 if open_ else 0.05) * SR)
    t = np.arange(n) / SR
    return hp(rng.standard_normal(n), 7000, 4) * np.exp(-t * (18 if open_ else 70))


def reverb(x, secs=1.3, mix=0.2, seed=3):
    rng = np.random.default_rng(seed)
    n = int(secs * SR)
    ir = rng.standard_normal((2, n)) * np.exp(-np.arange(n) / SR * (6.9 / secs))
    ir = lp(ir, 5000)
    wet = np.stack([fftconvolve(x[0], ir[0])[: x.shape[1]], fftconvolve(x[1], ir[1])[: x.shape[1]]])
    wet *= np.sqrt(np.mean(x ** 2) / (np.mean(wet ** 2) + 1e-12))
    return x * (1 - mix) + wet * mix


def make_music(seconds, out_path, style="upbeat", bpm=None, key="G", seed=7):
    st = STYLES.get(style, STYLES["upbeat"])
    bpm = bpm or st["bpm"]
    rng = np.random.default_rng(seed)
    beat = 60.0 / bpm
    bar = 4 * beat
    total = seconds + 0.05
    n_bars = int(math.ceil(total / bar)) + 1
    N = int((n_bars * bar + 2) * SR)
    drums, music, wetbus = np.zeros((2, N)), np.zeros((2, N)), np.zeros((2, N))
    root = 48 + NOTE.get(key, 7)  # nốt gốc quãng 3
    prog = [0, 7, 9, 5]            # I – V – vi – IV
    minor = {9}
    penta = [0, 2, 4, 7, 9, 12, 14, 16]
    k_snd, c_snd = kick(), clap(rng)
    motif = rng.choice(len(penta), size=8)
    rhythm = rng.random(8) < 0.7
    duck = np.ones(N)
    for b in range(n_bars):
        t_bar = b * bar
        deg = prog[b % 4]
        chord = [root + deg, root + deg + (3 if deg in minor else 4), root + deg + 7]
        intro = b == 0
        fill = (b % 8) == 7
        sw = st["swing"] * beat / 2
        # trống
        for q in range(4):
            tq = t_bar + q * beat
            if not intro and not (fill and q == 3):
                add(drums, k_snd, tq, st["kick"])
                i = int(tq * SR)
                L = int(0.35 * SR)
                duck[i:i + L] = np.minimum(duck[i:i + L], 1 - 0.55 * np.exp(-np.arange(min(L, N - i)) / SR * 9))
            if q in (1, 3) and not intro:
                add(drums, c_snd, tq, st["clap"], pan=0.05)
            for e in range(2):
                th = tq + e * beat / 2 + (sw if e else 0)
                add(drums, hat(rng, open_=(e == 1 and q == 3)), th, st["hat"] * (1.0 if e else 0.6), pan=0.25)
        if fill:  # fill clap cuối câu
            for s in range(4):
                add(drums, c_snd, t_bar + 3 * beat + s * beat / 4, st["clap"] * (0.5 + 0.15 * s))
        # bass 8 nốt móc đơn
        for e in range(8):
            if intro and e < 4:
                continue
            note = root - 12 + deg + (12 if e in (3, 7) else 0)
            sig = lp(additive(hz(note), beat / 2 * 0.95, harm=8, bright=0.8), 700) * env(int(beat / 2 * 0.95 * SR), 0.004, 0.16)
            add(music, sig, t_bar + e * beat / 2 + (sw if e % 2 else 0), st["bass"])
        # pad cả ô nhịp
        pad = sum(additive(hz(n + 12) * (1 + d), bar, harm=4, bright=0.5) for n in chord for d in (-0.003, 0.003))
        pad = lp(pad, 1400) * np.minimum(1, np.arange(len(pad)) / SR / 0.25) * np.exp(-np.arange(len(pad)) / SR / 3.0)
        add(wetbus, pad / 6, t_bar, st["pad"])
        # hợp âm stab ở phách lẻ
        if not intro:
            for q in range(4):
                stab = sum(additive(hz(n + 12), 0.3, harm=6, bright=0.75) for n in chord)
                stab = lp(stab, 2600) * env(len(stab), 0.003, 0.11)
                add(wetbus, stab / 3, t_bar + q * beat + beat / 2 + sw, st["stab"], pan=-0.2)
        # giai điệu marimba (từ ô 3, nghỉ 1 ô mỗi câu để thở)
        if b >= 2 and (b % 8) not in (3, 7):
            var = (b // 4) % 2
            for s in range(8):
                if not rhythm[s]:
                    continue
                n = root + 24 + penta[(motif[s] + var * 2) % len(penta)]
                d = 0.32
                t = np.arange(int(d * SR)) / SR
                sig = (np.sin(2 * np.pi * hz(n) * t) + 0.25 * np.sin(2 * np.pi * hz(n) * 4 * t) * np.exp(-t * 30)) * env(len(t), 0.002, 0.13)
                add(wetbus, sig, t_bar + s * beat / 2 + (sw if s % 2 else 0), st["mel"], pan=0.3 if s % 2 else -0.1)
    music = (music + reverb(wetbus, 1.3, 0.25)) * duck
    mix = drums + music
    L = int(total * SR)
    mix = mix[:, :L]
    t = np.arange(L) / SR
    mix *= np.minimum(1, t / 0.4) * np.clip((total - t) / 2.0, 0, 1)
    rms = np.sqrt(np.mean(mix ** 2)) + 1e-9
    mix *= 10 ** (-16 / 20) / rms        # ~ -16 dBFS RMS
    mix = np.tanh(mix * 1.1) / np.tanh(1.1)  # soft clip
    mix *= 0.95 / max(1e-9, np.max(np.abs(mix)))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(out_path, SR, (mix.T * 32767).astype(np.int16))
    print(f"Nhạc nền: {out_path} ({total:.1f}s, {style}, {bpm} BPM, giọng {key}, seed {seed})")
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--out")
    ap.add_argument("--seconds", type=float)
    ap.add_argument("--style", choices=list(STYLES))
    ap.add_argument("--bpm", type=int)
    ap.add_argument("--key")
    ap.add_argument("--seed", type=int)
    a = ap.parse_args()
    cfg = {}
    out = a.out
    secs = a.seconds
    if a.project:
        proj = Path(a.project)
        data = json.loads((proj / "02_kich_ban" / "du_an.json").read_text(encoding="utf-8"))
        cfg = data.get("music", {}) or {}
        out = out or proj / "03_nhac" / "nhac_nen.wav"
        if secs is None:
            spec = proj / "07_capcut_spec" / "spec.json"
            if spec.exists():
                s = json.loads(spec.read_text(encoding="utf-8"))
                clips = next(t["items"] for t in s["tracks"] if t["name"] == "clip_live")
                secs = clips[-1]["start"] + clips[-1]["duration"]
    make_music(secs or 50, out or "nhac_nen.wav", a.style or cfg.get("style", "upbeat"), a.bpm or cfg.get("bpm"),
               a.key or cfg.get("key", "G"), a.seed if a.seed is not None else cfg.get("seed", 7))


if __name__ == "__main__":
    main()
