"""Tự tạo TẠP ÂM NỀN gốc (tổng hợp bằng numpy/scipy — không dùng file âm thanh có bản quyền) cho video livestream.

python -P tao_tap_am.py --out tap_am.wav --seconds 40 [--style nha_may] [--seed 3]
(build_draft.py gọi make_ambience() với đúng độ dài timeline khi có --ambience hoặc mục "ambience" trong du_an.json.)

Kiểu "nha_may" (mặc định, bản 2 — sinh động hơn theo góp ý người dùng 2026-11-19):
- nền xưởng: máy chạy ù, băng tải lách cách, xe tải nổ máy xa, vang xưởng lớn
- THẢ HÀNG dày đặc: bao rơi xuống sàn (thịch + sột soạt), xô nhựa đặt chồng lên nhau (cạch–cạch),
  pallet gỗ thả xuống (cộp nảy 2–3 lần), va kim loại
- kéo bao/thùng trượt trên sàn, xe đẩy tay chở hàng lăn nhẹ
- XE CHẠY (xe nâng Doppler, bíp lùi, còi, xe tải) chỉ khi "vehicles": true — mặc định TẮT (người dùng thấy khó chịu)
- xì hơi khí nén máy chiết rót
Kiểu "boc_xep" (người dùng chọn theo video mẫu "tiếng ồn bốc xếp hàng hoá", 2026-11-19): 4 công nhân bốc xếp
liên tục, mỗi người một nhịp và vị trí riêng — quăng bao lên đống, đặt chồng xô, thả thùng carton, thỉnh thoảng thả pallet.
Cấu hình trong du_an.json (tuỳ chọn): "ambience": {"style": "boc_xep", "seed": 3, "volume": 0.35, "vehicles": false}
"""
import argparse
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, fftconvolve, sosfilt

SR = 44100


def _bp(x, lo, hi, order=4):
    return sosfilt(butter(order, [lo, hi], btype="band", fs=SR, output="sos"), x)


def _lp(x, f, order=4):
    return sosfilt(butter(order, f, btype="low", fs=SR, output="sos"), x)


def _hp(x, f, order=4):
    return sosfilt(butter(order, f, btype="high", fs=SR, output="sos"), x)


def _pan(mono, p):
    """p: -1 (trái) .. 1 (phải), số hoặc mảng cùng độ dài."""
    p = np.asarray(p, dtype=float)
    return np.stack([mono * np.cos((p + 1) * np.pi / 4), mono * np.sin((p + 1) * np.pi / 4)], axis=1)


def _add(mix, i, stereo):
    n = mix.shape[0]
    if i < 0 or i >= n:
        return
    k = min(len(stereo), n - i)
    mix[i:i + k] += stereo[:k]


def _env(L, attack, decay):
    a = np.arange(L)
    return np.minimum(1, a / max(1, attack * SR)) * np.exp(-a / max(1, decay * SR))


def _modes(freqs_amps, L, decay, rng):
    t = np.arange(L) / SR
    out = np.zeros(L)
    for f, a in freqs_amps:
        f *= rng.uniform(0.95, 1.05)
        out += a * np.sin(2 * np.pi * f * t + rng.uniform(0, 6.28)) * np.exp(-t / (decay * rng.uniform(0.7, 1.3)))
    return out


def _distance(mono, far):
    """far 0 (gần) .. 1 (xa): xa thì nhỏ và mất tiếng cao."""
    return _lp(mono, 9000 - 7000 * far, 2) * (1.0 - 0.7 * far)


# ---------- sự kiện thả hàng ----------
def ev_bag_drop(rng):
    L = int(0.6 * SR)
    t = np.arange(L) / SR
    sweep = np.sin(2 * np.pi * np.cumsum(110 * np.exp(-t / 0.06) + 45) / SR) * np.exp(-t / 0.14)
    body = _lp(rng.standard_normal(L), 350) * _env(L, 0.002, 0.07) * 3
    rustle = _bp(rng.standard_normal(L), 1200, 5000) * _env(L, 0.003, 0.12) * 0.5
    return 0.9 * sweep + body + rustle


