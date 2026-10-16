# VideoAgent — tạo video ngắn bằng AI (Python)

App desktop Windows: nhập ý tưởng → chọn thể loại & template → AI viết kịch bản → dựng hình từ template HTML/CSS
→ giọng đọc edge-tts → nhạc nền, SFX, phụ đề karaoke → xuất MP4 và lưu vào thư viện.

## Cài đặt & chạy

```powershell
cd videoagent
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

Lần đầu dựng hình, app tự tải Chromium cho Playwright (khoảng 150 MB). ffmpeg có sẵn qua `imageio-ffmpeg`, không cần cài riêng.
Cần internet cho edge-tts, Gemini và font Google.

Biến môi trường:
- `VIDEOAGENT_DEBUG=1`: bật DevTools trong cửa sổ và log mức debug.
- `VIDEOAGENT_DEV=1`: bỏ qua license.

## Profile trình duyệt (sidebar → Profile trình duyệt)

Mỗi profile là một Chrome riêng, có cookie và tài khoản đăng nhập riêng. Dùng profile khi mỗi model (Gemini, Grok, ChatGPT, Dola) cần một tài khoản khác, hoặc khi muốn nhiều tài khoản của cùng một model chạy song song.

1. **Thêm profile:** đặt tên (VD: "Grok – tài khoản 2"), chọn model dùng profile này, và chọn trình duyệt (Chrome, Edge hoặc Chromium; "Theo Cài đặt chung" dùng trình duyệt trong Cài đặt).
2. **Đăng nhập:** bấm **Đăng nhập** cạnh từng model trong thẻ profile. Đăng nhập tài khoản trong cửa sổ vừa mở, rồi đóng cửa sổ đó.
3. **Khi tạo video/ảnh**, ô chọn profile cạnh "Hiện Chrome" có 2 lựa chọn:
   - **Tự chọn profile rảnh** (mặc định): app lấy profile rảnh đầu tiên trong các profile gán cho model đó. Nếu tất cả đang bận, tác vụ chờ.
   - **Một profile cụ thể**: tác vụ luôn dùng đúng tài khoản đó.

Ghi chú:
- Profile **Mặc định** dùng lại thư mục cũ, nên các phiên đăng nhập đã có vẫn giữ nguyên. Profile này không xoá được.
- Một profile chỉ mở được bởi một Chrome tại một thời điểm. Vì vậy số tác vụ chạy song song trên một model tối đa bằng số profile gán cho model đó. Ô thống kê ở đầu trang cho biết con số này.
- Xoá profile sẽ xoá luôn cookie và phiên đăng nhập của profile đó khỏi máy.
- Dữ liệu lưu ở `browser_profiles.json` và thư mục `browser-profiles/<id>` trong thư mục dữ liệu của app.

## Chạy nhiều tác vụ song song

Bấm **Tạo video →** hoặc **Tạo ảnh →** nhiều lần: mỗi lần thêm một tác vụ vào hàng đợi, không cần chờ tác vụ trước xong.

- **Số tác vụ chạy cùng lúc** chỉnh trong Cài đặt: *Số video tạo song song* và *Số tác vụ ảnh song song* (mặc định 2). Tác vụ vượt quá giới hạn sẽ ở trạng thái **Đang chờ**.
- **Hàng đợi tác vụ** nằm ở tab Tiến trình:
  - mỗi tác vụ có thanh % riêng và nút ■ để dừng riêng tác vụ đó;
  - bấm vào một tác vụ để xem nhật ký và tiến trình của nó;
  - có nút **Dừng tất cả** và **Xoá tác vụ đã xong**.
- Tác vụ dùng trình duyệt còn bị giới hạn bởi số profile rảnh (xem mục trên). Tác vụ dùng API (OpenAI, Gemini API) hoặc Offline thì chỉ bị giới hạn bởi số luồng.
- Mỗi luồng tự mở Chrome, ffmpeg và edge-tts riêng, nên chạy nhiều luồng sẽ tốn CPU/RAM hơn. Máy yếu nên để 1–2 luồng.

## Provider AI

| Provider | Cách dùng |
|---|---|
| Gemini Browser (free) | Bấm **Đăng nhập**, đăng nhập Google trong cửa sổ Chrome/Edge vừa mở, rồi đóng cửa sổ đó. Profile lưu riêng cho app. Tích **Hiện Chrome** nếu muốn xem trình duyệt khi AI đang chạy. |
| Grok Browser (free) | Chọn Grok Browser, bấm **Đăng nhập**, đăng nhập grok.com (tài khoản X/xAI), rồi đóng cửa sổ. grok.com chặn trình duyệt headless (Cloudflare), nên khi tắt "Hiện Chrome" app vẫn mở cửa sổ thật nhưng đặt ra ngoài màn hình. |
| Gemini API | Nhập API key ở ô Provider hoặc trong Cài đặt. |
| Offline | Không gọi AI, dùng kịch bản dựng sẵn để thử pipeline. |

Selector của từng trang có thể thay đổi theo thời gian;
khi đó sửa `SITES` trong `app/llm/browser_chat.py`. Thêm một trang chat khác cũng làm ở đó, bằng một mục `ChatSite` mới
và một `<option value="<site>_browser">` trong `ui/index.html`.

## Template video AI (Grok hoặc Gemini Veo)

Template loại `ai_video` không dựng hình bằng HTML. Thay vào đó, app gửi prompt cho AI tạo video. Mọi template dùng được với cả 3 engine.
Engine được chọn theo **Provider AI** đang dùng:

| Provider AI | Engine | Thời lượng | Độ phân giải | Ảnh tham chiếu |
|---|---|---|---|---|
| Grok Browser | Grok Imagine (grok.com/imagine) | 6/10/15s | 480p/720p/1080p | tối đa 10 |
| Gemini Browser · **Veo** (mặc định) | Công cụ "Tạo video" (Veo) trong gemini.google.com. Nếu tài khoản không có Veo (cần gói Google AI Pro/Ultra), app **tự chuyển sang video thông thường** | 8s | 720p | 1 |
| Gemini Browser · **Video thông thường** | Gemini viết kịch bản từ prompt của template, app tự dựng (template HTML + giọng đọc + nhạc + phụ đề). Có chọn ảnh sản phẩm riêng thì dựng kiểu "Sản phẩm nổi" | theo mục Khung hình & thời lượng | theo app | 1 (ảnh sản phẩm) |
| Dola Browser | Dola AI Creation → Video (Seedance) trên dola.com — cần đăng nhập Dola (Provider Dola Browser → Đăng nhập) | 5/10s | 720p | 4 |
| Gemini API | Veo qua API key (`veo_model` trong Cài đặt, mặc định `veo-3.1-generate-preview`) | 4/6/8s | 720p/1080p | 3 (asset reference) |

Tuỳ chọn của template (ví dụ 15s) được tự chuẩn hoá theo engine (Veo → 8s). Nếu có nhiều ảnh hơn mức engine nhận, app bỏ ảnh thừa và ghi cảnh báo vào nhật ký.
Biến `"required": false` để trống thì được thay bằng chuỗi rỗng, và dòng chỉ còn `“”` sẽ bị bỏ khỏi prompt.

Cách dùng với Grok Imagine (grok.com/imagine):
- Chọn ở bộ chọn template, lọc **🎬 Video AI (Grok Imagine)**. Thẻ **Video AI · Grok Imagine** sẽ hiện ra, gồm:
  - các ô điền biến (ví dụ `{TenSanPham}`, `{HieuQua}`),
  - chọn thời lượng (6s/10s/15s) và độ phân giải (480p/720p/1080p),
  - phần xem trước prompt đã điền, kèm nút **Sao chép prompt**.
- Cần đăng nhập Grok một lần: Provider **Grok Browser** → **Đăng nhập**. Ô Nội dung và Provider AI không dùng cho loại template này.
- Quy trình: app mở Grok Imagine, chọn chế độ Video, đặt tỉ lệ/thời lượng/độ phân giải, nhập prompt, chờ tạo xong, tải video, chuẩn hoá H.264/AAC, cân âm lượng, rồi lưu vào thư viện.
- Thêm template mới: tạo `templates/<nhóm>/<id>/meta.json`:

```json
{
  "type": "ai_video", "engine": "grok_imagine",
  "name": "…", "description": "…", "tags": ["…"],
  "options": {"aspect": "9:16", "duration": "15s", "resolution": "720p"},
  "variables": [{"key": "TenSanPham", "label": "Tên sản phẩm", "placeholder": "…", "required": true}],
  "prompt": "… labeled '{TenSanPham}' …"
}
```

  Ảnh tham chiếu (tuỳ chọn) khai báo bằng `"attachments": [{"key", "label", "hint", "role", "prompt", "video": true}]`.
  Khi chạy, app chép ảnh vào `<video>/assets/`, tải tất cả lên Grok trong một lần (ô upload nhận nhiều ảnh), và thêm vào cuối prompt
  câu "Reference images are attached in this order — image 1 = <role>: <prompt>; …". Ô có `"video": true` nhận cả file video;
  khi đó app cắt khung hình ở giây thứ 1 làm ảnh tham chiếu.
  Có thể thêm `thumb.jpg` cạnh `meta.json` để làm ảnh bìa cho thẻ. Selector Grok Imagine nằm trong `app/llm/grok_imagine.py`.

## Tạo hình ảnh (sidebar → Tạo hình ảnh)

| Model | Cách chạy | Số ảnh | Ảnh tham chiếu |
|---|---|---|---|
| **OpenAI · GPT Image** (mặc định) | OpenAI Images API — nhập `OpenAI API key` trong Cài đặt (model `openai_image_model`, mặc định `gpt-image-1`) | 1–4 | tối đa 10 (dùng `/images/edits`) |
| OpenAI · ChatGPT (trình duyệt) | chatgpt.com bằng tài khoản đã đăng nhập (nút Đăng nhập trong trang Tạo ảnh), không cần API key | 1/2 | tối đa 10 |
| Gemini · Tạo hình ảnh | gemini.google.com, công cụ "Tạo hình ảnh" (tài khoản miễn phí dùng được) | 1 | 1 |
| Grok Imagine · Image | grok.com/imagine, chế độ Image | 1/2/4 | tối đa 10 |
| Dola · Seedream | dola.com AI Creation → Image | 1/2/4 | tối đa 4 |
| Gemini · Nano Banana | Gemini API key (`gemini_image_model`, mặc định `gemini-2.5-flash-image`) | 1–4 | tối đa 3 |

- Có 2 cách dùng: tự nhập prompt, hoặc chọn **template ảnh** (`"type": "ai_image"` trong `meta.json`, cùng định dạng biến/ảnh mẫu với template video AI).
- **Tham khảo ảnh Pinterest:**
  - Bật tuỳ chọn, nhập từ khoá, bấm **Tìm ảnh** để xem trước và chọn ảnh (tối đa 6). Nếu không tìm trước, app tự lấy các ảnh đầu tiên khi tạo.
  - App tìm trên pinterest.com không cần đăng nhập, dùng trình duyệt Chromium riêng. Ảnh được tải bản 736px vào `<bộ ảnh>/pinterest/` rồi gửi kèm làm tham chiếu, kèm lời dặn chỉ lấy cảm hứng (không chép watermark/chữ/logo).
  - Số ảnh tham chiếu tối đa vẫn theo giới hạn của từng model.
- Ảnh được lưu ở `<thư mục video>/_images/<tên>_<thời gian>/` (gồm `img_N.*` và `meta.json`). Nếu model trả ảnh khác tỉ lệ đã chọn, app tự cắt giữa cho đúng.

## Fanpage Facebook (sidebar → Fanpage Facebook)

1. **Lấy User Access Token.** Bấm **Mở Graph API Explorer**, rồi trong Explorer:
   - chọn Meta App của bạn và chọn **User Token**;
   - thêm 3 quyền `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`;
   - bấm **Generate Access Token** và cho phép các page cần dùng.
2. **Dán token** (chuỗi `EAA…`) vào ô **User Access Token**, rồi bấm **Kết nối & tải Fanpage**. App sẽ:
   - kiểm tra token (`/me`) và các quyền (`/me/permissions`), báo quyền nào còn thiếu;
   - lấy danh sách page kèm **Page Token** tương ứng (`/me/accounts`).
3. Bật **Kết nối** cho page muốn dùng, rồi bấm **Đăng bài** để đăng chữ, ảnh hoặc video.
4. *(Tuỳ chọn)* **App Meta.** Token lấy từ Explorer chỉ dùng được ~1–2 giờ. Nếu nhập App ID và App Secret của **đúng app đã chọn trong Explorer**, rồi dán lại token, app sẽ tự đổi sang token dài hạn (~60 ngày). Page Token lấy từ token dài hạn cũng dài hạn.

Ghi chú:
- App ở chế độ *Development* thì chỉ tài khoản có vai trò trong app (admin/developer/tester) mới đăng nhập được. Dùng cho người khác thì cần App Review cho các quyền trên.
- Token và App Secret chỉ lưu ở `facebook.json` trong thư mục dữ liệu của app, không gửi lên giao diện.

## Quảng cáo Facebook (sidebar → Quảng cáo Facebook)

Dùng chung User Access Token với mục Fanpage. Khi tạo token trong Graph API Explorer, thêm 2 quyền `ads_read` (xem số liệu) và `ads_management` (bật/tắt, đổi ngân sách, tạo quảng cáo). Thiếu quyền nào, màn hình sẽ báo.

- **Tổng quan:** chọn tài khoản quảng cáo và khoảng thời gian (hôm nay, 7 ngày, 30 ngày, tháng này… hoặc toàn bộ). App hiện:
  - chi tiêu, tiếp cận, lượt hiển thị, lượt nhấp, CTR, CPC, CPM;
  - kết quả chính: tin nhắn, khách tiềm năng, mua hàng, lượt nhấp link, lượt xem video hoặc tương tác.
- **Bảng phân cấp:** Chiến dịch → Nhóm quảng cáo → Quảng cáo. Bấm vào tên để xem cấp con, bấm thanh đường dẫn để quay lại.
- **Bật/tắt** bằng công tắc ở mỗi dòng, và **đổi ngân sách/ngày** bằng cách bấm vào số ngân sách. Cả hai đều hỏi xác nhận trước, vì ảnh hưởng tới tiền thật.
- **Tạo quảng cáo từ bài viết của Fanpage:**
  - chọn page và bài viết, mục tiêu (tương tác, tiếp cận hoặc ThruPlay video), ngân sách/ngày, số ngày chạy, quốc gia, độ tuổi, giới tính;
  - app tạo đủ Chiến dịch → Nhóm → Creative → Quảng cáo, tất cả ở trạng thái **TẠM DỪNG**, nên không tiêu tiền cho tới khi bạn tự bật;
  - nếu một bước lỗi, chiến dịch tạo dở sẽ bị xoá.
- Ngân sách nhập theo tiền tệ của tài khoản quảng cáo. Với VND, app gửi đúng số tiền; với USD/EUR, app tự đổi sang cent.

## Thể loại "Theo layout & sản phẩm mẫu"

Chọn thể loại này thì app hiện thẻ **Layout & sản phẩm mẫu**. Có 3 **kiểu video**:
- **Reel bán hàng** (mặc định, theo mẫu reel Facebook/TikTok bán phân bón):
  - Nền là **video quay thật** (MP4/MOV/WEBM, quay dọc) hoặc ảnh người bán cầm sản phẩm. Mỗi khung lấy đoạn tiếp theo của clip.
  - Lớp đồ hoạ phủ lên video: bong bóng logo shop (hoặc "Trả lời bình luận của …"), tag giá, checklist lợi ích (AI rút từ nội dung bạn nhập), chữ viền đen.
  - Khung cuối là thẻ **GIÁ ƯU ĐÃI** kèm giá cũ gạch ngang, ưu đãi (freeship…), lời mời bình luận "TƯ VẤN", và chân trang shop + website/hotline.
  - Giá, giá cũ, ưu đãi và website do bạn nhập. AI được dặn dùng đúng các con số này.
  - Tuỳ chọn **Giữ tiếng gốc của video**: dùng lời người bán nói trong clip thay cho giọng AI, đồng thời tắt phụ đề karaoke.
  - Khi render, lớp HTML được chụp dưới dạng PNG nền trong suốt rồi ghép đè lên video bằng ffmpeg.
- **Người mẫu giới thiệu (kiểu TikTok bán hàng)**: tải ảnh chụp dọc người mẫu cầm sản phẩm. Mỗi khung dùng một ảnh, xoay vòng,
  có hiệu ứng zoom/lia chậm. Video có bong bóng "Trả lời bình luận của …" (nhập bình luận thật của khách, để trống thì ẩn),
  chữ trắng viền đen, sticker giá, tên shop, và nút "ĐẶT HÀNG NGAY" ở khung cuối. AI viết lời theo giọng người bán nói trực tiếp với khách.
- **Sản phẩm nổi (showcase)**: như mô tả bên dưới.

Các tuỳ chọn khác:
- **Ảnh sản phẩm** (bắt buộc, 1–10 ảnh PNG/JPG/WEBP): chép vào `<video>/assets/` và lần lượt xuất hiện qua các khung. PNG nền trong suốt cho kết quả đẹp nhất.
- **Layout mẫu** (tuỳ chọn):
  - Là **ảnh**: làm nền cho template "Sản Phẩm Showcase", đồng thời app lấy tông màu chủ đạo của ảnh làm màu nhấn.
  - Là **file HTML**: dùng thẳng làm template Jinja2, xem phần "Thêm template" bên dưới. Có thêm các biến `product_image`, `product_images`, `layout_image`, `accent`, `bg`, `bg2`.
  - Không chọn: dùng template showcase với nền màu lấy từ ảnh sản phẩm.

Tên sản phẩm, giá và ưu đãi nhập vào ô **Nội dung**. Khi dùng **Gemini API**, ảnh sản phẩm được gửi kèm để AI viết đúng
sản phẩm. Gemini/Grok Browser không gửi ảnh, nên AI chỉ dựa vào nội dung bạn nhập.

## Pipeline (6 bước, khớp thanh tiến trình)

1. **Chuẩn bị**: kiểm tra license, khởi tạo provider và template.
2. **Kịch bản**: `script_writer.py` nhờ AI trả về JSON gồm từng khung (kicker, headline, highlight, subtext, stat, trend, narration). Nếu chọn "AI chọn template", AI chọn luôn template.
3. **Lời thoại**: `tts.py` (edge-tts) đọc từng khung và lấy mốc thời gian từng từ. Thời lượng khung = max(cấu hình, độ dài giọng + đệm).
4. **Dựng hình**: `scene_designer.py` chạy vòng lặp agent: điền template, đo chữ tràn (`__VA.overflow()`), nhờ AI rút gọn, rồi thử lại.
   Sau đó `renderer.py` mở HTML bằng Chromium headless và tua animation từng frame qua Web Animations API (ảnh ổn định, không phụ thuộc tốc độ máy), rồi đẩy JPEG vào ffmpeg để ra `scene.mp4`.
5. **Hậu kỳ**: `composer.py` lần lượt ghép khung, lồng giọng, thêm whoosh và nhạc nền, burn phụ đề ASS karaoke, rồi chuẩn hoá âm lượng (loudnorm −14 LUFS).
6. **Hoàn thiện**: ghi `job.json` và dọn thư mục `tmp/`.

Mỗi video là một thư mục trong thư mục lưu video:

```
<slug>_<YYYYmmdd_HHMMSS>/
  final.mp4  job.json
  scenes/01/{scene.html, scene.mp4, voice.mp3, thumb.jpg}
