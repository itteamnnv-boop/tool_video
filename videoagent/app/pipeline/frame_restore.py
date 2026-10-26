"""Khoá khung hình — giữ nét chi tiết. Model video vẽ lại cả khung ở độ phân giải thấp nên chữ trên nhãn, bình luận, giao
diện, kệ hàng bị nhoè / vỡ. Sau khi có clip: so từng khung với ảnh khung đầu gốc → vùng gần như đứng yên lấy lại điểm ảnh
của ảnh gốc (nét gốc), vùng chuyển động (người nói, tim bay…) giữ của clip. Mặt nạ tính ở độ phân giải thấp (ít nhiễu), nới
rộng vùng chuyển động, làm mượt theo thời gian + làm mềm mép để không nhấp nháy / lộ đường ghép.
Chỉ dùng ffmpeg (không cần numpy), chạy trên máy, không tốn lượt model."""
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from .. import ffmpeg

THRESHOLD = 26  # chênh lệch (0–255) trên khung thu nhỏ: dưới mức này coi là "đứng yên"
MASK_DIV = 4  # tính mặt nạ trên khung thu nhỏ 1/4 (lọc nhiễu nén, nhanh)
GROW = 3  # số lần nới vùng chuyển động (mỗi lần ~4px khung gốc) — không cắt mép người / tay
SMOOTH = 5  # số khung làm mượt mặt nạ theo thời gian
LIVE_UI_BANDS = ((0.0, 0.12), (0.66, 1.0))  # livestream dọc: thanh trên (kênh, Follow, người xem) + bình luận / tim / thanh dưới
MAX_ZOOM = 0.25  # model phóng to khung đầu tối đa 25% (dò trong khoảng này)
MIN_ZOOM = 0.008  # dưới mức này coi như không phóng
MAX_FIT_ERROR = 60.0  # tổng sai số 3 kênh xám (0–765) sau khi khớp: lớn hơn = clip đã vẽ lại khung, không chỉnh
ASPECT_TOLERANCE = 0.03  # lệch tỉ lệ khung tối đa giữa ảnh gốc và clip (làm tròn kích thước của model)
MIX =":".join(f"{a}{b}=0.5" for a in "rgb" for b in "rgb")  # mọi kênh = (ΔR+ΔG+ΔB)/2


def _graph(w: int, h: int, mw: int, mh: int, smooth: int, grow_n: int, bands=()) -> str:
    """[0:v] = ảnh / clip do model vẽ, [1:v] = ảnh gốc → vùng khác biệt thật giữ của model, còn lại lấy ảnh gốc.
    bands = các dải ngang (từ, đến — tỉ lệ chiều cao) LUÔN lấy ảnh gốc (giao diện livestream: model hay tự vẽ thêm
    thanh bình luận / cuộn bình luận — không phải chuyển động mong muốn)."""
    grow = ",".join(["dilation"] * grow_n)
    keep = "+".join(f"between(Y/H,{a:.3f},{b:.3f})" for a, b in bands)
    fixed = f"geq=r='if({keep},0,r(X,Y))':g='if({keep},0,g(X,Y))':b='if({keep},0,b(X,Y))'," if bands else ""
    cut, held = f"if(gt(val,{THRESHOLD}),255,0)", "if(gt(val,0),255,0)"
    # so sánh trên khung ĐÃ thu nhỏ cả hai phía: độ nhoè / nén của clip biến mất, chỉ còn khác biệt thật (chuyển động)
    small = f"scale={mw}:{mh}:flags=area,gblur=sigma=1"
    # tmix + lut>0 = "đã chuyển động trong SMOOTH khung gần nhất" → giữ trọn của clip (không hụt mép, không nhấp nháy)
    timeline = f"tmix=frames={smooth},lut=c0='{held}':c1='{held}':c2='{held}'," if smooth > 1 else ""
    return (f"[0:v]scale={w}:{h}:flags=lanczos,setsar=1,format=gbrp,split=2[v1][v2];"
            f"[1:v]scale={w}:{h}:flags=lanczos,setsar=1,format=gbrp,split=2[b1][b2];"
            f"[v1]{small}[vs];[b1]{small}[bs];"
            # gộp chênh lệch 3 kênh vào cả 3 mặt phẳng (không dùng format=gray: gbrp→gray làm sai giá trị chênh lệch)
            f"[vs][bs]blend=all_mode=difference:shortest=1,colorchannelmixer={MIX},"
            f"lut=c0='{cut}':c1='{cut}':c2='{cut}',{grow},{timeline}{fixed}boxblur=2:1,"
            f"scale={w}:{h}:flags=bicubic[m];"
            f"[b2][v2][m]maskedmerge")


