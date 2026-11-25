---
name: video-mau-doi-nhan-vat
description: Phân tích một VIDEO MẪU (quảng cáo/TVC/livestream/TikTok dọc 9:16 có người dẫn nói tiếng Việt) rồi DỰNG LẠI Y HỆT — cùng bố cục cảnh, thời lượng từng cảnh, lời thoại, hành động, chuyển động máy quay, phụ đề nhiều tầng đúng mốc và kiểu chữ — CHỈ THAY NHÂN VẬT bằng người trong ảnh mới (giọng nói mới khớp khẩu hình). Trả về draft CapCut chỉnh sửa được + bản xem trước MP4. Quy trình tự động: tách cảnh + chép lời (faster-whisper) → đọc phụ đề trên khung → ảnh khung đầu thay người bằng Codex CLI → clip nói bằng Grok Imagine (Chrome) → ghép khớp mốc gốc bằng ffmpeg → draft bằng capcut-cli. Dùng khi người dùng gửi một video có sẵn và nói "làm lại video này", "dựng lại giống vậy", "phân tích video và làm tương tự", "đổi người mẫu/nhân vật trong video", "thay KOL/người dẫn khác", "remake video", "clone video mẫu", "giữ nguyên kịch bản chỉ đổi người" — kể cả khi họ không nói chữ "skill" hay "CapCut".
---

# Video mẫu → dựng lại, chỉ đổi nhân vật

Đầu vào: **video mẫu** + **ảnh nhân vật mới**. Đầu ra: video giống video mẫu đến từng cảnh, từng câu,
từng dòng phụ đề — chỉ khác người (mặt, tóc, giọng). Dự án thử nghiệm: `D:\CapCut\RemakeKinger_n26`
(video mẫu `canvas-n26.mp4`, 3 cảnh, 8,8s, phụ đề 3 tầng).

`$SKILL` = thư mục chứa file này. Chạy Python bằng `python -P` (không `-I`: PIL/faster-whisper nằm ở user
site-packages), đặt `PYTHONIOENCODING=utf-8`. Cần: ffmpeg/ffprobe, faster-whisper (model `medium` đã có cache),
Codex CLI đã đăng nhập, Claude in Chrome + tài khoản Grok, capcut-cli.

Nguyên tắc cốt lõi — **"giống hệt, chỉ đổi người"**:
- Giữ nguyên: số cảnh, mốc cắt, bố cục khung, bối cảnh, sản phẩm + nhãn, trang phục (trừ khi người dùng muốn đổi),
  hành động, chuyển động máy quay, lời thoại, phụ đề (chữ, mốc, tầng, màu, vị trí), nhịp nhạc.
- Thay: mặt/tóc/dáng người theo ảnh mới, **giọng nói** (giọng nhân vật cũ không được giữ lại ở bất kỳ cảnh nào).
- Không tự sửa nội dung quảng cáo. Thấy claim sai/nhạy cảm trong video mẫu → báo người dùng, không tự đổi.

## 0. Thu thập đầu vào (hỏi một lần, gọn)