```

Ở tab **Kết quả → Chi tiết**, bạn có thể xem và sửa HTML từng cảnh. **Áp dụng** để xem trước, **Lưu file** để ghi lại, **Render lại** để dựng lại cảnh đó và ghép lại video cuối.

## Thêm template

Tạo thư mục `templates/<nhóm>/<id>/` gồm:
- `meta.json`: `name`, `description`, `tags` (từ khoá để tự chọn), `subtitle_margin` (vị trí phụ đề, tính theo tỉ lệ chiều cao).
- `template.html`: Jinja2. Đặt `{% include "head.html" %}` trong `<head>` để có font, CSS chung và runtime.

Biến có sẵn: `kicker, headline, words[{text,hl}], subtext, stat, trend, index, index2, total, duration, title, brand,
aspect_class, series, candles, line_path`. Đánh dấu ô chữ cần co cho vừa bằng `data-fit="headline|subtext|kicker|stat"`.
Chỉ dùng CSS animation (hoặc khai báo `window.__tick(ms)` cho animation bằng JS) để renderer tua chính xác được.
Nhóm hợp lệ: `sales, tech, news, finance, education, story, general`.

Nhạc nền: bỏ file mp3/wav vào `assets/music/` hoặc chọn thư mục trong Cài đặt. Nếu không có, app tự tổng hợp nhạc pad nhẹ.

## License ITNNV

`app/license.py` gắn mỗi tài khoản với 1 máy (định danh máy = hash của MachineGuid) và xác thực lại mỗi 30 phút.
Để trống **License server** trong Cài đặt thì app chạy ở chế độ phát triển. Server cần cung cấp:

```
GET  {server}/desktop/login?state&device&app=videoagent   → trang đăng nhập Google, gắn state với token
POST {server}/desktop/token   {state}                    → 200 {token} | 202 (đang chờ)
POST {server}/license/verify  {token, device, app}       → 200 {active, user:{name,email,avatar}, expires_at, message}
                                                            403 = tài khoản đang gắn máy khác
```

## Đóng gói .exe

```powershell
.\build.ps1
```

Kết quả nằm ở `dist\VideoAgent\VideoAgent.exe`. Chromium vẫn được tải ở lần chạy đầu trên máy người dùng.

## Cấu trúc mã

```
main.py                  khởi động server nội bộ + cửa sổ pywebview
app/api.py               cầu nối JS ↔ Python
app/server.py            phục vụ UI, file video (hỗ trợ Range), preview template
app/pipeline/            orchestrator, script_writer, tts, scene_designer, renderer, composer, subtitles, sfx
app/llm/                 Gemini Browser (Playwright), Gemini API, prompt
app/library.py           thư viện video (job.json)
app/license.py           license ITNNV
ui/                      giao diện (HTML/CSS/JS thuần)
templates/               template HTML/CSS theo nhóm
```