def ev_bucket_set(rng):
    """xô nhựa đặt xuống / chồng lên nhau: 1–3 tiếng cạch rỗng."""
    out = np.zeros(int(0.9 * SR))
    tc = 0.0
    for _ in range(rng.integers(1, 4)):
        L = int(0.25 * SR)
        hit = _modes([(170, 1), (390, 0.8), (660, 0.5), (1120, 0.35), (2300, 0.15)], L, 0.05, rng)
        hit += _bp(rng.standard_normal(L), 800, 6000) * _env(L, 0.0005, 0.012) * 1.2
        i = int(tc * SR)
        k = min(L, len(out) - i)
        out[i:i + k] += hit[:k] * rng.uniform(0.5, 1.0) * 0.6
        tc += rng.uniform(0.12, 0.3)
    return out


def ev_pallet_drop(rng):
    """pallet gỗ thả xuống: cộp + nảy 2–3 lần."""
    out = np.zeros(int(0.8 * SR))
    tc, amp = 0.0, 1.0
    for _ in range(rng.integers(2, 4)):
        L = int(0.2 * SR)
        hit = _modes([(140, 1), (260, 0.8), (520, 0.5), (940, 0.3)], L, 0.035, rng)
        hit += _lp(rng.standard_normal(L), 2500) * _env(L, 0.0005, 0.02) * 1.5
        i = int(tc * SR)
        k = min(L, len(out) - i)
        out[i:i + k] += hit[:k] * amp
        tc += rng.uniform(0.07, 0.12) * amp
        amp *= 0.45
    return out


def ev_metal(rng):
    L = int(0.9 * SR)
    f0 = rng.uniform(380, 900)
    clank = _modes([(f0, 1), (f0 * 2.76, 0.6), (f0 * 5.4, 0.35), (f0 * 8.9, 0.2)], L, 0.12, rng)
    clank += _hp(rng.standard_normal(L), 2000) * _env(L, 0.0005, 0.01)
    return clank * 0.5


def ev_hiss(rng):
    L = int(rng.uniform(0.25, 0.6) * SR)
    return _hp(rng.standard_normal(L), 3000) * _env(L, 0.02, 0.2) * 0.35


# ---------- xe chạy ----------
def ev_forklift(rng, D):
    """xe nâng điện chạy ngang có Doppler; trả về (mono, pan)."""
    L = int(D * SR)
    t = np.arange(L) / SR
    x = np.linspace(-1, 1, L) * rng.choice([-1, 1])           # vị trí ngang
    y = rng.uniform(0.25, 0.6)                                # khoảng cách tới máy quay
    dist = np.sqrt((x * 6) ** 2 + (y * 6) ** 2)
    vx = np.gradient(x * 6, 1 / SR)
    vr = (x * 6) * vx / (dist + 1e-6)                         # vận tốc hướng tâm
    dop = 343 / (343 + vr)
    speed = 1 + 0.15 * np.sin(2 * np.pi * rng.uniform(0.2, 0.4) * t)    # nhả/ăn ga
    f_motor = rng.uniform(170, 240) * speed * dop
    ph = 2 * np.pi * np.cumsum(f_motor) / SR
    whine = np.sin(ph) + 0.5 * np.sin(2 * ph) + 0.25 * np.sin(3 * ph) + 0.15 * np.sin(5.03 * ph)
    whine *= 0.18
    tires = _bp(rng.standard_normal(L), 120, 900) * (0.6 + 0.4 * np.sin(2 * np.pi * 11 * t * dop))
    rattle = _bp(rng.standard_normal(L), 1500, 5000) * (rng.random(L) < 0.004) * 6
    rattle = _lp(np.abs(rattle), 3000) * 0.3
    body = whine + tires * 0.9 + rattle
    gain = 1.0 / (1 + (dist / 3.0) ** 2)
    mono = body * gain * 1.6
    pan = np.clip(x * 0.9, -0.95, 0.95)
    return mono, pan