1. **Video mẫu**: đường dẫn file (thường trong `Downloads`) hoặc link → tải về chỉ khi người dùng đồng ý.
2. **Ảnh nhân vật mới**: mặt rõ, chính diện, đủ sáng. Ảnh qua chat thường không tới được → nhờ chép vào
   `D:\CapCut\_input\nhan_vat\` rồi kiểm tra bằng `ls`.
3. **Đồng ý hình ảnh**: ảnh là người thật → hỏi xác nhận có sự đồng ý của người đó để làm video quảng cáo AI.
   Không có → đề nghị nhân vật AI hư cấu (Codex tạo chân dung trước, dùng làm ảnh nhân vật).
4. **Bản quyền video mẫu**: nếu video mẫu không phải của người dùng (video của thương hiệu/KOL khác) → nhắc rằng
   dựng lại y hệt nội dung/nhãn hiệu người khác có rủi ro; đề nghị đổi sản phẩm/thương hiệu sang của người dùng.
5. Tuỳ chọn: giọng (Nam/Bắc), trang phục mới, tên dự án. Mặc định: giữ trang phục, giọng nữ miền Nam.

Dùng AskUserQuestion cho câu hỏi có lựa chọn; người dùng thích được hỏi ít và thấy tiến độ.

## 1. Khởi tạo + phân tích video mẫu (chỉ một đoạn → cắt trước: `ffmpeg -ss <a> -to <b> -i mau.mp4 -c:v libx264 -crf 16 -c:a aac 00_input/mau_doan.mp4`)

```bash
mkdir -p "D:/CapCut/<TenDuAn>/00_input"
ffmpeg -v error -y -i "<ảnh nhân vật>" "D:/CapCut/<TenDuAn>/00_input/nhan_vat.png"
python -P "$SKILL/scripts/phan_tich_video.py" --video "<video mẫu>" --project "D:/CapCut/<TenDuAn>"
```
Ra `01_phan_tich/`: `phan_tich.json/.md` (cảnh + lời có mốc từng từ), `luoi_canh.png` (mỗi hàng 1 cảnh, 3 khung),
`luoi_phu_de_*.png` (khung mỗi 0,5s có mốc giây), `canh/<id>_{a,b,c}.png`; và khung sườn `02_kich_ban/du_an.json`.
- Cảnh bị tách thừa/thiếu → chạy lại với `--threshold 0.2` (nhạy hơn) / `0.4`, hoặc sửa tay `shots` trong du_an.json
  (start/end) — video có chuyển cảnh mờ dần thường cần sửa tay.
- Video dài (> 60s) → `--step 1` để lưới phụ đề gọn.

## 2. Đọc kỹ video mẫu (Read các ảnh lưới) → điền `du_an.json`

Xem `luoi_canh.png` và **mọi** `luoi_phu_de_*.png`. Cấu trúc file: `references/du_an_schema.md`. Với từng cảnh điền:
- `hinh` / `giong` theo bảng trong schema. Quy tắc quan trọng:
  - Video mẫu có **phụ đề/chữ dính cứng** (gần như luôn có) → mọi cảnh `hinh: "tao_moi"` (Codex xoá chữ khi dựng
    lại khung); `giu_goc` chỉ cho cảnh sạch chữ và không có người.
  - Cảnh không lộ mặt (cận sản phẩm, bàn tay chỉ) nhưng lời vẫn chạy → `giong: "giong_rieng"` + `giong_anh`
    (id cảnh lộ mặt) — nhân vật mới đọc lời đó trong một clip riêng, chỉ lấy tiếng.
- `mo_ta` (tiếng Anh): bối cảnh, đạo cụ, sản phẩm, trang phục, bố cục — đủ để Codex dựng lại nếu khung mẫu mờ.
- `hanh_dong` (tiếng Anh): chuyển động thực tế trong cảnh (so khung a→b→c: tay chỉ, giơ sản phẩm, gật đầu…).
- `camera`: tĩnh / zoom vào chậm / lia… (so khung a và c: vật to dần = push-in).
- `dialogue`: lời whisper **đã sửa** — whisper hay nghe sai tên riêng/từ hiếm ("Kinger" → "kênh giờ",
  "tươi tốt" → "tư tốt"). Đối chiếu với phụ đề trên khung + nhãn sản phẩm. Từ nào không chắc → hỏi người dùng
  (Claude không nghe được âm thanh). Số/điện thoại viết bằng CHỮ, đọc từng chữ số, số 5 là "năm" (không "lăm").
- `phu_de`: mỗi cụm phụ đề = 1 sự kiện `{t0, t1, dong:[{text, kieu}]}` — mốc theo giây video mẫu, đọc từ lưới
  0,5s; cần chính xác hơn thì trích thêm khung quanh chỗ đổi: `ffmpeg -ss <t> -i mau.mp4 -frames:v 1 x.png`.
  Ghi đúng chữ hoa/thường như trên màn hình. Kiểu chữ khác mặc định (dẫn/nhấn/IN HOA) → khai báo `phu_de_kieu`.
- Âm thanh: Claude không nghe được → đo xem giữa các câu có nhạc không:
  `ffmpeg -ss <khoảng lặng giữa 2 câu> -t 0.3 -i mau.mp4 -af volumedetect -f null -` (mean > −45 dB ≈ có nhạc/tạp âm),
  rồi hỏi người dùng muốn: không nhạc / file nhạc của họ (`nhac: "file"`) / tách nhạc gốc (`nhac: "tach_goc"`, bước 6).

Trình bày bảng phân tích (cảnh, mốc, lời, phụ đề, hinh/giong) cho người dùng duyệt trước khi tạo ảnh — nhất là
những từ đã sửa so với whisper.

## 2b. Storyboard nhân vật — BẮT BUỘC, làm ngay khi đã có ảnh nhân vật + trang phục

Một ảnh chính diện không đủ để AI giữ đúng người khi cảnh quay nghiêng, sau lưng, cận mặt hay chuyển động.
Vì vậy trước khi tạo khung đầu, dựng ảnh các góc cạnh của TỪNG nhân vật:
```bash
python -P "$SKILL/scripts/tao_sheet_nhan_vat.py" --project "D:/CapCut/<TenDuAn>"   # --print xem prompt
```
- Điền trước trong du_an.json (nhân vật trong `nhan_vat` hoặc `nhan_vats`): `trang_phuc` (trang phục trong video —
  sheet toàn thân mặc đúng bộ này), `toc` nếu kiểu tóc trong video khác ảnh (vd tóc búi cô dâu), `kinh: true` nếu
  đeo kính.
- Ra `00_input/sheet/<vai>_mat.png` (6 góc mặt: chính diện, 3/4 hai bên, nghiêng hai bên, cười) và
  `<vai>_toan_than.png` (5 góc toàn thân trong trang phục: trước, 3/4, nghiêng, sau lưng, 3/4 phải).
- **Kiểm tra** (Read từng sheet, đặt cạnh ảnh gốc): cùng một người ở mọi ô, không lẫn người khác, đúng kính/tóc/màu
  da, trang phục đúng. Sai → `--lam-lai --only <vai>` (có thể thêm mô tả vào `toc`/`trang_phuc`).
- **Gửi người dùng xem** sheet (SendUserFile) và chờ đồng ý trước khi sang bước 3 — đây là "bản gốc" của nhân vật
  cho toàn bộ video.
- `tao_anh.py` tự gửi kèm ảnh gốc + 2 sheet của mỗi nhân vật làm tham chiếu (thiếu sheet thì in cảnh báo).
- Khi tạo clip (Veo/Grok) có chế độ ảnh tham chiếu/thành phần, có thể đính kèm thêm sheet mặt.

## 3. Ảnh khung đầu thay nhân vật (Codex CLI)

```bash
python -P "$SKILL/scripts/tao_anh.py" --project "D:/CapCut/<TenDuAn>"        # --print để xem prompt + refs
```
Mỗi cảnh `tao_moi`: ảnh 1 = khung mẫu (`<id>_a.png` hoặc `shot["khung"]` — Veo/Grok chuyển động từ khung này),
rồi với từng nhân vật: ảnh gốc + sheet mặt + sheet toàn thân → `04_anh/<id>.png`. Prompt mặc định: dựng lại khung
y hệt, chỉ thay người (dùng sheet để đúng mặt ở góc máy của cảnh), xoá chữ/logo.
Video ngang (`width` > `height`) → ảnh 16:9; nhiều người → `nhan_vats` (xem schema).
Kiểm tra (ghép ngang khung mẫu | ảnh mới, Read): mặt giống ảnh nhân vật, nhất quán giữa các cảnh; nhãn sản phẩm
đúng chữ; không còn phụ đề; bố cục trùng khung mẫu. Hỏng → xoá file, chỉnh `image_prompt`/`mo_ta`, chạy lại.
Cảnh cận tay: tay/da phải hợp với nhân vật mới (màu da, móng, tay áo đúng trang phục).

## 4. Clip Grok Imagine (Chrome của người dùng)

```bash
python -P "$SKILL/scripts/grok_prompt.py" --project "D:/CapCut/<TenDuAn>"
```
In danh sách clip cần tạo: **clip hình** `<id>.mp4` (ảnh `04_anh/<id>.png`) và **clip giọng** `<id>_giong.mp4`
(ảnh của cảnh lộ mặt), kèm prompt và thời lượng (6s nếu cảnh ≤ 5,5s, ngược lại 10s). Làm theo
`references/grok_imagine_chrome.md` (đọc kỹ — nhiều bẫy: Cloudflare, tab nền đóng băng, giới hạn lượt, tải file).
- Thử clip đầu tiên, **nhờ người dùng nghe** (giọng, đọc đúng tên sản phẩm) rồi mới làm tiếp.
- Xin phép trước khi tải (tên file, nguồn assets.grok.com, dung lượng); mỗi file một tab.
- `python -P "$SKILL/scripts/thu_video.py" --project … --prefix <prefix>` → `05_video/`.
- Grok hết lượt → dựng trước với `--skip-missing` (cảnh thiếu tạm dùng cảnh gốc — có người cũ, chỉ để xem nhịp).

## 5. Dựng + xem trước

```bash
python -P "$SKILL/scripts/dung_draft.py" --project "D:/CapCut/<TenDuAn>"     # --no-compile: chỉ dựng đoạn + spec
python -P "$SKILL/scripts/xem_truoc.py" --project "D:/CapCut/<TenDuAn>"
```
`dung_draft.py` cho mỗi cảnh một đoạn chuẩn 1080x1920/30fps (`06_doan/`): lời mới đặt đúng chỗ lời gốc bắt đầu,
nói dài hơn → tăng tốc ≤ 1,3× (hình + tiếng cùng tốc độ để khớp miệng, giữ cao độ), vẫn dài → kéo dài cảnh và co
giãn phụ đề theo. Video mẫu không đúng 9:16 (vd 1080x1896) → tự phóng phủ + cắt mép. Rồi dựng draft CapCut:
track video, 1 track chữ cho mỗi tầng phụ đề (chữ CapCut gốc, sửa được; đậm/nghiêng/màu bằng text-ranges; hiệu ứng
xuất hiện fade-in/pop-up so le như mẫu), track nhạc nếu có. Draft cũ cùng tên → `.bakN` (không xoá).
Bảng in ra cho biết hệ số tăng tốc từng cảnh — cảnh x1.3 hoặc bị kéo dài thì lời Grok quá dài: rút gọn lời
(nếu người dùng đồng ý) hoặc tạo lại clip với "speaks fast".
`xem_truoc.py` ghép bản MP4 (phụ đề vẽ bằng font Windows — chỉ ước lượng) + `08_xem_truoc/luoi.png`.
**So sánh** lưới xem trước với `luoi_phu_de_*.png` của video mẫu: cùng cảnh ở cùng mốc, phụ đề cùng chỗ/cùng lúc.

## 6. Nhạc nền (khi cần)

- `nhac: "file"` + `nhac_file`: file của người dùng (lặp/cắt đúng độ dài, fade cuối).
- `nhac: "tach_goc"`: tách nhạc khỏi giọng của video mẫu bằng demucs — chỉ khi người dùng có quyền dùng nhạc đó.
  Cần cài (nặng ~2 GB, hỏi trước): `pip install demucs`. Rồi:
  ```bash
  ffmpeg -y -i "<video mẫu>" -ar 44100 -ac 2 03_nhac/mau.wav
  python -m demucs --two-stems=vocals -n htdemucs -o 03_nhac/demucs 03_nhac/mau.wav
  cp 03_nhac/demucs/htdemucs/mau/no_vocals.wav 03_nhac/nhac_goc_tach.wav
  ```
  Nhờ người dùng nghe: còn sót giọng cũ thì không dùng.

## 7. Trả kết quả

Gửi: đường dẫn draft (`%LOCALAPPDATA%\CapCut\User Data\Projects\com.lveditor.draft\<draft_name>`), bảng timeline
(cảnh, mốc mẫu → mốc mới, tốc độ, lời), file xem trước (SendUserFile), ảnh so sánh mẫu | mới. Lưu ý ngắn:
font chữ CapCut không đặt được qua CLI (chọn font serif nghiêng cho tầng nhấn nếu muốn giống hệt), nhờ nghe kiểm tra
giọng/tên sản phẩm, CapCut đang mở thì khởi động lại để thấy draft.

## Sự cố thường gặp
- Mọi file mới có thể bị hook GateGuard chặn lần đầu → nêu ngắn bên gọi/dữ liệu/lời yêu cầu rồi thử lại.
- faster-whisper lỗi `open() got an unexpected keyword argument 'metadata_errors'` (PyAV lệch bản) → đã xử lý:
  script tự đọc WAV bằng numpy.
- `codex exec -i a b "prompt"` → "No prompt provided": prompt phải đứng TRƯỚC `-i` (script đã làm đúng).
- Codex giữ lại phụ đề của khung mẫu → thêm vào `image_prompt` "absolutely no text anywhere"; hoặc dùng khung `_b`
  (`"khung": "01_phan_tich/canh/<id>_b.png"`) nếu khung a có chữ to.
- Mặt nhân vật lệch giữa các cảnh → tạo cảnh đẹp nhất trước, rồi thêm nó làm tham chiếu (sửa `image_prompt`: "same
  woman as in image 3") — chép ảnh vào `04_anh/` và thêm vào lệnh codex bằng tay nếu cần.
- Grok tự thêm nhạc/chữ → prompt đã có "No on-screen text, no music"; vẫn bị thì tạo lại clip.
- Draft không hiện trong CapCut → đóng hẳn CapCut rồi mở lại; vẫn không thấy → `capcut-cli register <draft> --apply`.
