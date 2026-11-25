---
name: tvc-livestream-capcut-muse
description: Tự động làm video TVC/quảng cáo dạng LIVESTREAM BÁN HÀNG dọc 9:16 (người mẫu nữ ngồi live giới thiệu sản phẩm, tự nói tiếng Việt bằng giọng gốc khớp khẩu hình, khung live động + bình luận + giỏ hàng, phụ đề nổi bật tô từ khoá, hiệu ứng sản phẩm động như huy hiệu giá, hộp quà, nhạc nền tự tạo) và trả về DRAFT CAPCUT có timeline chỉnh sửa được, kèm bản preview MP4. Đầu vào chỉ cần ý tưởng + link web sản phẩm + ảnh người mẫu + ảnh sản phẩm (+ yêu cầu thêm). Quy trình tự động gồm tìm ý tưởng web → kịch bản lời thoại → ảnh cảnh bằng Codex CLI (giữ mặt người mẫu + nhãn sản phẩm) → clip nói bằng Muse của Meta (muse.ai, qua muse-cli) → khung live → dựng draft bằng capcut-cli → preview. Bản này tạo clip nói bằng Muse (muse.ai) thay cho Grok — dùng khi người dùng nhắc Muse/muse.ai/Meta, hoặc Grok hết lượt. Dùng skill này khi người dùng nói "video livestream bán hàng", "TVC livestream", "cô gái live giới thiệu sản phẩm", "video quảng cáo kiểu live TikTok", "làm video bán hàng bằng AI từ ảnh người mẫu và sản phẩm", hoặc gửi ảnh người mẫu + ảnh sản phẩm và muốn ra video/timeline CapCut — kể cả khi họ không nói chữ "skill" hay "CapCut".
---

# TVC Livestream → CapCut (tự động, clip nói bằng Muse)

Biến **ý tưởng + link web + ảnh người mẫu + ảnh sản phẩm** thành một video livestream bán hàng
chân thực (~45–50 giây, 5 clip × 10s) và một **draft CapCut** sẵn sàng chỉnh/xuất.

Kết quả đã được người dùng duyệt ở dự án mẫu `D:\CapCut\KingerLivestream` (draft `KingerLivestream_GiongGoc`).
Những điều người dùng đã nói rõ là quan trọng — hãy giữ:
- Người dẫn phải **tự nói** (giọng gốc do Muse tạo, khớp khẩu hình), **hăng hái, nói nhanh, trôi chảy** — giọng TTS lồng tiếng bị chê là "chưa đạt".
- **Không** dùng dòng tiêu đề to ở đầu cảnh; chỉ phụ đề lời nói, **nổi bật** (chữ đậm, từ khoá vàng to hơn, nền tối, pop-up).
- Phụ đề là **chữ CapCut gốc** (sửa được), không render cứng.

Script ở `scripts/` (đường dẫn tuyệt đối: thư mục chứa file SKILL.md này, gọi là `$SKILL`).
Chạy Python bằng `python -P` (không dùng `-I`: các gói như PIL nằm ở user site-packages).
Trên Windows, đặt `PYTHONIOENCODING=utf-8` khi chạy script in tiếng Việt.

## 0. Thu thập đầu vào (hỏi một lần, gọn)

Cần có: (1) **ý tưởng/chủ đề**, (2) **link web** sản phẩm (tuỳ chọn nhưng nên có), (3) **ảnh người mẫu**,
(4) **ảnh sản phẩm**, (5) **yêu cầu thêm** (tuỳ chọn: tên shop, hotline, độ dài, giọng vùng miền…).