def _sizes(base: Path) -> tuple[int, int, int, int]:
    with Image.open(base) as im:
        w, h = im.size
    w, h = w - w % 2, h - h % 2
    return w, h, max(16, (w // MASK_DIV) // 2 * 2), max(16, (h // MASK_DIV) // 2 * 2)


def restore_image(edited: Path, base: Path, out: Path) -> bool:
    """Ảnh AI đã sửa (vd. ghép người dẫn vào layout) → `out`: chỗ AI thay đổi thật (người) giữ của AI, mọi chỗ còn lại
    lấy ĐÚNG điểm ảnh gốc (sản phẩm, chữ, giao diện không bị vẽ lại). False khi ảnh AI khác tỉ lệ (không ghép được)."""
    w, h, mw, mh = _sizes(base)
    with Image.open(edited) as im:
        ew, eh = im.size
    if abs(ew / eh - w / h) > ASPECT_TOLERANCE * (w / h):
        return False
    ffmpeg.run(["-i", edited, "-i", base, "-filter_complex", _graph(w, h, mw, mh, 1, GROW + 2) + ",format=rgb24[out]",
                "-map", "[out]", "-frames:v", "1", "-y", out])
    return True


def _fit_error(base: Image.Image, frame: Image.Image, zoom: float, x: float, y: float) -> float:
    sw, sh = frame.size
    crop = base.crop((x, y, x + sw / zoom, y + sh / zoom)).resize((sw, sh), Image.BILINEAR)
    return sum(ImageStat.Stat(ImageChops.difference(crop, frame)).mean)


def _search(base: Image.Image, frame: Image.Image, width: int, zooms, xs, ys) -> tuple[float, float, float, float]:
    """Tìm (sai số, zoom, x, y) nhỏ nhất trên ảnh thu nhỏ còn `width` px; xs / ys tính theo điểm ảnh của ảnh gốc."""
    k = width / base.width
    b = base.resize((width, round(base.height * k)), Image.BOX)
    f = frame.resize(b.size, Image.BOX)
    return min((_fit_error(b, f, z, x * k, y * k), z, x, y) for z in zooms for x in xs(k) for y in ys(k))


def estimate_zoom(frame: Path, base: Path) -> tuple[float, float, float, float]:
    """Model video hay phóng to / cắt khung đầu (Muse ~6%) → giao diện tràn ra ngoài. Trả (zoom, x, y, sai số): clip
    = vùng (x, y, W/zoom, H/zoom) của ảnh gốc phóng lên đủ khung. Dò thô trên ảnh 68px rồi tinh chỉnh trên 270px."""
    with Image.open(base) as b0, Image.open(frame) as f0:
        b, f = b0.convert("L"), f0.convert("L")
    span = MAX_ZOOM / (1 + MAX_ZOOM)  # phần ảnh gốc bị cắt tối đa ở mỗi chiều
    _, z, x, y = _search(b, f, 68, [1 + i / 100 for i in range(round(MAX_ZOOM * 100) + 1)],
                         lambda k: [i / k for i in range(round(b.width * k * span) + 1)],
                         lambda k: [i / k for i in range(round(b.height * k * span) + 1)])
    e, z, x, y = _search(b, f, 270, [z + i / 500 for i in range(-5, 6)],
                         lambda k: [max(0.0, x + i / k) for i in range(-4, 5)],
                         lambda k: [max(0.0, y + i / k) for i in range(-4, 5)])
    return z, x, y, e


def undo_zoom(clip: Path, base: Path) -> float | None:
    """Ghi đè `clip`: thu clip về đúng chỗ của nó trên ảnh gốc (phần mép bị cắt lấy từ ảnh gốc) → giao diện, chữ, sản
    phẩm khớp lại vị trí ảnh gốc. Trả zoom đã sửa; None khi clip không bị phóng (hoặc không đo chắc được)."""
    w, h, _, _ = _sizes(base)
    duration = ffmpeg.media_duration(clip)
    probes = []
    for i, ts in enumerate((0.1, max(0.2, duration / 2))):
        png = clip.with_name(f"{clip.stem}_probe{i}.png")
        ffmpeg.run(["-ss", f"{ts:.2f}", "-i", clip, "-frames:v", "1", "-vf", f"scale={w}:{h}", "-y", png])
        try:
            probes.append(estimate_zoom(png, base))
        finally:
            png.unlink(missing_ok=True)
    (z, x, y, e), (z2, x2, y2, _) = probes
    # zoom không đổi theo thời gian (máy đứng yên) + khớp tốt — không chắc thì không đụng clip
    if z < 1 + MIN_ZOOM or e > MAX_FIT_ERROR or abs(z - z2) > 0.01 or abs(x - x2) > w * 0.01 or abs(y - y2) > h * 0.01:
        return None
    cw, ch = round(w / z) // 2 * 2, round(h / z) // 2 * 2
    tmp = clip.with_name(clip.stem + "_fit.mp4")
    ffmpeg.run(["-i", clip, "-loop", "1", "-t", f"{duration:.3f}", "-i", base, "-filter_complex",
                f"[1:v]scale={w}:{h},setsar=1[bg];[0:v]scale={cw}:{ch}:flags=lanczos,setsar=1[fg];"
                f"[bg][fg]overlay=x={round(x)}:y={round(y)}:shortest=1,format=yuv420p[out]",
                "-map", "[out]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
                "-c:a", "copy", "-movflags", "+faststart", tmp])
    tmp.replace(clip)
    return z


def restore_static(clip: Path, base: Path, bands=()) -> bool:
    """Ghi đè `clip`: vùng đứng yên (và các dải `bands`) lấy từ ảnh `base` (khung đầu gốc), giữ tiếng của clip.
    False (không đụng clip) khi ảnh gốc khác tỉ lệ clip — model đã cắt / thêm viền, ghép sẽ méo hình."""
    w, h, mw, mh = _sizes(base)
    cw, ch = ffmpeg.video_size(clip)
    if abs(cw / ch - w / h) > ASPECT_TOLERANCE * (w / h):
        return False
    duration = ffmpeg.media_duration(clip)
    graph = _graph(w, h, mw, mh, SMOOTH, GROW, bands) + ",format=yuv420p[out]"
    tmp = clip.with_name(clip.stem + "_sharp.mp4")
    ffmpeg.run(["-i", clip, "-loop", "1", "-t", f"{duration:.3f}", "-i", base, "-filter_complex", graph,
                "-map", "[out]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
                "-c:a", "copy", "-movflags", "+faststart", tmp])
    tmp.replace(clip)
    return True