def ev_lift(rng):
    """thuỷ lực nâng càng: tiếng rít đều đi lên."""
    L = int(rng.uniform(1.0, 1.8) * SR)
    t = np.arange(L) / SR
    f = np.linspace(rng.uniform(420, 520), rng.uniform(600, 720), L)
    ph = 2 * np.pi * np.cumsum(f) / SR
    s = (np.sin(ph) + 0.3 * np.sin(2 * ph)) * 0.12 + _bp(rng.standard_normal(L), 300, 1500) * 0.15
    return s * np.minimum(1, t / 0.15) * np.minimum(1, (t[-1] - t) / 0.2)


def ev_beeps(rng, count):
    BL, gap = int(0.28 * SR), int(0.56 * SR)
    out = np.zeros(gap * count)
    beep = np.sin(2 * np.pi * 1150 * np.arange(BL) / SR) * np.minimum(1, np.arange(BL) / 150) * 0.22
    for k in range(count):
        out[k * gap:k * gap + BL] += beep
    return out


def ev_horn(rng):
    L = int(0.32 * SR)
    t = np.arange(L) / SR
    h = sum(np.sign(np.sin(2 * np.pi * f * t)) * 0.5 for f in (415, 523))
    h = _lp(h, 2500) * np.minimum(1, t / 0.01) * np.minimum(1, (t[-1] - t) / 0.02) * 0.18
    out = np.zeros(int(0.75 * SR))
    out[:L] += h
    if rng.random() < 0.6:
        out[int(0.4 * SR):int(0.4 * SR) + L] += h
    return out


def ev_pallet_jack(rng, D):
    L = int(D * SR)
    rumble = _bp(rng.standard_normal(L), 200, 1200) * 0.35
    clicks = (rng.random(L) < 0.012).astype(float) * rng.uniform(0.3, 1, L)
    clicks = _bp(clicks, 1800, 7000) * 4
    env = np.sin(np.pi * np.arange(L) / L) ** 1.5
    return (rumble + clicks) * env * 0.5


def ev_drag(rng):
    """kéo/đẩy bao, thùng trượt trên sàn bê tông."""
    L = int(rng.uniform(0.5, 1.1) * SR)
    t = np.arange(L) / SR
    grit = _bp(rng.standard_normal(L), 250, 2500) * (0.7 + 0.3 * np.sin(2 * np.pi * rng.uniform(6, 12) * t))
    env = np.minimum(1, t / 0.05) * np.minimum(1, (t[-1] - t) / 0.12)
    return grit * env * 0.35


def ev_trolley(rng, D):
    """xe đẩy tay chở hàng lăn nhẹ (không động cơ)."""
    L = int(D * SR)
    roll = _bp(rng.standard_normal(L), 150, 900) * 0.25
    bumps = (rng.random(L) < 0.002).astype(float)
    bumps = _lp(bumps, 1500) * 6
    env = np.sin(np.pi * np.arange(L) / L) ** 1.5
    return (roll + bumps) * env * 0.35


def ev_carton(rng):
    """thùng carton đặt/quăng xuống: thịch giữa + tiếng giấy vỗ."""
    L = int(0.4 * SR)
    body = _modes([(130, 1), (240, 0.7), (410, 0.4)], L, 0.04, rng)
    slap = _bp(rng.standard_normal(L), 900, 5000) * _env(L, 0.0005, 0.02) * 1.4
    return (body + slap) * 0.7


def ev_sack_throw(rng):
    """quăng bao lên đống bao: thịch nặng, đục + sột soạt dài hơn (bốc xếp)."""
    L = int(0.7 * SR)
    t = np.arange(L) / SR
    thump = np.sin(2 * np.pi * np.cumsum(90 * np.exp(-t / 0.05) + 40) / SR) * np.exp(-t / 0.12)
    mass = _lp(rng.standard_normal(L), 280) * _env(L, 0.003, 0.09) * 3.2
    rustle = _bp(rng.standard_normal(L), 900, 4500) * _env(L, 0.004, 0.2) * 0.6
    return thump + mass + rustle