- **Chỉ có mã hoặc tên sản phẩm, không có link** → chủ động tra NNV MCP ngay, không hỏi lại link:
  `find` trên `chatbot.catalog_products` với
  `{"$or":[{"productCode":"<MÃ>"},{"variants.sku":"<MÃ>"},{"legacySnapshot.PRODUCT_CODE":"<MÃ>"},{"name":{"$regex":"<tên>","$options":"i"}}]}`
  (tên: bỏ dấu phụ không chắc thì dùng lớp ký tự, vd `m[ií]t`; kết quả tối đa 10/lần — thu hẹp regex nếu đủ 10).
  Field cần đọc: `name`, `productCode`, `status`, `formColor` (dạng/màu, vd "Gel / Đen"), `type`, `benefits`,
  `ingredients`, `usageInstruction`, `mainCrops`, `stages`, `variants[].unit` (quy cách), `variants[].prices`
  (`priceList` "default" = giá bán, "compare_at" = giá gốc), `legacySnapshot` (FORM_COLOR, KEYWORDS, COMPANY).
  Dự phòng: `chatbot.businessaiproducts` (`name`, `productCode`, `priceText`). Ưu tiên bản ghi `status: active`.
  Nhiều bản ghi khớp → liệt kê (tên, mã, giá, quy cách) và hỏi người dùng chọn. Không thấy → hỏi người dùng.
  Ảnh sản phẩm: nếu người dùng không gửi ảnh, dùng `variants[].thumbnail`/`gallery` (link Google Drive
  thumbnail) — tải về `00_input/` sau khi người dùng đồng ý; vẫn đọc nhãn trên ảnh để đối chiếu.

- Ảnh thường **không đến được** qua chat. Tạo sẵn `D:\CapCut\_input\nguoi_mau\` và `D:\CapCut\_input\san_pham\`
  rồi nhờ người dùng chép ảnh vào (hoặc đưa đường dẫn). Kiểm tra bằng `ls` — đừng tin "đã chép" khi thư mục trống.
- **Đồng ý hình ảnh**: ảnh người mẫu là người thật → hỏi xác nhận người dùng có sự đồng ý của người đó để làm
  video quảng cáo AI. Không có → đề nghị dùng người mẫu AI hư cấu (Codex tạo, bỏ `ref_nguoi_mau`).
- Thiếu gì thì dùng mặc định hợp lý, không hỏi dồn: giọng nữ miền Nam, ~5 clip × 10s, tên shop lấy theo
  thương hiệu trên nhãn, hotline lấy trên nhãn/web.

Dùng AskUserQuestion cho các câu hỏi có lựa chọn; người dùng thích được hỏi ít và thấy tiến độ.

## 1. Khởi tạo dự án

```bash
python -P "$SKILL/scripts/init_project.py" --root "D:/CapCut" --name <TenDuAnKhongDau> \
  --model "<ảnh người mẫu>" --product "<ảnh sản phẩm>"
```
Tạo cây thư mục chuẩn, chuyển ảnh sang PNG (`00_input/nguoi_mau.png`, `san_pham.png`), chép ảnh tham chiếu
cho Codex, và tạo `02_kich_ban/du_an.json` mẫu. Cấu trúc file dự án: `references/du_an_schema.md`.

## 2. Đọc sản phẩm + lấy ý tưởng từ web

- **Tra NNV MCP trước tiên (bắt buộc)** — cơ sở dữ liệu sản phẩm nội bộ của công ty (connector claude.ai
  "NNV MCP"; công cụ `list_databases`, `list_collections`, `sample_schema`, `find`, `aggregate`). Cách tra:
  `list_databases` → `list_collections` → `sample_schema` để biết tên field → `find` theo tên sản phẩm
  (regex không phân biệt hoa thường, thử cả tên ngắn như "Mít Đại Gia"). Phải xác nhận đủ **5 yếu tố**:
  1. **Tên** sản phẩm chính xác (đúng chữ, đúng số: "Kinger 2", không phải "Kinger II").
  2. **Giá** bán hiện hành + đơn vị (đ/xô, đ/chai, đ/bao) và quy cách (22 kg, 1 lít…).
  3. **Công dụng** chính (giai đoạn dùng, cây trồng) — chỉ nói đúng những gì có trong dữ liệu.
  4. **Dạng** sản phẩm: lỏng / bột / hạt / viên / sệt…, đóng xô, chai hay bao.
  5. **Chất phân**: loại phân (vi lượng, trung lượng, NPK, hữu cơ, hữu cơ vi sinh, sinh học…) và thành phần chính.
  Ghi bảng 5 yếu tố vào `01_y_tuong/y_tuong.md`, cột nguồn: NNV MCP / nhãn / web. Lưu vào `du_an.json` khoá
  `thong_tin_sp` ({ten, gia, cong_dung, dang, chat_phan, nguon}). **Nguồn ưu tiên: NNV MCP > nhãn > web.**
  Khi các nguồn lệch nhau (vd giá trên web khác NNV), dùng NNV và báo người dùng chỗ lệch trước khi viết kịch bản.
  Nếu NNV MCP không phản hồi hoặc không có sản phẩm: thử lại 2–3 lần, rồi **hỏi người dùng** xác nhận 5 yếu tố —
  không tự đoán giá/chất phân.
- Kịch bản, phụ đề, huy hiệu giá, thẻ công dụng phải khớp bảng 5 yếu tố; sau bước 3 đối chiếu lại một lượt.
- **Xem ảnh sản phẩm** (Read), phóng to nhãn bằng ffmpeg crop để đọc: tên, thành phần, công dụng, cách dùng,
  liều lượng, hotline, slogan. Đây là nguồn claim duy nhất được dùng.
- **WebFetch link web** người dùng đưa + **WebSearch** 1–2 truy vấn: nỗi đau khách hàng của ngành hàng, hook
  quảng cáo video ngắn. Ghi `01_y_tuong/y_tuong.md` kèm nguồn (URL).
- Quy tắc nội dung: chỉ dùng công dụng có trên nhãn/web chính thức, dùng từ "hỗ trợ"; **không bịa số liệu**,
  không bịa lời chứng thực khách hàng. Bình luận giả lập trên khung live chỉ là câu hỏi/chào hỏi/đặt hàng trung tính.

## 3. Viết kịch bản lời thoại → `du_an.json`

5 clip mặc định (10s/clip, ~22–30 từ tiếng Việt mỗi clip — nhiều hơn sẽ bị nói vội/cắt):
1. Chào live + hook ("Chào cả nhà đang xem live nha! …")
2. Giới thiệu sản phẩm (tên, loại, xuất xứ) — người mẫu giơ sản phẩm khoe nhãn
3. Mở/trải nghiệm sản phẩm (mở nắp, xem chất bên trong, công dụng chính)
4. Cách dùng (liều lượng, thời điểm)
5. Lợi ích + CTA (bấm giỏ hàng / gọi hotline)

Mỗi clip điền: `image_prompt` (ảnh cảnh), `grok_action` (hành động), `dialogue` (lời nói — **số viết bằng chữ**
để Muse đọc đúng: "không chín bốn bốn, hai mươi…"), `display` (phụ đề hiển thị — **số viết bằng chữ số**:
"0944.20.20.15", "1 lít"), `comments` (2–3 bình luận). Điền `keywords` (từ khoá tô vàng) và `overlay`.
Mẫu prompt: `references/prompts.md`.
**Đọc số điện thoại/mã số**: đọc TỪNG CHỮ SỐ, số 5 luôn là **"năm"** (không dùng "lăm"), số 1 là "một", 0 là "không"
— vd 0944.20.20.15 → "không chín bốn bốn, hai không, hai không, một năm" (người dùng sửa 2026-11-19: "một lăm" là sai).
"lăm"/"mốt" chỉ dùng trong số đếm bình thường (vd "hai mươi lăm ký"), không dùng khi đọc từng chữ số.

**Bối cảnh MẶC ĐỊNH (người dùng không mô tả)**: người mẫu **đứng** giới thiệu sản phẩm trong **nhà máy sản xuất
phân bón** đang hoạt động — **rất nhiều công nhân** (áo xanh, mũ bảo hộ vàng) đang làm việc ở hậu cảnh, dây chuyền
chiết rót xô trên băng chuyền inox, bồn trộn, xe nâng, và **rất nhiều sản phẩm** (pallet và chồng xô/chai cùng
nhãn) xếp quanh người mẫu. Dùng đoạn "Bối cảnh nhà máy" trong `references/prompts.md` cho `image_prompt` của mọi
clip để các cảnh nhất quán. Chỉ đổi bối cảnh (studio, vườn, cửa hàng…) khi người dùng mô tả cảnh khác.
Trang phục người mẫu ghi rõ và giống hệt nhau ở mọi clip; giữ thanh lịch, kín đáo.

**Giá + ưu đãi**: khi người dùng nhấn mạnh giá/khuyến mãi, dành riêng 1 clip cho giá + ưu đãi (thay clip cách dùng),
ghi giá vào `overlay.product_line2` (vd "650.000đ/xô") và ưu đãi vào `overlay.product_line3` (vd "Mua 5 tặng 1");
tên shop ngắn (≤ 14 ký tự) để không bị cắt. Giá lấy đúng từ web/nhãn; ưu đãi không có trên web thì chỉ dùng khi
người dùng tự đưa ra, và ghi chú điều đó trong `01_y_tuong/y_tuong.md`.

**Hiệu ứng (`fx`)** — điền cho từng clip theo bộ mặc định (chi tiết từng loại: `references/du_an_schema.md`):
| Clip | Hiệu ứng mặc định |
|---|---|
| 1 chào live | `react` (emoji bay) khi nói câu hook |
| 2 giới thiệu | `reveal` lúc giơ sản phẩm (`at` ≈ 0.5) + `chips` 3 thông số trên nhãn (`on` = tên loại phân) |
| 3 mở sản phẩm | `reveal` lúc mở nắp/múc + `callout` chỉ vào chất bên trong + `chips` 3 công dụng |
| giá/ưu đãi | `price` (giá + dải ưu đãi) + `gift` khi nói "tặng" + `react` |
| CTA | `pointer` khi nói "giỏ hàng" + `react` khi nói hotline |
Chữ trên thẻ/chú thích chỉ lấy từ nhãn, web chính thức hoặc mô tả của người dùng. `on` dùng từ khoá nằm trọn
trong 1 dòng phụ đề. Toạ độ x,y điền tạm, căn lại ở bước 7 khi đã có clip.

## 4. Tạo ảnh cảnh bằng Codex CLI

```bash
python -P "$SKILL/scripts/gen_images.py" --project "D:/CapCut/<TenDuAn>"
```
Chạy song song `codex exec` (đăng nhập ChatGPT, tính năng image_generation), dùng 2 ảnh tham chiếu
(người mẫu + sản phẩm), ra `04_anh/codex/<clip_id>.png` 1024x1536. Bỏ qua ảnh đã có; chạy lại để tạo ảnh thiếu.
Sau đó ghép lưới ảnh nhỏ bằng ffmpeg và **xem** để kiểm tra mặt người mẫu nhất quán và nhãn rõ chữ;
ảnh nào hỏng thì xoá file và chạy lại script.

## 5. Tạo clip nói bằng Muse (muse.ai của Meta, qua muse-cli — không cần trình duyệt)

```bash
python -P "$SKILL/scripts/muse_video.py" --project "D:/CapCut/<TenDuAn>" --print          # xem prompt
python -P "$SKILL/scripts/muse_video.py" --project "D:/CapCut/<TenDuAn>" --clip v1        # thử 1 clip
python -P "$SKILL/scripts/muse_video.py" --project "D:/CapCut/<TenDuAn>"                  # các clip còn thiếu
```
Chi tiết, cách đăng nhập và bẫy: `references/muse_video.md`. Tóm tắt:
- Kiểm tra trước: `python -P -m muse_cli status` in ra `vm_id` = đã đăng nhập. Lỗi `auth error`/không có cookie →
  nhờ người dùng đăng nhập muse.ai trong Chrome rồi làm theo mục Auth của skill muse-cli (không tự đăng nhập hộ).
  Chú ý: lệnh `muse` là Muse Code (trợ lý lập trình) — KHÔNG phải công cụ này; dùng `python -m muse_cli`.
- Script tự: tạo **side chat riêng** "TVC <tên dự án>" (ghi `muse_thread` vào du_an.json) → đẩy ảnh cảnh lên máy ảo
  Muse (`/workspace/tvc_uploads/<dự án>/<id>.jpg`) → gửi prompt image-to-video (10s, dọc 9:16, tự nói đúng nguyên văn
  `dialogue`, không nhạc/phụ đề) → chờ (mặc định tối đa 900s/clip) → tải về `05_grok_video/<id>.mp4`
  (giữ tên thư mục cũ để build_draft dùng chung) → in kích thước, thời lượng, có tiếng hay không.
- Chạy nền (`run_in_background`) vì mỗi clip mất vài phút; các clip chạy **tuần tự**.
- Thử 1 clip đầu và **nhờ người dùng nghe** (Claude không nghe được âm thanh) trước khi làm 4 clip còn lại.
  Không đạt → sửa `grok_action`/`dialogue`/`voice_style` rồi chạy lại `--clip v1` (tự ghi đè).
- Kiểm tra mỗi clip: dọc (cao > rộng), ~10s, **có tiếng**; trích 1 khung hình xem mặt + nhãn. Muse trả khung ngang
  hoặc không có tiếng → chạy lại clip đó; vẫn sai → xem `muse_cli history --thread <muse_thread>` để đọc Muse nói gì.
- Muse báo hết lượt/giới hạn → dừng, báo người dùng; hỏi dựng trước với clip đã có (`build_draft.py … --skip-missing`).

## 6. Khung livestream (ảnh tĩnh — dự phòng; bản động dựng ở bước 7 bằng Remotion)

```bash
python -P "$SKILL/scripts/tao_overlay.py" --project "D:/CapCut/<TenDuAn>"
```
Tạo PNG trong suốt 1080x1920: thanh shop (avatar cắt từ ảnh người mẫu, "+ Theo dõi"), LIVE + số người xem,
tim, thẻ giỏ hàng (ảnh sản phẩm, tên, hotline, MUA NGAY), ô bình luận; và ảnh bình luận theo từng clip.
**Khung live kiểu chung — không dùng logo/giao diện TikTok** (tránh vấn đề thương hiệu khi chạy quảng cáo).
Xem thử bằng cách chồng lên nền màu và Read ảnh.

## 7. Dựng draft CapCut

```bash
python -P "$SKILL/scripts/build_draft.py" --project "D:/CapCut/<TenDuAn>" --remotion --music --ambience
```

**Giọng nói nhanh, dứt khoát (người dùng yêu cầu 2026-11-19)**: prompt clip nói ghi "very fast, crisp and decisive,
short punchy delivery, no drawn-out vowels, no pauses". Sau khi tải clip, **tăng tốc 1,15×** cả hình lẫn tiếng (giữ
khớp miệng, giữ cao độ) — bản gốc cất ở `05_grok_video_goc/`:
`ffmpeg -i goc/vN.mp4 -filter_complex "[0:v]setpts=PTS/1.15[v];[0:a]atempo=1.15[a]" -map "[v]" -map "[a]" -c:v libx264 -crf 16 -c:a aac 05_grok_video/vN.mp4`
(ghi `"toc_do_noi": 1.15` vào du_an.json; người dùng muốn nhanh hơn nữa → 1.2–1.25).

**Tạp âm nền nhà máy (`--ambience`, hoặc tự bật khi du_an.json có mục `"ambience"`)** — mặc định BẬT cho bối cảnh nhà máy:
`scripts/tao_tap_am.py` tổng hợp tạp âm GỐC (numpy/scipy, không dùng file có bản quyền): máy ù 50 Hz, băng tải
lách cách, xì hơi khí nén, xe nâng chạy ngang + bíp lùi, va kim loại, vang xưởng. Thêm track audio `tap_am`
(volume 0.25 ≈ −30 dBFS, dưới giọng). Cấu hình: `"ambience": {"style": "boc_xep", "seed": 3, "volume": 0.35, "vehicles": false}`
(mặc định **boc_xep** = tiếng bốc xếp hàng liên tục; người dùng KHÔNG muốn tiếng xe chạy — chỉ bật `vehicles` khi được yêu cầu);
đổi `seed` để ra bản khác, `--no-ambience` để tắt. render_preview tự trộn cả nhạc nền và tạp âm.

**Nhạc nền tự tạo (`--music`, hoặc tự bật khi du_an.json có mục `"music"`)**: `scripts/tao_nhac_nen.py` tổng hợp
một bản nhạc GỐC bằng numpy/scipy (không dùng nhạc có bản quyền) dài đúng timeline: kick 4/4 có sidechain "nhún",
clap, hi-hat, bass nảy, hợp âm stab, pad, giai điệu marimba theo `seed`; vòng I–V–vi–IV; fade in/out.
Thêm track audio `nhac_nen` (mặc định volume 0.15 ≈ thấp hơn giọng ~15 dB). Tuỳ biến trong du_an.json:
`"music": {"style": "upbeat"|"chill", "bpm": 112, "key": "G", "seed": 7, "volume": 0.15}` — đổi `seed` để ra bài khác,
`chill` cho nhịp chậm nhẹ nhàng. Claude không nghe được âm thanh → luôn nhờ người dùng nghe preview và chỉnh.
Khi người dùng muốn "đổi nhạc": tạo 4 bản mẫu 15s khác nhau bằng
`tao_nhac_nen.py --out 03_nhac/mau/<ten>.wav --seconds 15 --style … --bpm … --key … --seed …`
(gợi ý: A chill 92/C/3, B chill 84/A/11, C upbeat 104/D/21, D upbeat 124/F/5), gửi bằng SendUserFile, hỏi chọn,
ghi lựa chọn vào `music` trong du_an.json rồi chạy lại build_draft — khung live động được dùng lại (không render
Remotion lại) khi đã có và khớp độ dài; `--rerender` để buộc render lại.
Mặc định đã duyệt (2026-11-18): **dong_luc 124 BPM, giọng C, seed 18** — `init_project.py` ghi sẵn vào du_an.json.
Kiểu có sẵn: `upbeat`, `chill`, `dong_luc`, `shopping` (người dùng từng chê `shopping`).

**Khung live ĐỘNG bằng Remotion (mặc định dùng `--remotion`)**: `scripts/remotion_overlay.py` render composition
`LiveOverlay` (template ở `assets/remotion-live-overlay`, project dùng chung `D:/CapCut/_remotion/live-overlay`,
tự `npm install` lần đầu) theo đúng mốc thời gian các clip: tim bay liên tục, bình luận của từng clip trượt lên,
LIVE nhấp nháy, số người xem tăng dần, giỏ hàng nảy + nút MUA NGAY loé sáng, "… vừa tham gia" luân phiên.
Xuất video trong suốt **ProRes 4444** (`04_anh/overlay/khung_live_dong.mov`, ~10 MB/giây) và thay 2 track ảnh tĩnh
bằng 1 track `khung_live_dong`. Phụ đề vẫn là chữ CapCut gốc (sửa được).
- Bỏ `--remotion` để dùng khung live ảnh tĩnh (nhẹ, chắc chắn hiển thị) — dùng khi Node/Remotion lỗi, máy yếu,
  hoặc CapCut không hiện được kênh trong suốt của file .mov. `--overlay-format webm` cho bản VP9 alpha rất nhẹ.
- Giấy phép Remotion: miễn phí cho cá nhân/nhóm <= 3 người; công ty lớn hơn cần license → đặt `REMOTION_LICENSE_KEY`
  (script tự truyền `--license-key`, nếu không có thì render `--is-production=false`). Nhắc người dùng một lần.
- Muốn chỉnh hiệu ứng: sửa `assets/remotion-live-overlay/src/LiveOverlay.tsx` (theo skill `remotion-markup`),
  xem trước bằng `npx remotion studio` trong project dùng chung (skill `remotion-studio`).
Script tự: đo khoảng có tiếng nói trong từng clip (`capcut-cli detect-silence`) → cắt khoảng lặng đầu/cuối →
nối các clip liền nhau (cắt thẳng, giữ âm thanh gốc volume 1) → phủ khung live + bình luận → phụ đề chia theo
dấu câu, **bắt dính ranh giới vào chỗ ngắt hơi** → tô từ khoá (vàng, to hơn) bằng text-ranges, nền tối, viền →
`capcut compile` vào thư viện draft (bản cũ cùng tên được đổi thành `.bakN`, không xoá) → `lint --fix` →
hiệu ứng **pop-up** cho từng dòng phụ đề. In ra bảng timeline và kết quả lint.
- CapCut đang mở → script tự thêm `--force-write` (draft mới, an toàn); nhắc người dùng khởi động lại CapCut.

**Hiệu ứng sản phẩm (`"fx"` trong từng clip của du_an.json)** — `at` = giây trong clip Muse gốc, `x`,`y` = toạ độ khung 1080x1920:
- `{"type": "reveal", "at": 0.5, "x": 500, "y": 1000}`: khi sản phẩm xuất hiện — chớp sáng, tia sáng vàng xoay, 2 vòng sóng,
  tia lấp lánh bung ra + lấp lánh quanh sản phẩm; video tự **zoom punch** 12% (tắt bằng `"zoom": false`).
- `{"type": "price", "at": 0.35, "x": 860, "y": 560, "scale": 0.72, "pre": "GIÁ CHỈ", "text": "650.000đ", "sub": "MUA 5 TẶNG 1"}`:
  huy hiệu ngôi sao đỏ ghi giá + dải ưu đãi có vệt sáng + pháo giấy, giữ đến hết clip. Đặt chỗ trống, không che mặt/phụ đề.
- Thay "at" bằng "on": "từ khoá" để hiệu ứng bắt đầu đúng lúc dòng phụ đề chứa từ khoá hiện ra (+ "delay"); từ khoá phải nằm trọn trong 1 dòng phụ đề.
- {"type": "chips", "on": "...", "x": 560, "y": 190, "items": [{"icon": "🌿", "text": "Hữu cơ 50%"}]}: thẻ thông tin trượt vào lần lượt (x = mép phải).
- {"type": "callout", "on": "đen sệt", "x", "y" (điểm chỉ), "bx", "by" (bong bóng), "text", "dur"}: chú thích + nét đứt chỉ vào sản phẩm.
- {"type": "gift", "on": "tặng", "x", "y", "text": "+1 XÔ"}: hộp quà bật ra + tim/sao bung.
- {"type": "pointer", "on": "giỏ hàng", "x", "y"}: bàn tay 👇 nhấp nhô chỉ xuống giỏ hàng đến hết clip.
- {"type": "react", "on": "...", "x", "y", "items": ["🔥","👍"]}: emoji cảm xúc bay lên.
- Tự động: ánh sáng mở màn + chớp/vệt sáng ở mỗi lần chuyển clip.
**Căn vị trí hiệu ứng**: trích 1 khung hình mỗi clip (`ffmpeg -ss 1 -i 05_grok_video/<id>.mp4 -frames:v 1`), quy đổi
sang khung 1080x1920, chọn x,y để tránh: mặt người mẫu, phụ đề (y ≈ 1100–1250), bình luận (trái dưới, y > 1380),
giỏ hàng (phải dưới, x > 690, y > 1360), tim bay (x ≈ 975). Sau khi dựng, mốc thời gian từng hiệu ứng có trong
`D:/CapCut/_remotion/live-overlay/out/<name>_props.json` → trích khung tại các mốc đó để kiểm tra.
Cảnh báo `! fx … không thấy '<từ khoá>'` = từ khoá bị ngắt sang 2 dòng phụ đề → đổi từ khoá khác (+ `delay`).
Code ở `assets/remotion-live-overlay/src/ProductFx.tsx`. Chọn x,y bằng cách xem khung hình clip; kiểm tra lại trên preview.

## 8. Preview + kiểm tra

```bash
python -P "$SKILL/scripts/render_preview.py" --project "D:/CapCut/<TenDuAn>"
```
(`capcut render` hỏng với ffmpeg 9, nên dùng script này.) Trích 5 khung hình bằng ffmpeg, ghép ngang, **xem**:
phụ đề đúng chữ (số hotline không bị cắt), không đè mặt, khung live đúng. Gửi MP4 bằng SendUserFile (display render).

## 9. Trả kết quả

Gửi người dùng: đường dẫn draft (`%LOCALAPPDATA%\CapCut\User Data\Projects\com.lveditor.draft\<draft_name>`),
**bảng timeline** (#, thời gian, lời thoại), file preview, và lưu ý ngắn: bình luận/số người xem là dàn dựng;
phụ đề chia ước lượng (có thể dùng Auto captions của CapCut để khớp từng chữ); nhờ nghe kiểm tra Muse đọc
đúng tên sản phẩm/số; có thể thêm nhạc nền nhỏ trong CapCut. Hỏi người dùng mở CapCut kiểm tra.

## Sự cố thường gặp
- Muse báo hết lượt/giới hạn giữa chừng → dựng trước với các clip đã có: `build_draft.py … --skip-missing`;
  tạo clip còn thiếu khi hết giới hạn rồi chạy lại build_draft (không cần `--skip-missing`).
- `codex exec -i a b "prompt"` → lỗi "No prompt provided": `-i` nuốt mọi tham số sau nó; **prompt phải đứng trước `-i`**.
- edge-tts/Muse/Wikimedia đôi khi lỗi tạm thời → thử lại có giãn cách, đừng đổi nội dung.
- Phụ đề số điện thoại bị ngắt ở dấu chấm → đã xử lý trong build_draft (chỉ ngắt ở dấu câu có khoảng trắng).
- `capcut text-anim` báo "Segment not found …\r" → ID dính CR; script đã strip.
- Lint "caption-overlap 1ms" do làm tròn → `lint --fix` (script tự chạy).
- Mọi bước tạo file mới có thể bị hook GateGuard yêu cầu nêu "facts" — nêu ngắn gọn rồi thử lại.