LOADING_WORKERS = [  # (kiểu sự kiện chính, nhịp trung bình giây)
    ("sack", 1.05), ("bucket", 1.3), ("carton", 1.6), ("sack", 1.4),
]


def _loading(mix, seconds, rng):
    """bốc xếp hàng: nhiều công nhân, mỗi người một nhịp & vị trí riêng, đều đặn liên tục."""
    gen = {"sack": ev_sack_throw, "bucket": ev_bucket_set, "carton": ev_carton}
    for kind, period in LOADING_WORKERS:
        pan = rng.uniform(-0.85, 0.85)
        far = rng.uniform(0.05, 0.7)
        tc = rng.uniform(0, period)
        while tc < seconds - 0.4:
            g = gen[kind] if rng.random() < 0.8 else gen[rng.choice(list(gen))]
            if rng.random() < 0.08:
                g = ev_pallet_drop
            s = _distance(g(rng), far) * rng.uniform(0.75, 1.25)
            _add(mix, int(tc * SR), _pan(s, np.clip(pan + rng.uniform(-0.1, 0.1), -0.95, 0.95)))
            tc += period * rng.uniform(0.7, 1.35)
            if rng.random() < 0.12:  # nghỉ tay một chút
                tc += rng.uniform(1.0, 2.5)


def make_ambience(seconds, out_path, style="nha_may", seed=3, vehicles=False):
    rng = np.random.default_rng(seed)
    n = int((seconds + 0.1) * SR)
    t = np.arange(n) / SR
    mix = np.zeros((n, 2))

    # --- nền xưởng ---
    hum = sum(a * np.sin(2 * np.pi * f * t + rng.uniform(0, 6.28)) for f, a in
              [(50, 1.0), (100, 0.55), (150, 0.3), (200, 0.18)])
    hum *= 1 + 0.08 * np.sin(2 * np.pi * 0.3 * t)
    room = _lp(rng.standard_normal(n), 400) * 0.12 + _bp(rng.standard_normal(n), 400, 3000) * 0.025
    mix += _pan(0.06 * hum + room, 0.0)
    if vehicles:  # xe tải nổ máy xa (diesel ~26 Hz xung)
        diesel = (np.sin(2 * np.pi * 26 * t) > 0.6).astype(float)
        diesel = _lp(diesel, 220) * (0.7 + 0.3 * np.sin(2 * np.pi * 0.17 * t)) * 0.12
        mix += _pan(diesel, 0.7)
    # băng tải lách cách
    belt = np.zeros(n)
    cl = int(0.025 * SR)
    click = np.exp(-np.arange(cl) / (0.004 * SR)) * _bp(rng.standard_normal(cl), 1500, 6000)
    tc = 0.1
    while tc < seconds:
        i = int(tc * SR)
        k = min(cl, n - i)
        belt[i:i + k] += click[:k] * rng.uniform(0.4, 1.0)
        tc += 0.21 * rng.uniform(0.93, 1.07)
    mix += _pan(_distance(belt * 0.08 + _bp(rng.standard_normal(n), 600, 2800) * 0.03, 0.4), -0.5)

    # --- thả hàng: dày đặc, ngẫu nhiên vị trí/khoảng cách ---
    # tiếng VẬN CHUYỂN HÀNG (người dùng chỉ muốn tiếng này, không muốn tiếng xe chạy)
    gens = [(ev_bag_drop, 0.28), (ev_bucket_set, 0.30), (ev_pallet_drop, 0.15), (ev_drag, 0.17),
            (ev_metal, 0.06), (ev_hiss, 0.04)]
    names, probs = zip(*gens)
    if style == "boc_xep":
        _loading(mix, seconds, rng)
    tc = rng.uniform(0.3, 1.0) if style != "boc_xep" else seconds
    while tc < seconds - 0.5:
        g = names[rng.choice(len(names), p=np.array(probs) / sum(probs))]
        far = rng.uniform(0.0, 0.85)
        s = _distance(g(rng), far) * rng.uniform(0.9, 1.5)
        _add(mix, int(tc * SR), _pan(s, rng.uniform(-0.9, 0.9)))
        tc += rng.uniform(0.5, 1.6)

    # --- xe nâng chạy ngang (chỉ khi vehicles=True; mặc định TẮT vì người dùng thấy khó chịu) ---
    tc = rng.uniform(0.0, 1.5) if vehicles else seconds
    while tc < seconds - 2:
        D = rng.uniform(4.5, 7.5)
        mono, pan = ev_forklift(rng, D)
        i = int(tc * SR)
        _add(mix, i, _pan(mono, pan))
        r = rng.random()
        if r < 0.35:   # bíp lùi
            b = ev_beeps(rng, int(rng.integers(3, 7)))
            j = int(rng.uniform(0.3, max(0.4, D - 2.5)) * SR)
            _add(mix, i + j, _pan(_distance(b, 0.3), float(pan[min(len(pan) - 1, j)])))
        elif r < 0.55:  # còi
            j = int(rng.uniform(0.5, D * 0.5) * SR)
            _add(mix, i + j, _pan(ev_horn(rng), float(pan[min(len(pan) - 1, j)])))
        if rng.random() < 0.4:  # nâng càng thuỷ lực
            j = int(rng.uniform(0.5, D * 0.6) * SR)
            _add(mix, i + j, _pan(_distance(ev_lift(rng), 0.35), float(pan[min(len(pan) - 1, j)])))
        tc += rng.uniform(3.0, 6.0)

    # --- xe đẩy tay chở hàng lăn nhẹ ---
    tc = rng.uniform(2.0, 5.0)
    while tc < seconds - 2:
        D = rng.uniform(1.5, 2.8)
        L = int(D * SR)
        _add(mix, int(tc * SR), _pan(_distance(ev_trolley(rng, D), rng.uniform(0.2, 0.6)),
                                    np.linspace(rng.uniform(-0.7, 0), rng.uniform(0, 0.7), L)))
        tc += rng.uniform(6.0, 10.0)

    # --- xe đẩy pallet lạch cạch (chỉ khi vehicles=True) ---
    if not vehicles:
        tc = seconds
    else:
        tc = rng.uniform(3.0, 6.0)
    while tc < seconds - 2:
        D = rng.uniform(1.8, 3.2)
        L = int(D * SR)
        _add(mix, int(tc * SR), _pan(_distance(ev_pallet_jack(rng, D), rng.uniform(0.1, 0.6)),
                                    np.linspace(rng.uniform(-0.8, 0), rng.uniform(0, 0.8), L)))
        tc += rng.uniform(7.0, 12.0)

    # --- vang xưởng lớn (sớm + đuôi ~1.3s) ---
    ir_len = int(1.3 * SR)
    a = np.arange(ir_len)
    ir = rng.standard_normal(ir_len) * np.exp(-a / (0.35 * SR))
    for d in (0.013, 0.021, 0.034, 0.047):  # phản xạ sớm
        ir[int(d * SR)] += rng.uniform(1.5, 3.0) * rng.choice([-1, 1])
    ir = _lp(ir, 6000)
    ir /= np.abs(ir).sum()
    wet = np.stack([fftconvolve(mix[:, c], ir)[:n] for c in range(2)], axis=1)
    out = mix * 0.7 + wet * 9.0

    # fade, chuẩn hoá RMS ~ -18 dBFS, giới hạn đỉnh mềm
    fade = int(0.6 * SR)
    out[:fade] *= np.linspace(0, 1, fade)[:, None]
    out[-fade:] *= np.linspace(1, 0, fade)[:, None]
    out *= (10 ** (-18 / 20)) / (np.sqrt((out ** 2).mean()) + 1e-9)
    out = np.tanh(out * 1.3) / 1.3
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(out_path, SR, (np.clip(out, -0.98, 0.98) * 32767).astype(np.int16))
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--style", default="nha_may")
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--vehicles", action="store_true", help="thêm tiếng xe nâng/xe tải (mặc định tắt)")
    a = ap.parse_args()
    print("Tạp âm:", make_ambience(a.seconds, a.out, a.style, a.seed, a.vehicles))
