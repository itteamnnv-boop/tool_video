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

## Nhân vật & Layout cố định (sidebar → Nhân vật & Layout)

Tạo nhân vật và bối cảnh dùng lại cho nhiều video Studio.

- **Nhân vật:**
  1. *Ý tưởng & mô tả cố định:* viết ý tưởng tiếng Việt, bấm **✨ AI viết mô tả** (chọn model chữ: Claude / ChatGPT / Gemini trình duyệt hoặc API). AI viết mô tả ngoại hình cố định bằng tiếng Anh; sửa tay được.
  2. *Ảnh gốc:* tải ảnh khuôn mặt lên, hoặc **✨ Tạo chân dung từ mô tả**. Ảnh gốc là tham chiếu khuôn mặt cho mọi góc.
  3. *Góc mặt, cơ thể & sheet nhân vật:* tick các góc rồi bấm tạo. Có các góc:
     - **sheet nhân vật đầy đủ**, dùng đúng prompt của template *Nhảy theo trend*;
     - mặt chính diện, mặt 3/4, mặt nghiêng;
     - biểu cảm (lưới 2×2);
     - toàn thân chính diện, nghiêng, sau lưng.

     Mỗi góc có prompt mẫu sửa được (✎ Prompt); prompt đã sửa được lưu cùng nhân vật.
  4. *Ảnh đã tạo:* ⭐ chọn ảnh dùng cho Studio, 👤 đặt làm ảnh gốc, **✎ sửa ảnh theo lời dặn** (VD: "tóc dài hơn, áo len màu kem"; ảnh mới tạo từ chính ảnh đó), 🗑 xoá. Làm tới khi ưng.
- **Layout:** cũng các bước ý tưởng → AI viết mô tả bối cảnh (không có người) → tạo vài phương án (chọn tỉ lệ, số phương án) → sửa ảnh theo lời dặn → ⭐ chốt ảnh.
  - **⬆ Tải layout mẫu lên** (tuỳ chọn): ảnh mẫu được ⭐ sẵn nên Studio dùng được ngay. Khi có ảnh mẫu, các phương án tạo mới được gửi kèm ảnh mẫu và giữ bố cục, cách sắp xếp, góc máy của mẫu; mô tả quyết định chi tiết, chất liệu, không khí. Ảnh mẫu cũng sửa được theo lời dặn.
  - Studio gửi 1 ảnh layout: ảnh ⭐ mới nhất.
  - **Thành phần giao diện** (tuỳ chọn, tick nhiều được): giao diện TikTok, khung livestream, giỏ hàng Shopee / TikTok Shop, giao diện Facebook, khung chat nhiều người quan tâm, bình luận nổi, tim / like bay lên, avatar + tên kênh. Ngoài ra nhập được tên kênh và **bình luận thật của khách** (mỗi dòng 1 bình luận).
    - Chữ trong bình luận chỉ lấy từ ô này. Để trống thì bong bóng có chữ mờ, không đọc được; app không tự bịa bình luận, lượt thích hay số người xem.
    - Icon được vẽ theo phong cách của các ứng dụng; model có thể không vẽ đúng logo.
    - Dùng ở Studio: bỏ tick "Không chữ / Không logo" trong Ràng buộc prompt để giữ giao diện (nhật ký nhắc nếu đang cấm).
- **Kết hợp** (tab thứ 3): chọn 1–3 nhân vật và 1 layout đã có, rồi:
  - **Ảnh sản phẩm** (tuỳ chọn, tối đa 3): tải ảnh sản phẩm để nhân vật cầm / giới thiệu đúng sản phẩm đó. Ảnh được gửi kèm sau ảnh nhân vật và layout, prompt dặn giữ nguyên bao bì, nhãn, logo của sản phẩm. Studio dùng bộ kết hợp cũng gửi kèm tối đa 2 ảnh sản phẩm khi tạo ảnh khung đầu.
  - viết hành động / dàn cảnh (có ✨ AI viết dàn cảnh);
  - **✨ Tạo ảnh kết hợp**: ảnh ⭐ của từng nhân vật và layout được gửi kèm, model đặt nhân vật vào bối cảnh; chọn tỉ lệ, số ảnh;
  - sửa ảnh theo lời dặn, ⭐ chốt.

  Ở Studio, chọn **Bộ kết hợp** thì nhân vật và layout của bộ được điền sẵn. Ảnh dàn cảnh ⭐ được gửi kèm khi tạo ảnh khung đầu, và mô tả dàn cảnh được đưa vào storyboard.
- **Dùng ở Studio:** ⚙ Cài đặt dự án (hoặc form Dự án mới) → **Nhân vật & layout cố định** → chọn tối đa 3 nhân vật và 1 layout, hoặc *Không dùng* (mặc định, như cũ). Khi dùng:
  - storyboard được dặn dùng đúng các nhân vật / bối cảnh đó; phần *Nhân vật* của dự án lấy nguyên mô tả đã duyệt;
  - khi tạo ảnh khung đầu, app gửi kèm ảnh ⭐ (1 nhân vật: 2 ảnh; nhiều nhân vật: mỗi người 1 ảnh; layout: 1 ảnh), trong giới hạn số ảnh của model; logo (nếu có) luôn là ảnh cuối;
  - dự án luôn dùng bản mới nhất của nhân vật / layout; mục đã xoá được bỏ qua.
  - **giữ nguyên khuôn mặt, phong cách, độ tuổi, trang phục và bối cảnh:**
    - *storyboard:* AI viết storyboard được dặn không tả quần áo, không thay đồ, không chuyển sang địa điểm khác, không viết cảnh nhân vật lúc nhỏ / lúc già / sau nhiều năm; prompt từng cảnh chỉ tả hành động, biểu cảm, góc máy, đạo cụ;
    - *ảnh khung đầu:* mô tả cảnh đặt trước, cuối prompt là câu khoá danh tính (*IDENTITY LOCK*: cùng khuôn mặt, màu da, vóc dáng, phong cách, độ tuổi; không làm đẹp, trẻ hoá hay già đi), khoá trang phục (*OUTFIT LOCK*) và khoá bối cảnh (*SETTING LOCK*). Cụm tả quần áo còn sót trong mô tả cảnh cũ (ví dụ "in a red ao dai") được tự bỏ;
    - *clip:* prompt dặn giữ nguyên khuôn mặt, tuổi, phong cách, trang phục và bối cảnh như khung đầu;
    - *ảnh gửi kèm khi tạo clip:* gửi 3 ảnh theo thứ tự: (1) khung đầu, (2) ảnh ⭐ của nhân vật, (3) ảnh sản phẩm của bộ kết hợp, không có thì ảnh layout / dàn cảnh. Prompt ghi rõ vai trò từng ảnh. Không dùng nhân vật / layout cố định thì chỉ gửi khung đầu như trước. Grok: ô tải chỉ nhận 1 file thì app tải lần lượt từng ảnh, chờ tải xong mới gửi;
    - *màn Nhân vật & Layout:* ảnh kết hợp và *Sửa ảnh theo lời dặn* cũng dặn giữ nguyên khuôn mặt, độ tuổi, phong cách.

    Dự án viết storyboard trước bản này: bấm **↻ Lưu & viết lại storyboard** hoặc làm lại ảnh các cảnh để áp dụng. Ảnh ⭐ của nhân vật / bộ kết hợp nên thấy rõ cả bộ đồ (toàn thân hoặc nửa người).
- **Bố cục màn hình:** cột trái là danh sách; đầu trang hiện tên, số ảnh ⭐, số ảnh, số sản phẩm và tác vụ đang chạy. Bên dưới, cột giữa là các bước thiết lập; cột phải gồm **Tiến trình** và **⭐ Dùng cho Studio**. Thư viện *Ảnh đã tạo* nằm dưới cùng, trải hết chiều ngang.
- **Tiến trình** (giống trang Tạo video):
  - các bước Chuẩn bị → Tạo ảnh / AI viết mô tả → Lưu → Hoàn tất, kèm thanh %, trạng thái và nhật ký chi tiết. Nhật ký lấy từ tác vụ ảnh thật, ví dụ "đã gửi prompt", "đang tạo ảnh 2/2";
  - nhiều tác vụ thì bấm tên tác vụ để chuyển; **■ Dừng** để huỷ.
- Ảnh vẫn chạy qua hàng đợi *Tạo hình ảnh*. Dữ liệu lưu ở `cast/` trong thư mục dữ liệu của app.

## Facebook (nhóm FACEBOOK trên menu)

Gồm **Fanpage Facebook**, **Quảng cáo Facebook**, **Trợ lý quảng cáo** và **Quản lý bài đăng**.

### Quản lý bài đăng
- **Tự lưu:** mọi bài đăng thành công được lưu kèm *bản sao* ảnh / video, nên vẫn đăng lại được dù file gốc đã xoá. Nguồn gồm:
  - nút Đăng bài ở trang Fanpage;
  - block Đăng bài Facebook trong Workflow;
  - Chiến dịch.
- **Bài mới / Sửa:** soạn hoặc sửa tên bài, kiểu bài (feed, chỉ chữ, chỉ ảnh/video, Reels, Story), nội dung và tối đa 10 ảnh hoặc 1 video. *Lưu bài* để giữ làm nháp.
- **Đăng / Đăng lại:**
  - chọn một hoặc nhiều Fanpage đã bật Kết nối;
  - chọn Đăng ngay hoặc Hẹn giờ (10 phút → 30 ngày; Story không hẹn giờ được);
  - **phải tick ô xác nhận** mới đăng được;
  - mỗi lần đăng ghi lại Fanpage, thời điểm, người xác nhận, link bài hoặc lỗi. Page lỗi không chặn page khác.
- **Lọc và tìm:** lọc theo trạng thái (Nháp / Đã đăng / Hẹn giờ / Lỗi) và nguồn, tìm theo nội dung hoặc tên Fanpage.
- **Xoá:** 🗑 chỉ xoá bài khỏi danh sách (kèm bản sao file), không xoá bài trên Facebook.
- **Dữ liệu:** lưu ở `posts/posts.json` và `posts/media/<id>/` trong thư mục dữ liệu của app.

## Cách điều khiển Chrome (Cài đặt → Trình duyệt)

Mọi model chạy qua trình duyệt (ChatGPT, Gemini, Grok, Dola, Muse, Claude; Studio, Studio Muse AI, Tạo ảnh / video, Trợ lý quảng cáo…) đều mở **Chrome thật của máy**. Mỗi tài khoản dùng một profile riêng, và app điều khiển qua **CDP bằng đường ống nội bộ** (`--remote-debugging-pipe`, không mở cổng mạng). Có 2 chế độ:

- **Chrome thật (CDP)** — mặc định:
  - chỉ dùng khoảng 11 cờ tối thiểu, không có các cờ thử nghiệm / tắt tiện ích / keychain giả của Playwright;
  - **không bao giờ chạy headless**, cửa sổ có kích thước thật;
  - vân tay giống Chrome thường nên trang web ít nghi là bot.
- **Playwright** — cách cũ: khoảng 43 cờ tự động hoá, có nơi chạy headless. Chọn chế độ này nếu chế độ mới gặp lỗi.

Việc dựng khung hình từ template HTML vẫn dùng Chromium headless đi kèm, vì không đăng nhập tài khoản nào.

### Giữ Chrome mở sẵn cho mỗi tài khoản (kiểu HaoHao)

Công tắc trong Cài đặt → Trình duyệt, mặc định **tắt**. Chỉ có tác dụng khi chọn chế độ Chrome thật (CDP).

- **Bật:**
  - mỗi profile giữ một Chrome chạy liên tục;
  - các lượt sau nối lại vào Chrome đó (`app/llm/chrome_pool.py`), không phải mở Chrome và tải lại phiên → nhanh hơn, phiên đăng nhập luôn sẵn;
  - task xong chỉ đóng các tab nó mở thêm rồi ngắt kết nối, Chrome vẫn chạy.
- **Khi Chrome tự đóng:**
  - rảnh 20 phút;
  - thoát app;
  - đổi lại cài đặt (Chrome đang chạy task sẽ đóng khi task xong);
  - mở cửa sổ đăng nhập của profile đó.
- **Cổng gỡ lỗi:** task nối vào Chrome qua cổng gỡ lỗi **chỉ trên máy này** (127.0.0.1, cổng ngẫu nhiên). Khác chế độ thường dùng đường ống nội bộ, vì Chrome phải sống lâu hơn từng task.
- **Tắt:** quay về cách cũ (mỗi lượt mở rồi đóng Chrome), không ảnh hưởng chức năng nào khác.

## Hiện / ẩn cửa sổ Chrome (Cài đặt → Trình duyệt)

Một công tắc chung cho mọi màn hình chạy model qua trình duyệt:
- **Bật:** cửa sổ Chrome hiện trên màn hình.
- **Tắt:** Chrome chạy ngầm ngoài màn hình và **không hiện icon trên thanh taskbar**.

Cửa sổ đăng nhập luôn hiện. Các công tắc "Hiện Chrome" riêng ở từng màn đã bỏ.

## Profile trình duyệt (sidebar → Profile trình duyệt)

Mỗi profile là một Chrome riêng, có cookie và tài khoản đăng nhập riêng. Dùng profile khi mỗi model (Gemini, Grok, ChatGPT, Claude, Dola, Muse) cần một tài khoản khác, hoặc khi muốn nhiều tài khoản của cùng một model chạy song song.

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

### Muse (muse.ai) viết storyboard / chữ

**Muse (Meta) (trình duyệt)** có trong mọi ô chọn model viết chữ: Studio (viết storyboard, hậu kỳ AI), Nhân vật & Layout (AI viết mô tả), Tạo content bài viết và các block Workflow.
- Dùng tài khoản Muse đã đăng nhập trong Profile trình duyệt, giống Muse Image / Video.
- Mỗi yêu cầu được dặn thêm: chỉ trả lời bằng chữ trong khung chat, không tạo ảnh / video, không dùng công cụ khác. Lý do: Muse là trợ lý làm được nhiều việc.
- Nhận được giao diện tiếng Việt (ô *Nhắn tin*) lẫn tiếng Anh (*Message*). Muse Image / Video cũng dùng cách nhận này.
- App gửi kèm một mã yêu cầu ở cuối tin nhắn (dạng `[VA-xxxxxxxx]`), rồi đọc toàn bộ chữ Muse trả lời sau mã đó, giữ xuống dòng, bỏ chữ trên các nút gợi ý. Coi là xong khi Muse ngừng viết; riêng storyboard phải đọc được JSON đủ các cảnh.
- **Lần đầu dùng Muse:** Muse hỏi "Bạn muốn gọi mình là gì?" (Beacon / Astro / Muse…). App dừng và nhắc bạn mở Muse bằng profile trình duyệt để chọn tên trước, không tự chọn thay bạn.

### Claude Browser (claude.ai)

Claude (Anthropic) dùng qua trình duyệt với tài khoản claude.ai đã đăng nhập, không cần API key. Claude chỉ viết chữ:
- kịch bản (Provider AI ở trang Tạo video),
- storyboard trong **Studio**,
- **Tạo content** bài viết,
- block **Tạo văn bản** và **Tạo content bài viết** trong Workflow.

Claude không tạo ảnh hay video. Nếu chọn Claude Browser làm Provider AI với template AI video, app báo chưa có engine video.

Cách dùng:
- Lần đầu, vào **Profile trình duyệt** → profile *Mặc định* (đã tự gán Claude) → **Đăng nhập** cạnh Claude.
- App tự dặn Claude trả lời ngay trong khung chat, không mở artifact, để đọc được câu trả lời.
- claude.ai chặn trình duyệt chạy ẩn, nên app mở Chrome ngoài màn hình; bật *Hiện Chrome* để xem trực tiếp.

## Seedance Studio Pro (sidebar → Seedance Studio Pro)

Workspace riêng để tạo video hàng loạt qua **Dola**, có adapter **Doubao thử nghiệm**. Chạy trực tiếp bằng Playwright và các profile có sẵn của app; không cần cài extension.

1. Chọn nhà cung cấp, chọn profile, bấm **Đăng nhập**. Đăng nhập trong cửa sổ mở ra rồi đóng cửa sổ đó. Profile mới được thêm tại **Profile trình duyệt** và phải được gán cho nhà cung cấp tương ứng.
2. Nhập kịch bản hoặc kéo thả TXT/CSV/JSON. Một dòng là một cảnh; nếu có dòng trống, mỗi đoạn là một cảnh và giữ nguyên xuống dòng bên trong. CSV có cột `text`/`prompt`, tuỳ chọn `title`; JSON nhận mảng chuỗi, mảng `{title,text}` hoặc `{scenes:[...]}`.
3. Chọn Text to Video hoặc Image to Video. Với ảnh, thêm/kéo thả JPEG/PNG/WebP/GIF/AVIF (tối đa 200 ảnh, 25 MB/ảnh); đổi thứ tự bằng ↑/↓. Ảnh được ghép theo thứ tự cảnh; phần dư được hiển thị và giữ lại.
4. Chọn model 2.5/2.0, tỉ lệ hoặc **Không chèn tỉ lệ**, thời lượng, tiền tố và phong cách. Sáu nút phong cách giữ nguyên tên/nội dung mô tả của bản gốc: **Hollywood 4K, Chân Dung 8K, Hành Động, Anime 60FPS, Cyberpunk, Fantasy 3D**. Cấu hình dùng chung cho cả hai chế độ.
5. Bấm **Tạo video** để chạy toàn bộ cảnh chờ, hoặc **Gửi cảnh** cho một cảnh. Có thể dùng nhiều profile và 1–4 tab/profile, tối đa 12 tab. Cụm hai cảnh được phân phối vòng tròn; mỗi tab gửi từng cảnh và chờ video trước cảnh tiếp theo, tối đa hai cảnh/chat (Img2Vid: một cảnh/chat). New Chat không được xác minh thì lane dừng.
6. Theo dõi riêng **Đã gửi**, **Cảnh có video**, **Video đã tải**. Video nằm ở tab **Video đầu ra**: xem, tải MP4, mở file, chọn video để xuất ZIP (không chọn thì xuất tất cả). ZIP giữ thứ tự cảnh, hỗ trợ ZIP64 và ghi `_error.txt` cho từng file lỗi. Bật **Gom ZIP** sẽ tắt tải lẻ tự động trên mọi đường thu media.

**Dừng & khôi phục:** Dừng ngăn các thao tác tiếp theo; không huỷ render đang chạy trên dịch vụ. Trạng thái và nhật ký lưu bằng SQLite ở thư mục dữ liệu app `seedance/`; ảnh được chép vào `seedance/images/`. Sau khi app đóng giữa chừng, cảnh đang chạy được đánh dấu **Bị gián đoạn**, không tự gửi lại. Kiểm tra URL chat trong chi tiết cảnh, dùng **Quét lịch sử** để thu video rồi **Gắn cảnh** để nối lại kết quả. **Thử lại** là thao tác chủ động và có xác nhận nếu trước đó đã bấm gửi. Có thể xuất kịch bản/cấu hình/trạng thái/log ra JSON.

**Thông báo limit tài khoản:** App phân biệt hạn mức ngày, không đủ credit, số video đang chạy đồng thời, giới hạn tần suất và giới hạn tài khoản chưa rõ loại. Thông báo gốc được lưu cùng cảnh và hiển thị trong banner. Khi một profile bị giới hạn, app dừng gửi thêm bằng profile đó, vẫn thu kết quả của video đã gửi và tiếp tục công việc ở các profile khác đang hoạt động bình thường. Không tự gửi lại cảnh bị từ chối; kiểm tra chat và điều kiện trên nhà cung cấp trước khi chủ động thử lại. Một toast mới có nội dung trùng thông báo cũ vẫn được nhận diện; thông báo cũ trong lịch sử chat không tự chặn batch mới.

File MP4, dự án JSON và ZIP lưu tại `<thư mục video>/_seedance/`. Tải video kiểm tra file bằng ffmpeg và đọc kích thước/thời lượng thực. ZIP ghi từ đĩa, giới hạn 500 video, 1 GB/video và 10 GB/ZIP.

**Seedance 2.5:** Chế độ **Tự nhận diện** mở workspace tạo video và chọn **Dreamina Seedance 2.5** trong bộ chọn thực tế. Bộ chọn mới của Dola gộp tỉ lệ và thời lượng vào cùng panel, dùng slider thời lượng. Adapter đọc giới hạn trên trang, xác minh giá trị trước khi gửi và báo lỗi nếu không hỗ trợ. UI mặc định 10s, có 5s; 15s dùng luồng chat. Đã kiểm tra thao tác chọn 2.5 / 10s / 16:9 trên profile Dola đăng nhập tại máy này, không bấm tạo video trong lần kiểm tra. Có thể chọn riêng **Pro/Fast chat** để dùng luồng extension gốc; ở luồng này model video chỉ được yêu cầu trong prompt, không coi Pro chat là bằng chứng model video 2.5.

**Watermark:** Bật **Ưu tiên bản master không watermark** để resolver yêu cầu `channel=no`, `codec_type=8`, `logo_type=unwatermarked` qua fallback API của nhà cung cấp, chọn biến thể chất lượng cao và giải mã token URL khi cần. Bộ lọc phân biệt `watermarked` với `unwatermarked`. Nguồn master được ghi rõ; không dùng việc đổi query trên URL preview làm bằng chứng video đã sạch logo. Nếu không lấy được master sau thời gian chờ, video hiện có được lưu với trạng thái watermark tương ứng.

Với MP4 đã tải, bấm **Gỡ watermark**, kéo khoanh vùng logo cố định, xem khung tham chiếu bằng thanh thời gian rồi xác nhận. App dùng [FFmpeg delogo](https://ffmpeg.org/ffmpeg-filters.html#delogo) nội suy vùng chọn sang file `_clean.mp4`, giữ nguyên kích thước, âm thanh và file gốc. Bản xử lý được dùng khi xem/mở/xuất ZIP; có thể xuất hiện vùng mềm hoặc vệt nội suy, và công cụ không tự bám logo di chuyển. Nhãn 4K/8K/60FPS của phong cách là nội dung mô tả gửi trong prompt; thông số thực được đọc từ file.

Không cam kết 1080p, quota không giới hạn hoặc 30/60s. Selector, React props và URL media phụ thuộc giao diện dịch vụ. Doubao vẫn là adapter thử nghiệm. Bộ kiểm thử không gửi yêu cầu tạo video thật.

Kiểm tra triển khai:

```powershell
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python tests/smoke_seedance_ui.py
```

Mã nguồn: `app/seedance/` (parser/config, SQLite, adapter, scheduler/download); `ui/seedance.js` và `ui/seedance.css` (giao diện). Không dùng lại module tài khoản, license shield hoặc code obfuscate của extension gốc.

## Workflow (sidebar → nhóm WORKFLOW)

Nhóm có 2 trang:
- **Danh sách workflow**: thẻ cho từng workflow (chuỗi block, số lần chạy, trạng thái lần chạy gần nhất), số liệu nhanh, tìm kiếm và lọc theo trạng thái. Mỗi thẻ có nút Mở, ▶ Chạy, Nhân đôi, Xoá. Bên dưới là các mẫu dựng sẵn.
- **Thiết kế workflow**: canvas kéo thả, mô tả ở dưới. Nút **← Danh sách** để quay lại.

Tự dựng quy trình sản xuất video bằng cách kéo thả block, rồi chạy lại bao nhiêu lần cũng được. Màn hình đi theo 4 bước, hiện ở thanh trên cùng:

| Bước | Làm gì |
|---|---|
| **01 Thiết kế** | Kéo block từ bảng bên trái vào canvas. Kéo từ cổng ra (bên phải block) sang cổng vào (bên trái block) để nối. Dây sai kiểu dữ liệu bị từ chối. Kéo nền để di chuyển, lăn chuột để phóng to/thu nhỏ, phím Delete để xoá block hoặc dây. |
| **02 Cấu hình AI** | Chọn một block để cấu hình ở bảng bên phải: model (video: Grok Imagine, Gemini Veo, Dola Seedance, Gemini API; ảnh: OpenAI/Gemini/Grok/Dola; chữ: Claude, Gemini, Grok, ChatGPT), prompt, tỉ lệ, thời lượng, độ phân giải. Block thiếu cấu hình có dấu đỏ và hiện ở tab **Kiểm tra**. |
| **03 Chạy tự động** | Bấm **▶ Chạy**: các block chạy lần lượt theo dây nối, chạy nền nên có thể làm việc khác. Khay dưới hiện tiến trình từng block, nhật ký và kết quả. Bấm vào một ảnh hoặc video kết quả để mở hộp thoại xem ảnh lớn / phát video (‹ › hoặc phím ←/→ để chuyển, Esc để đóng, có nút Mở thư mục). Block lỗi thì các block phía sau nó được bỏ qua; các nhánh khác vẫn chạy. |
| **04 Tái sử dụng** | Workflow tự lưu. Block đầu vào bật **Hỏi lại khi chạy** thì mỗi lần bấm Chạy sẽ hỏi input mới (văn bản/ảnh); phần còn lại giữ nguyên. Tab **Lịch sử chạy** xem lại kết quả mọi lần chạy. |

**Các block:**
- Đầu vào: Văn bản/Prompt, Ảnh, Video.
- AI xử lý: AI viết/xử lý — viết `{{input}}` để chèn văn bản đầu vào vào yêu cầu.
- Tạo nội dung: Tạo ảnh, Tạo video, **Video dài từ storyboard**, **Whiteboard từ SRT / kịch bản**, Ghép video (nối nhiều video theo thứ tự dây).
  - **✍ Whiteboard từ SRT / kịch bản** — như template *SRT Whiteboard animation* (xem mục [SRT Whiteboard animation](#srt-whiteboard-animation)):
    - **Cổng vào:** *SRT / kịch bản* (văn bản). Có thể gõ trong block hoặc chọn file `.srt` (file được ưu tiên).
    - **Cổng ra:** *Video*, *Lời đọc* (toàn bộ câu phụ đề, dùng làm caption).
    - **Cài đặt:** model vẽ ảnh line-art, tỉ lệ, giọng đọc + tốc độ, file âm thanh khớp SRT (tuỳ chọn), chất lượng dựng, gợi ý phong cách, bàn tay, phụ đề.
    - Block *Video dài từ storyboard* có thêm ô **Kiểu dựng cảnh** (Clip video AI / Whiteboard vẽ tay).
  - **🎬 Video dài từ storyboard** — chạy trọn quy trình của màn **Studio** trong workflow:
    - **Cổng vào:** *Ý tưởng* (văn bản), *Ảnh tham chiếu* (nhân vật / sản phẩm). Có thể gõ thêm ý tưởng ngay trong block.
    - **Cổng ra:** *Video* (video hoàn chỉnh), *Lời dẫn* (nối sang block Đăng bài Facebook làm caption).
    - **Cài đặt:** chỉnh ngay trong block (độ dài, phong cách, model storyboard / ảnh / video, lồng tiếng hoặc giọng gốc, giọng đọc, phụ đề, nhạc nền, chuyển cảnh, hậu kỳ AI, hiện trình duyệt), **hoặc** chọn *Lấy toàn bộ cài đặt từ dự án Studio* để dùng nguyên cài đặt của dự án đó, gồm logo, ràng buộc prompt, profile trình duyệt, hậu kỳ…
    - **Khi chạy:** mỗi lần chạy tạo 1 dự án mới trong màn Studio, tự viết storyboard → tạo ảnh + clip từng cảnh → ghép. Nhật ký và % của Studio hiện ngay trong workflow.
    - **Dừng / lỗi:** bấm Dừng workflow thì dự án Studio cũng dừng. Lỗi thì mở dự án ở màn Studio để làm lại cảnh lỗi rồi ghép.
  - **Tạo ảnh → kết hợp ảnh sản phẩm và ảnh tham chiếu**: model nhận ảnh theo thứ tự sau, và prompt ghi rõ vai trò của từng ảnh:
    1. Ảnh nối vào cổng *Ảnh sản phẩm*: mặc định model giữ nguyên bao bì, logo, chữ, màu. Có thể đổi thành "Ảnh tham chiếu chung".
    2. **Ảnh tham chiếu đính kèm** chọn ngay trong block, kèm vai trò: người mẫu/nhân vật, phong cách/bố cục/màu sắc, bối cảnh/nền, hoặc tham chiếu chung.
    3. Ảnh Pinterest (nếu bật).

    Nếu tổng số ảnh vượt mức tối đa của model, app bỏ bớt ảnh ở cuối danh sách.
  - **Tạo ảnh → Tham khảo ảnh tìm trên Pinterest**: có hai cách lấy ảnh tham khảo.
    - Bấm **🔍 Tìm & chọn ảnh Pinterest…** để tìm và chọn sẵn tối đa 6 ảnh.
    - Không chọn ảnh nào: lúc chạy app tự tìm theo từ khoá. Từ khoá lấy từ ô Từ khoá, hoặc từ dây nối vào cổng *Từ khoá Pinterest*; nếu để trống thì lấy theo prompt.

    Ảnh Pinterest chỉ dùng để tham khảo bố cục và màu sắc (prompt ghi rõ không sao chép). Ảnh bạn nối vào block vẫn là ảnh tham chiếu chính.
  - **Tạo video → Template video**: bấm **▦ Chọn template…** để mở cửa sổ chọn dạng thẻ, giống trang Tạo video (lọc theo nhóm, có ảnh bìa, biến và số ảnh tham chiếu). Sau khi chọn:
    - Block chạy đúng như trang Tạo video. Tỉ lệ khung hình và model (nếu template cố định model, ví dụ *Nhảy theo trend* dùng Grok) được khoá theo template. Bảng bên phải hiện *Video đầu ra theo template* và các bước của template nhiều bước (ví dụ ChatGPT ghép mặt, rồi sheet nhân vật, rồi Grok tạo video).
    - **Ảnh / video template yêu cầu**: mỗi ô (ảnh sản phẩm, ảnh nhân vật, video mẫu…) có nút chọn file riêng, đúng loại file của ô đó. Ô để trống thì lấy file từ dây nối vào cổng *Ảnh tham chiếu* / *Video tham chiếu* theo thứ tự; nếu vẫn không có thì dùng ảnh mẫu của template. Ô bắt buộc còn trống thì app báo lỗi ở tab Kiểm tra.
    - **Thông tin template yêu cầu**: điền các biến. Ô để trống thì dùng giá trị mặc định.
    - **Prompt & quy trình của template**: liệt kê từng bước của template, gồm model, khung hình và ảnh/video đầu vào của mỗi bước (lấy từ ô nào hoặc từ bước nào). Mở "Prompt" để xem prompt thật sẽ gửi đi, đã điền thông tin bạn nhập (phần điền được tô màu, cập nhật ngay khi gõ). Bấm **✎ Sửa prompt** để sửa prompt của một bước riêng cho block này, template gốc không đổi. Bấm **↺ Dùng prompt gốc** để khôi phục. Đổi sang template khác thì prompt đã sửa được bỏ.
    - *Văn bản từ dây Prompt điền vào biến*: chọn biến sẽ nhận văn bản nối vào cổng Prompt (ví dụ Tên sản phẩm).
    - *Hỏi các thông tin template khi chạy workflow*: khi bấm ▶ Chạy, hộp thoại sẽ hỏi cả thông tin lẫn file ảnh/video của template, giống block đầu vào bật "Hỏi lại khi chạy". Mục bắt buộc còn trống thì app không cho chạy.
    - Bấm **+ Tạo template** để tự viết template: đặt `{TenBien}` trong prompt và app tự tạo ô nhập cho từng biến (đặt tên hiển thị, giá trị mặc định, bắt buộc hay không). Có thể thêm ô ảnh tham chiếu. Template có sẵn của app không sửa trực tiếp được, chỉ có thể **tạo bản sao** rồi sửa.
    - Template bạn tạo lưu ở `user_templates/<nhóm>/<id>/meta.json` trong thư mục dữ liệu của app và cũng dùng được ở trang Tạo video.
- Đầu ra:
  - **Kết quả**: gom file cuối vào một thư mục.
  - **Đăng bài Facebook**: đăng caption và ảnh/video lên Fanpage đã kết nối.
  - **Lên lịch đăng bài**: giống Đăng bài nhưng hẹn giờ, sau N giờ hoặc vào một thời điểm, từ 10 phút đến 30 ngày.
  - **Tạo quảng cáo**: nối từ cổng *Bài viết* của block đăng bài; tạo chiến dịch, nhóm quảng cáo và quảng cáo ở trạng thái **TẠM DỪNG**, sau đó bạn tự bật trong Quản lý quảng cáo.

**Chạy thử từng block:** di chuột lên block và bấm nút ▶ ở góc, hoặc chọn block rồi bấm **▶ Chạy thử block này** ở bảng bên phải. App mở hộp thoại cho biết trước:
- block nào sẽ chạy thật;
- block phía trước nào dùng lại kết quả của lần chạy cũ. App chỉ dùng lại khi cấu hình và dây vào của block không đổi và file kết quả vẫn còn. Block phía trước chưa có kết quả thì được chạy kèm. Tích **Chạy lại cả các block phía trước** để bỏ qua kết quả cũ.

Lần chạy thử được lưu trong **Lịch sử chạy**, có nhãn *Chạy thử*, nhưng không tính là "lần chạy gần nhất" của workflow. Block đầu vào bật *Hỏi lại khi chạy* sẽ dùng input mặc định đang lưu. Chạy thử block đăng bài hoặc tạo quảng cáo vẫn đăng bài và tạo quảng cáo thật (đăng bài vẫn phải chờ duyệt, quảng cáo vẫn ở trạng thái tạm dừng). Hộp thoại có cảnh báo trước khi chạy.

**Duyệt trước khi đăng:** tùy chọn này bật sẵn. Khi chạy tới block đăng bài, workflow dừng ở trạng thái *Chờ duyệt*. Khay **Tiến trình** hiện ảnh/video và caption; caption sửa được trước khi bấm **Đồng ý đăng**. Nếu bấm **Không đăng**, block đó và các block phía sau được bỏ qua. Ai duyệt và lúc nào được ghi vào `run.json` và vào **Lịch sử & chi phí**. Nếu có cả ảnh lẫn video, app chỉ đăng video. Không tạo được quảng cáo cho bài đã hẹn giờ mà chưa đăng.

Có 3 mẫu dựng sẵn ở **+ Mới**: *Ảnh → Video*, *Ý tưởng → AI → Ảnh → Video*, *2 cảnh → Ghép video*.

Workflow lưu ở `workflows/<id>.json` trong thư mục dữ liệu của app. Mỗi lần chạy lưu ở `<thư mục video>/_workflows/<id>/<YYYYmmdd_HHMMSS>/` (mỗi block một thư mục con, kèm `run.json`). Xoá workflow không xoá kết quả các lần chạy.

## Studio — ý tưởng → storyboard → video dài (sidebar → Studio)

Từ một ý tưởng, AI viết storyboard 5–10 cảnh. Mỗi cảnh gồm lời đọc tiếng Việt, prompt ảnh khung đầu và prompt chuyển động; bạn sửa được trước khi làm. App tạo ảnh khung đầu, rồi nhờ model video tạo clip cho từng cảnh, sau đó ghép thành video 30–90 giây có giọng đọc, phụ đề và nhạc nền. Video hoàn chỉnh nằm trong **Thư viện video**.

- **Một video / Hàng loạt.**
  - *Một video:* tạo một dự án; tích "Tự làm video luôn" để bỏ bước duyệt storyboard.
  - *Hàng loạt:* mỗi dòng ý tưởng là một video, tối đa 20 dòng. Có thể đặt tiền tố tên, ví dụ "BOSS 1" → BOSS 1 #1, #2… Mọi dự án dùng chung tuỳ chọn và ảnh tham chiếu, tự làm trọn từ storyboard đến ghép.
  - Các dự án xếp hàng chạy song song theo giới hạn trong Cài đặt. Ảnh và clip chạy song song theo số profile trình duyệt của từng model.
- **▶ Chạy tiếp tất cả** (ở cột Dự án): chạy tiếp mọi dự án chưa có video. Dự án chưa có storyboard thì viết rồi làm; đã có thì làm các cảnh còn thiếu rồi ghép. Dự án bị gián đoạn vì app tắt giữa chừng hiện "Bị gián đoạn" và chạy tiếp được.
- **↻ Làm lại N cảnh lỗi:** làm lại đúng các cảnh lỗi rồi tự ghép lại video.
- **Cách ghép:** cảnh có lời đọc dài theo lời đọc, được dư thêm tối đa 2 giây để clip chạy hết.
  - Clip dài hơn thì tua nhanh tối đa 1,25×; clip ngắn hơn thì tua chậm tối đa 0,8×. Nhờ vậy giữ trọn chuyển động, hạn chế cắt cụt hoặc đứng hình.
  - Cảnh không lời giữ clip tối đa 8 giây.
  - Nhật ký ghi rõ từng cảnh dài bao nhiêu, tua bao nhiêu và có bỏ phần nào không.
- **🎬 Video tham khảo** (tuỳ chọn, đầu ⚙ Cài đặt dự án và form Dự án mới):
  - dán **link** (YouTube, TikTok, Facebook, Instagram…, tải bằng `yt-dlp`) hoặc **📁 Chọn file** video, rồi bấm **🔍 Phân tích** (1–3 phút);
  - app tự cắt các khung đổi cảnh thành một ảnh lưới có ghi mốc giây và đo nhịp dựng (số lần cắt cảnh, độ dài cảnh trung bình); link có phụ đề thì lấy luôn phụ đề;
  - sau đó hỏi model **một lần** để ra bản tóm tắt: chủ đề, hook, cấu trúc theo thời gian (kèm góc máy), nhịp dựng, phong cách hình, lời thoại, âm thanh, điểm hay, gợi ý áp dụng. Bản tóm tắt **sửa được**;
  - model 👁 (Gemini trình duyệt / API, Claude / OpenAI API) xem được ảnh khung hình; model khác chỉ đọc tiêu đề, mô tả, phụ đề;
  - tick **Dùng video tham khảo khi viết storyboard** (bỏ tick = không dùng, vẫn giữ bản phân tích). *Cách dùng*:
    - **Lấy cảm hứng**: cấu trúc, nhịp, hook, phong cách;
    - **Bám sát**: cùng cấu trúc / nhịp nhưng thay bằng sản phẩm, nội dung của bạn.

    Storyboard luôn được dặn không chép nguyên văn lời thoại, thương hiệu, nhân vật hay logo của video gốc;
  - video tải từ link chỉ dùng để phân tích, app xoá sau đó; ảnh lưới được lưu vào dự án. Nhân bản dự án cũng chép theo video tham khảo.
- **👥 Hồ sơ nhân vật** (thẻ *Nhân vật & phong cách*), khoá nhân vật và trang phục:
  - storyboard tự tạo hồ sơ cho từng nhân vật: tên, ngoại hình cố định (tuổi, khuôn mặt, tóc, vóc dáng), **một bộ trang phục cố định**, giọng lồng tiếng riêng. Sửa được, thêm / xoá được (tối đa 8); đổi tên thì câu thoại và cảnh tự đổi theo;
  - mỗi cảnh có hàng **Trong khung hình**: bật / tắt nhân vật xuất hiện;
  - prompt ảnh khung đầu chỉ chèn hồ sơ của **nhân vật có trong cảnh**, kèm câu khoá danh tính (cùng khuôn mặt, tuổi) và khoá trang phục. Áp dụng **cả khi không dùng Nhân vật & Layout cố định**. Cụm tả quần áo lạc trong mô tả cảnh được tự bỏ;
  - dự án cũ (chưa có hồ sơ) vẫn chạy như trước.
- **Lời thoại có mô tả**, lồng tiếng nhiều nhân vật:
  - mỗi cảnh có danh sách câu thoại: **ai nói** (nhân vật hoặc 🎙 người dẫn chuyện), câu nói, **cảm xúc / giọng điệu**; có 🔊 nghe thử từng câu. Cảnh có lời đọc đơn thì bấm *+ Chia thành thoại nhiều nhân vật*;
  - khi lồng tiếng AI, **mỗi câu đọc bằng giọng của người nói**, nối lại thành giọng của cảnh; phụ đề vẫn khớp từng từ. Hai nhân vật cùng giọng thì tự lệch cao độ cho dễ phân biệt;
  - prompt clip mô tả rõ ai nói câu nào, cảm xúc, chất giọng. Model video khớp khẩu hình đúng người; với giọng gốc thì mỗi người nói bằng giọng riêng;
  - thêm vai giọng: thiếu nữ / thiếu niên, MC nam / nữ, nữ nhẹ nhàng, nam trầm uy lực, cùng **6 giọng đa ngôn ngữ** (Ava, Emma, Vivienne, Andrew, Brian, Hyunsu). Các giọng này đọc được tiếng Việt nhưng hơi lơ lớ, hợp vai người nước ngoài / vai cách điệu.
- **Chất lượng prompt:**
  - storyboard viết prompt theo công thức: cỡ cảnh + góc máy → nhân vật (gọi bằng tên) làm gì, biểu cảm → bố cục, đạo cụ → ánh sáng → ống kính → không khí. Prompt chuyển động là *một* hành động chính + chuyển động máy + nhịp độ;
  - **✨ Chuốt prompt** (nút ở đầu dự án, hoặc tick *Chuốt prompt bằng AI sau khi viết storyboard* trong ⚙): model viết lại prompt ảnh / chuyển động từng cảnh chi tiết hơn, giữ nhân vật và câu chuyện. Cảnh đổi prompt ảnh phải làm lại ảnh + clip. Thêm 1 lượt hỏi model.
- **Tỉ lệ khung hình & chất lượng** (⚙ Cài đặt dự án, hoặc form Dự án mới):
  - *Tỉ lệ khung hình:* Dọc 9:16 (mặc định, TikTok / Reels), Ngang 16:9 (YouTube / Facebook), Vuông 1:1. Áp dụng cho storyboard, ảnh khung đầu, clip, whiteboard và video ghép (1080×1920 / 1920×1080 / 1080×1080).
  - *Chất lượng clip:* 480p / 720p (mặc định) / 1080p — độ phân giải yêu cầu model video tạo; model không hỗ trợ mức đó thì dùng mức gần nhất. 1080p nét hơn nhưng tạo clip lâu hơn.
  - Đầu dự án hiện nhãn ▭ tỉ lệ · chất lượng. Đổi tỉ lệ sau khi đã có ảnh / clip thì nên làm lại các cảnh. Block Workflow *Video dài từ storyboard* cũng có hai ô này.
- **Kiểu dựng cảnh** (⚙ Cài đặt dự án):
  - *AI video* (mặc định): ảnh khung đầu → model video làm clip.
  - *Whiteboard vẽ tay:* mỗi cảnh, model ảnh vẽ một tranh line-art nền giấy kem (chia tối đa 4 vùng theo các câu lời dẫn). Máy bạn dựng bàn tay vẽ lần lượt từng vùng đúng lúc giọng đọc tới câu đó. Không cần model video, không tốn lượt tạo video.
    - Tuỳ chọn: *Chất lượng whiteboard* (Nhanh 1080px / Nét 1920px, lâu hơn ~3 lần), *Hiện bàn tay cầm bút*.
    - Dùng giọng AI (vai người nói từng cảnh vẫn áp dụng); ghép, phụ đề, nhạc, hậu kỳ AI như bình thường.
- **Lồng tiếng AI (bật/tắt)** (trong Cài đặt dự án, mặc định bật):
  - *Bật:* đọc lời dẫn bằng giọng máy (edge-tts) như trước.
  - *Tắt (dùng giọng nói gốc):* khi tạo clip, prompt yêu cầu nhân vật nói lời dẫn tiếng Việt ngay trong clip. Lúc ghép, app dùng tiếng gốc của từng clip, giữ nguyên tốc độ (không tua để giọng không méo) và giảm nhạc nền còn 60%.
  - Cần model video có tiếng (Grok, Veo, Muse…). Clip tạo trước khi tắt không có lời nói, nên phải làm lại clip; bấm *Ghép lại* thì chỉ lấy âm thanh sẵn có của clip.
  - Phụ đề (nếu bật) chia đều lời dẫn theo thời lượng cảnh.
- **Màn quản lý dự án** (mở Studio là thấy):
  - lưới thẻ dự án gồm ảnh, trạng thái, tên, ý tưởng, số cảnh / clip, thời lượng, tỉ lệ, ngày tạo, nút **Mở** và 🗑;
  - ô 🔍 tìm theo tên / ý tưởng; bộ lọc *Tất cả / Đang chạy / Chưa có video / Đã có video*; nút **▶ Chạy tiếp N dự án** và **+ Dự án mới**;
  - mở dự án hoặc tạo mới thì toàn màn hình dành cho dự án, nút **← Tất cả dự án** để quay lại (có thay đổi chưa lưu thì hỏi trước).
- **Màn hình dự án:**
  - đầu dự án có các nút ⧉ Nhân bản, ⚙ Cài đặt, 🗑 Xoá; dòng thông số; hàng nút chính và các công tắc (Hậu kỳ AI, Hiện Chrome);
  - **storyboard mỗi cảnh một hàng ngang**: ảnh / clip theo đúng tỉ lệ dự án │ tiêu đề, số giây, nhân vật trong khung, lời thoại (người nói | câu nói | cảm xúc | 🔊 | ✕), giọng dẫn chuyện │ prompt ảnh, prompt chuyển động, các nút ↻ Ảnh / ↻ Clip / ↑ ↓ / 🗑. Màn hình hẹp thì cột prompt xuống dưới.
- **Tiến trình** giống trang Tạo video: các bước Storyboard → Ảnh khung đầu → Clip cảnh → (Hậu kỳ AI) → Ghép video → Hoàn tất, thanh %, trạng thái hiện tại và toàn bộ nhật ký (tự cuộn). Mở lại một dự án đang chạy vẫn thấy đủ tiến trình.
- **Sửa ý tưởng để chạy lại:** bấm **✎ Sửa ý tưởng** ở đầu dự án, rồi **💾 Lưu ý tưởng** hoặc **↻ Lưu & viết lại storyboard** (thay các cảnh hiện tại).
- **⧉ Nhân bản dự án** (chép kèm cài đặt, ảnh tham chiếu, logo; không chép video hoàn chỉnh):
  - *Ảnh tham chiếu của bản sao:* hộp thoại nhân bản hiện ảnh của dự án gốc — bấm ✕ để bỏ ảnh, **+ Thêm ảnh** để thêm ảnh mới (tối đa 6). Ví dụ: nhân bản để làm cùng kịch bản cho sản phẩm khác.
  - *Chỉ ý tưởng + cài đặt:* mở sẵn khung sửa ý tưởng để viết storyboard mới.
  - *Ý tưởng + storyboard:* giữ nhân vật, phong cách, các cảnh; tạo ảnh / clip mới.
  - *Toàn bộ, kèm ảnh + clip:* làm biến thể — sửa vài cảnh, đổi giọng / nhạc / hậu kỳ rồi ghép.
- **✨ Hậu kỳ AI sau bước ghép** (công tắc lớn trong ⚙ Cài đặt dự án + nút *Hậu kỳ AI: Bật/Tắt* ở hàng nút dự án; mặc định tắt):
  - Trước khi ghép, model chat (mặc định **Claude trình duyệt**, đổi được model và profile) đọc lời dẫn từng cảnh rồi trả về:
    - từ khoá cần tô nổi, chép nguyên văn từ lời dẫn;
    - hiệu ứng âm thanh gắn vào đúng từ (pop, ding, impact, riser, whoosh…);
    - một câu *hook* ngắn cho đầu video;
    - mức nhạc nền (nhẹ / vừa / mạnh).
  - **Phụ đề nổi bật:** từ khoá tô vàng và phóng to, mỗi dòng phụ đề bật lên, hook hiện trên khung vàng 3 giây đầu. Cần bật *Phụ đề*.
  - **Âm thanh nổi bật:** hiệu ứng đặt đúng lúc đọc tới từ khoá; nhạc nền tự nhỏ lại khi có lời và to lại lúc nghỉ.
  - Model chỉ *chọn* trong lời dẫn có sẵn, không viết lại lời, nên phụ đề luôn khớp giọng. Gợi ý sai (từ không có trong lời, hiệu ứng lạ) bị bỏ qua.
  - Gợi ý được lưu trong dự án: *Ghép lại* khi lời dẫn và model không đổi thì dùng lại, không hỏi model nữa.
  - Model lỗi hoặc chưa đăng nhập thì vẫn ghép video bình thường (nhật ký ghi rõ).
  - **Kiểu hậu kỳ** (khi bật Hậu kỳ AI):
    - *Cơ bản:* phụ đề tô nổi từ khoá như trên (nhanh).
    - *HyperFrames — đồ hoạ động:* dùng [HyperFrames](https://github.com/heygen-com/hyperframes) (HeyGen, mã nguồn mở) để dựng đồ hoạ động ngay trên máy.
      - Cách làm: app ghép video chưa có phụ đề, rồi model (mặc định Claude trình duyệt) viết CSS + HTML + GSAP cho lớp phủ: phụ đề chạy chữ từng từ đúng nhịp giọng (từ khoá nổi bật), thẻ hook đầu video, dải tên sản phẩm, thẻ kết có logo. Video Studio làm lớp nền, giữ nguyên giọng, nhạc, hiệu ứng.
      - App kiểm tra thiết kế (`hyperframes lint`). Lỗi thì nhờ model sửa 1 lần; vẫn lỗi thì quay về phụ đề thường, video vẫn ra. Thiết kế dùng `Math.random`, `Date`, tải từ internet… bị chặn.
      - Thiết kế được lưu trong dự án: *Ghép lại* dùng lại; *Hậu kỳ lại (gợi ý mới)* thì thiết kế lại.
      - Cần **Node.js 22+** và **FFmpeg có ffprobe** trong PATH (Windows: `winget install Gyan.FFmpeg`). Lần đầu app tự `npm install hyperframes@0.8.170 gsap@3.15.0` vào `tools/hyperframes` trong thư mục dữ liệu và tải Chrome dùng để dựng. Telemetry của HyperFrames luôn tắt.
      - **Font tiếng Việt:** app nhúng sẵn bộ Segoe UI của Windows (thường / đậm vừa / đậm / đen) dưới tên `VA Viet`. Mọi chữ của lớp phủ dùng font này, kể cả khi model tự chọn font khác (Anton, Impact, Bebas… không có dấu tiếng Việt). Lý do: HyperFrames vốn tự đổi font hệ thống sang font Google và tải lúc dựng, dễ làm vỡ chữ có dấu. Chữ được chuẩn hoá về dạng dựng sẵn (NFC); prompt dặn model chừa khoảng cho dấu chồng (Ể, Ỗ, Ữ…) và tách theo từ. Máy không có Segoe UI thì dùng font Google *Be Vietnam Pro*.
      - Thời gian dựng khoảng 3 phút cho 1 phút video (máy 16 nhân).
    - Block **Video dài từ storyboard** trong Workflow cũng có ô *Kiểu hậu kỳ*.
  - **Hậu kỳ tiếp trên video đã xong:** thẻ *Video hoàn chỉnh* có khung Hậu kỳ AI.
    - Chưa hậu kỳ thì có nút **✨ Chạy hậu kỳ AI**: dùng lại clip đã có, chỉ chạy hậu kỳ rồi ghép lại, không tạo lại ảnh hay clip. Nút này bật luôn tuỳ chọn hậu kỳ của dự án.
    - Đã hậu kỳ thì khung hiện model, số từ tô nổi, số hiệu ứng, câu hook, kèm nút **↻ Hậu kỳ lại (gợi ý mới)** để bỏ gợi ý cũ và hỏi AI lại.
    - Khi bấm các nút này mà model lỗi, app báo lỗi rõ và giữ nguyên video cũ (không ghép lại vô ích).
- **Ràng buộc prompt** (Cài đặt dự án; áp cho ảnh khung đầu và clip):
  - *Cấm trong hình:* tick từng mục — không chữ, không phụ đề, không logo, không watermark (mặc định tick cả 4, như trước). Ô *Cấm thêm* nhận câu tiếng Anh tuỳ ý (VD: `no extra fingers`). Bỏ tick hết và để trống thì prompt không có câu cấm. App hiện sẵn câu sẽ gửi để xem trước.
  - *Logo thương hiệu:* bỏ tick **Không logo** thì hiện ô **Tải logo lên** (nên dùng PNG nền trong suốt).
    - Logo được gửi kèm model ảnh như ảnh tham chiếu cuối cùng, kèm lời dặn vẽ đúng logo ở chỗ hợp lý (bao bì, biển hiệu, đồng phục). Clip giữ logo vì chạy từ ảnh khung đầu. Ảnh đã tạo trước đó phải bấm ↻ Ảnh.
    - Tuỳ chọn **Đóng logo lên video khi ghép** (4 góc): đóng logo thật, chính xác 100%, lên video hoàn chỉnh; áp dụng khi ghép hoặc *Ghép lại*.
    - Tick lại **Không logo** thì app bỏ qua logo (file vẫn giữ trong dự án).
  - *Câu mô tả ảnh tham chiếu:* bật/tắt câu "Reference images are attached in this order — image 1 = reference image: …", và sửa được phần vai trò ảnh (mặc định `use it as a visual reference for subject, style and composition`).
- **Lời thoại trong clip:** khi tạo clip từng cảnh, prompt gửi model video luôn kèm dòng *Dialogue* chứa nguyên văn **Lời đọc** của cảnh, cùng kiểu giọng theo vai.
  - *Lồng tiếng AI:* nhân vật mấp máy môi và làm cử chỉ theo đúng câu đó; lúc ghép, tiếng của clip được thay bằng giọng đọc.
  - *Giọng gốc:* nhân vật nói to, rõ, đúng nguyên văn câu đó.
  - Cảnh không có lời đọc thì không có dòng thoại.
  - **Khoá nhân vật trong clip** (mọi model video, nhất là Muse): đầu prompt clip luôn có đoạn IDENTITY LOCK (giữ nguyên khuôn mặt, màu da, tuổi, kiểu tóc từ khung đầu, không vẽ lại / đổi mặt) kèm mô tả từng nhân vật. Muse được dặn tạo video trực tiếp từ đúng ảnh khung đầu và chép nguyên văn đoạn khoá.
  - **Giữ nguyên trang phục** (⚙ dự án, mặc định bật): bật → trang phục giống nhau mọi cảnh; tắt → trang phục đổi theo mô tả từng cảnh, khuôn mặt vẫn khoá (làm lại ảnh khung đầu để áp dụng).
  - **Chạy nhiều Chrome song song:** số clip tạo cùng lúc = Cài đặt → Số video tạo song song (tối đa 10), nhưng mỗi profile chỉ mở 1 Chrome. Muốn 3 Chrome cho Muse thì cần 3 profile đã đăng nhập Muse và gán cho Muse, và ⚙ dự án để “Tự chọn profile rảnh”. Nhật ký báo số Chrome thực chạy và lý do nếu chỉ chạy lần lượt.
  - **Tiến trình:** thanh tiến trình theo % thật của mọi clip đang tạo song song (vd. “Clip: 3/10 xong · đang tạo 2 (cảnh 4 62%, cảnh 5 30%) · 5 chờ Chrome rảnh”); bước ghép nối tiếp từ 72% thay vì tụt về đầu.
  - Nên để lời đọc vừa với số giây của cảnh (khoảng 2,5 từ/giây) để model nói kịp. App ước lượng thời gian nói hết lời của từng cảnh:
    - storyboard / lưu cảnh chưa có clip: tự tăng số giây lên mức model video hỗ trợ đủ để nói hết câu;
    - lời dài hơn clip dài nhất của model: cảnh hiện ⚠ và nhật ký nhắc rút gọn lời hoặc tách cảnh;
    - prompt clip không còn cắt lời thoại giữa câu, và dặn model nói hết mọi câu trước khi clip kết thúc.
- **Giọng người nói theo nhân vật** (mỗi cảnh, ô *Giọng người nói*): người dẫn chuyện nữ/nam, bé gái, bé trai, cô gái trẻ, chàng trai trẻ, phụ nữ / đàn ông trung niên, bà cụ, ông cụ.
  - Khi viết storyboard, model tự chọn vai cho từng cảnh; bạn đổi tay được, và bấm 🔊 để nghe thử lời đọc.
  - *Lồng tiếng AI:* edge-tts tiếng Việt chỉ có 1 giọng nữ và 1 giọng nam, nên app chỉnh cao độ và tốc độ theo vai. Ví dụ: trẻ em cao giọng và nhanh hơn; người già trầm và chậm hơn. Đổi vai không phải làm lại clip.
  - *Giọng gốc:* prompt clip dặn model video nói bằng đúng kiểu giọng đó (ví dụ giọng bé gái khoảng 7 tuổi). Đổi vai hoặc lời dẫn thì clip cảnh đó phải làm lại.
- **Chuyển cảnh khi ghép** (trong Cài đặt dự án):
  - *Kiểu chuyển cảnh:* hoà trộn, mờ qua đen, loé trắng, tan hạt, trượt trái/lên, lướt mượt, lau ngang, mở vòng tròn, quét kim đồng hồ, phóng to, nhoè, vỡ điểm ảnh, mở cửa dọc, cắt thẳng, hoặc **Ngẫu nhiên** (mỗi lần một kiểu, không lặp kiểu liền trước).
  - *Thời lượng:* 0,3–1 giây.
  - *Âm chuyển cảnh:* whoosh, swoosh, riser, pop, click, impact, ding, ngẫu nhiên hoặc không có. Âm do app tự tạo nên không cần file; nút 🔊 để nghe thử.
  - Chỉnh được âm lượng.
  - Mốc thời gian từng cảnh giữ nguyên, nên giọng đọc và phụ đề không bị lệch.
  - Block **Ghép video** trong Workflow có cùng các tuỳ chọn này (mặc định cắt thẳng, không âm, như trước).

Dự án lưu ở `<thư mục video>/_studio/<id>/` (`project.json`, `refs/`, `scenes/NN/frame.png`, `clip.mp4`).

## Studio Muse AI (menu trái → Studio Muse AI)

Dây chuyền chỉ dùng Muse (muse.ai), theo mô hình nhiều tài khoản chạy song song. Thanh trên có:
- chọn dự án + nút **Dự án** (thêm, đổi tên, tạm dừng, xoá);
- trạng thái tài khoản;
- **Chạy tiếp / Dừng tất cả / Thư mục**.

Có 5 tab:

- **Studio** — soạn lệnh và quản lý hàng đợi:
  - Tạo ảnh / Tạo video, tỉ lệ khung hình, chèn mẫu prompt, lưu làm mẫu.
  - Mỗi khối prompt cách nhau 1 dòng trống là 1 task.
  - Ảnh tham chiếu dùng chung cho mọi prompt, hoặc ghép cặp (ảnh i ↔ prompt i).
  - Công tắc Người mẫu cố định / Ảnh luân phiên. Gõ tên nhân vật trong prompt thì app tự gắn ảnh nhân vật. Muse nhận tối đa 3 ảnh mỗi lệnh.
  - Hàng đợi có tìm kiếm, lọc theo trạng thái, Chọn tất cả / Chọn lỗi / Chọn chưa chạy, Chạy lại / Huỷ / Xoá. Bấm vào task để xem prompt, ảnh gắn kèm, lỗi, nhật ký và file kết quả.
- **Tư liệu** — nhân vật (≤ 3 ảnh), mẫu prompt, người mẫu cố định (gắn vào mọi task, ≤ 3 ảnh), ảnh luân phiên (mỗi task lấy 1 ảnh kế tiếp, ≤ 20 ảnh). Ảnh được chép vào kho riêng, nên đổi hay xoá file gốc không ảnh hưởng.
- **Kịch bản** — mỗi dòng là 1 cảnh, cách 1 dòng trống để sang video tiếp theo. Chế độ "Từ ảnh": mỗi ảnh sản phẩm thành 1 video, với các gợi ý chuyển động zoom / xoay 360° / trượt ngang / khói sương.
  - **Cách làm:** làm video thẳng; Storyboard → tự làm video (Muse vẽ ảnh storyboard rồi dựng video theo đúng thứ tự khung); Storyboard → chờ duyệt (bấm "✓ Duyệt storyboard" rồi mới làm video).
  - **Thời lượng:** 10–60 giây gộp 1 lệnh, hoặc từng cảnh 10 giây gửi lần lượt rồi app tự ghép.
  - **Tuỳ chọn khác:** tiền tố câu lệnh; giọng đọc (không lồng tiếng / nhân vật tự nói khớp môi / giọng nam, nữ); người dẫn nam / nữ; nhân vật dẫn lấy từ Tư liệu; số bản cho mỗi video; ảnh sản phẩm (mỗi ảnh ra 1 bộ video riêng).
  - **Nhạc nền:** video xong thì app lấy ngẫu nhiên 1 bài trong thư mục nhạc nền, lót nhỏ dưới giọng đọc, và giữ cả bản không nhạc.
  - **Ảnh sản phẩm:** kéo thả vào ô hoặc bấm "Chọn ảnh" (PNG / JPG / WEBP, tối đa 20MB mỗi ảnh).
  - **Danh sách video:**
    - lọc theo Chờ / Đang làm / Xong / Lỗi;
    - bảng hiện từng bước của mỗi video (SB / C1 / C2…);
    - bấm 1 video để xem chi tiết bên phải: video kết quả, các cảnh, trạng thái từng bước, nút Duyệt, nút Chạy lại phần lỗi.
  - **Thanh dưới:** Chọn tất cả, Xoá đã chọn, Xoá hết, Dừng, Bắt đầu render. Bấm "Xem lệnh sẽ gửi Muse" để xem trước nội dung.
- **Tiến trình** — theo dõi trực tiếp mọi việc Muse đang làm, của dự án đang mở hoặc tất cả dự án:
  - **Chỉ số:** đang chạy / số luồng, đang chờ, xong và lỗi hôm nay, thời gian trung bình.
  - **Mỗi tài khoản:** việc đang làm, với đồng hồ chạy, thanh tiến độ ước tính (theo thời gian trung bình 20 lượt gần nhất), dòng nhật ký mới nhất và nút Huỷ.
  - **Sắp chạy:** các việc kèm lý do đang chờ (chờ luồng trống, chờ storyboard, chờ duyệt, hàng đợi dừng, hết tài khoản rảnh).
  - **Vừa xong:** thời gian từng việc mất, nút mở file hoặc chạy lại.
  - Bấm vào một việc để xem chi tiết.
- **LadiPage:**
  - Dán link landing page: app đọc tên sản phẩm, ảnh, giá và chữ trên trang. Nội dung trang chỉ được dùng làm dữ liệu.
  - Muse viết 3 kịch bản phân cảnh, mỗi cảnh có lời thoại và mô tả hình. Có tuỳ chọn "Không đọc giá".
  - Bạn chọn 1–3 ảnh sản phẩm (gửi kèm mọi video), sửa từng cảnh, xem trước lệnh, rồi đưa các kịch bản đã tích vào hàng đợi. Cách làm, tỉ lệ, thời lượng và giọng đọc lấy theo tab Kịch bản.
- **Video mẫu** — tạo video tương tự một video mẫu (`app/muse_sample.py`):
  1. Chọn file video trên máy hoặc dán link (TikTok / YouTube / Facebook… qua yt-dlp). Máy tự cắt các khung đổi cảnh, ghép ảnh lưới có mốc giây, đo thời lượng, tỉ lệ, số lần cắt cảnh, độ dài mỗi cảnh; nếu link có phụ đề / mô tả thì lấy luôn. Bước này **không tốn lượt Muse**.
  2. Nhập **Nội dung mới** (đổi sản phẩm, thông điệp, đối tượng…). Có thể dán lời thoại video mẫu, chọn mức bám (Bám sát / Lấy ý tưởng), số kịch bản (1–3), số cảnh.
     - Đính kèm tối đa 2 ảnh sản phẩm / nhân vật: gửi kèm Muse và mọi video.
     - Đính kèm tối đa 5 tài liệu (.txt .md .csv .json .docx .srt .vtt): thông tin sản phẩm, kịch bản thô…
  3. Bấm "Muse phân tích & viết kịch bản": Muse xem ảnh lưới và ảnh sản phẩm **1 lần**, trả về bản phân tích video mẫu (hook, cấu trúc theo giây, nhịp, phong cách) và các kịch bản mới sửa được từng cảnh.
     - Nội dung video mẫu và tài liệu chỉ được dùng làm dữ liệu.
     - Muse không chép nguyên văn lời thoại, thương hiệu, khuôn mặt người thật, và không bịa công dụng hay số liệu.
  4. Tỉ lệ và thời lượng lấy gần với video mẫu; cách làm, giọng đọc, nhạc nền theo tab Kịch bản. Xem lệnh rồi đưa vào hàng đợi.
- **Hậu kỳ** — ghép các video tự chọn thành 1 video hoàn chỉnh, cùng bộ hậu kỳ với Studio (`app/muse_post.py`):
  - Thêm video **từ Thư viện** (tick theo thứ tự) hoặc **từ máy**, sắp xếp ↑↓, mỗi cảnh nhập lời đọc / lời thoại.
  - Âm thanh: **Lồng tiếng AI** (edge-tts, giọng + tốc độ, nghe thử; clip tự kéo dài / tua nhẹ cho khớp lời) · **Giữ tiếng gốc** (nhạc nền tự nhỏ lại) · **Không lời**.
  - Phụ đề (từ lời đã nhập), nhạc nền + âm lượng (thư mục nhạc của Studio Muse AI, không có bài thì dùng thư mục ở Cài đặt).
  - Chuyển cảnh: kiểu, thời lượng, âm chuyển cảnh (nghe thử) + âm lượng — giống Studio.
  - ✨ Hậu kỳ AI: Muse chọn từ khoá tô nổi, hiệu ứng âm thanh, hook, mức nhạc; kiểu **HyperFrames** dựng đồ hoạ động trên máy (cần Node.js 22+). Muse / HyperFrames lỗi thì vẫn ghép bình thường.
  - Chạy nền lần lượt, có tiến độ %, nhật ký, nút Dừng. Video xong hiện ở "Video hậu kỳ đã làm" và trong Thư viện video.
- **Storyboard dài** — Studio storyboard nhiều cảnh (lồng tiếng, phụ đề, ghép), mọi bước khoá dùng Muse.
- **Thư viện** — file kết quả của dự án đang mở. Tick các video rồi bấm **Ghép video**: sắp thứ tự ↑↓, đặt tên file, có thanh tiến độ %. Ghép xong, app mở Explorer chọn sẵn file.
- **Tài khoản:**
  - Tài khoản chính là các **profile trình duyệt đã gán Muse** ở màn Profile trình duyệt (dùng lại phiên đã đăng nhập). Bấm "＋ Thêm tài khoản" sẽ mở màn đó.
  - Thiết lập: số TK chạy đồng thời, tổng luồng, số luồng / tài khoản (1–5), cách chia việc **Luân phiên** (ít việc nhất → dùng ít hạn mức nhất) hoặc **Lần lượt**, giới hạn phút cho ảnh / video, số lần tự thử lại.
  - **Hạn mức tuần:** % đã dùng, ngày đặt lại và token bổ sung còn lại. App đọc từ trang muse.ai đã đăng nhập, chỉ đọc nên không tốn lượt.
  - Tài khoản hết hạn mức tự nghỉ tới ngày đặt lại, trừ khi bật "Dùng token bổ sung" hoặc "vẫn tạo tiếp".

Cách chạy:
- Task lỗi tự thử lại (mặc định 1 lần).
- Lỗi do hết hạn mức hoặc tài khoản đăng xuất thì task được xếp hàng lại (không tính lượt) và chuyển sang tài khoản khác.
- Tắt app khi đang chạy: task dở được xếp hàng lại.
- File lưu ở `<thư mục video>/_muse_hub/<dự án>/`.
- Dữ liệu (cài đặt, task, tư liệu) lưu trong thư mục dữ liệu app, mục `muse_hub/`.

## Chiến dịch — phòng marketing AI (sidebar → nhóm CHIẾN DỊCH)

Phòng marketing có 6 vai trò AI chạy theo dây chuyền 0 → 8 (thay cho lệnh `/marketing`). Thư mục mỗi chiến dịch là `<thư mục video>/_campaigns/<YYYY-MM-DD>-<slug>/`. Tên file bàn giao giữ đúng như bộ công cụ cũ: `00-brief.md`, `01-y-tuong.md`, `02-chon-y-tuong.md`, `03-content.md/.html/.pdf`, `04-chon-content.md`, `05-hinh-anh/c1-a.png, c1-b.png`, `05-hinh-anh.html`, `07-video/video.mp4` + `07-video.html` (nếu có video), `06-danh-gia.md`, `08-dang-bai/ke-hoach-dang.md`, `08-dang-bai/da-dang.md` và `bao-cao.md`.

**Trước khi chạy:**
- Nhập khoá Anthropic và/hoặc OpenAI ở **Thư viện chiến dịch → Vai trò AI** (hoặc đặt biến môi trường `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`). Chỉ cần khoá của nhà cung cấp mà các vai trò đang dùng. OpenAI dùng được luôn khoá OpenAI trong **Cài đặt**. Khoá chỉ lưu trên máy và không gửi về giao diện.
- Model tạo ảnh / tạo video dùng trình duyệt (ChatGPT, Grok, Gemini, Dola) cần đăng nhập trong **Profile trình duyệt**; model dùng API key cần khoá trong **Cài đặt**.
- Kết nối Fanpage ở mục **Fanpage Facebook**.

**Các trang:**

| Trang | Chức năng |
|---|---|
| **Tạo chiến dịch** | Nhập mô tả, sản phẩm (từ thư viện hoặc nhập mới; giá/mã/khuyến mãi để trống thì không tự bịa), link web, ảnh sản phẩm, ảnh tham chiếu và người mẫu (upload hoặc chọn từ thư viện; WEBP tự đổi sang PNG). Tuỳ chọn: phong cách nhân vật, *Tôi tự chọn ý tưởng*, *Không đăng*, Fanpage, **model tạo ảnh** (mặc định theo trang Tạo hình ảnh) + profile, *Có video* + **loại video** (Video bán hàng / Video AI từ ảnh) + kiểu + profile. |
| **Danh sách chiến dịch** | Số liệu nhanh, lọc theo trạng thái/sản phẩm/ngày, tìm theo tên. Bấm vào một chiến dịch để mở trang chi tiết, xem bảng dưới. |
| **Thư viện chiến dịch** | Sản phẩm (kèm mô tả nhãn để so nhãn), ảnh tham chiếu có thẻ, người mẫu, phong cách nhân vật, mẫu content, 6 vai trò AI. Với mỗi vai trò chỉnh được model, effort và system prompt; prompt có lưu phiên bản cũ. |
| **Lịch sử & chi phí** | Bài đã đăng (ai bấm đăng, lúc nào, link), chi phí theo chiến dịch, nhật ký từng lần gọi AI (vai trò, model, token, giây, chi phí). |

**Trang chi tiết chiến dịch** có:
- thanh 12 chặng, mỗi chặng ở một trong các trạng thái chờ / đang chạy / xong / lỗi / chờ bạn / bỏ qua;
- nhật ký chạy trực tiếp;
- tab Brief, 5 ý tưởng, Content (sửa trực tiếp hoặc viết lại, mở PDF), Ảnh (vẽ lại đúng ảnh đó, xem prompt, model và kết quả so nhãn; xem video và **Làm lại video**), Thông tin web, Đánh giá, Đăng bài, Báo cáo;
- nút Chạy tiếp, Huỷ, Chạy lại từ chặng X, Nhân bản, Thư mục, Tải ZIP.

**Quy trình tự động (ảnh, video, Fanpage, quảng cáo):**
- **Chặng 5 · Kế hoạch nội dung theo Fanpage.** Trưởng phòng nhận danh sách page (tên, danh mục, lượt theo dõi) và danh mục tài nguyên của app. Từ đó trưởng phòng lập kế hoạch: chỉ đạo 2 ảnh quảng cáo, từ khoá Pinterest, ảnh studio, poster (khi hợp ngành hàng và model vẽ được chữ), và tối đa 2 video.
- **Chặng 6 · Ảnh** (hàng đợi **Tạo hình ảnh**, các ảnh chạy song song):
  - Mỗi ảnh quảng cáo tạo 2 phương án; trưởng phòng xem ảnh thật rồi chọn 1.
  - Thêm *Ảnh sản phẩm studio* và *Poster nông nghiệp*, làm bằng template ảnh của hệ thống.
  - Không có ảnh tham chiếu thì tự lấy ảnh tham khảo từ **Pinterest**.
  - Mọi ảnh vào thư viện ảnh, rồi được chép về `05-hinh-anh/`; các phương án lưu là `<ảnh>-pa1.png`, `<ảnh>-pa2.png`.
- **Chặng 6b · Video** (hàng đợi **Tạo video**, các video chạy song song). Loại video do trưởng phòng chọn hoặc bạn chỉ định:
  - **Video bán hàng:** brand là tên Fanpage, cảnh mở đầu trả lời câu hỏi khách, có giọng đọc, phụ đề, giá.
  - **Video kiến thức:** thể loại Giải thích / Top / Kể chuyện.
  - **Video AI theo template ngành hàng:** AI tự điền biến, tự gắn ảnh sản phẩm / nhân vật / ảnh chiến dịch.
  - **Video AI từ ảnh (Grok):** qua template ẩn `templates/sales/anh-thanh-video`.
  - Video lưu ở `07-video/v1.mp4`, `v2.mp4`.
- **Chặng 7b · Kế hoạch đăng theo từng page:**
  - Mỗi page 1–3 bài khác nhau: album, video hoặc ảnh đơn, caption viết riêng.
  - Khi bật *Hẹn giờ đăng*, NV đăng bài rải bài vào khung giờ vàng trong N ngày. Facebook chấp nhận giờ hẹn từ 20 phút đến 28 ngày tới.
- **Chặng 7c · Đăng:** vẫn **chỉ khi bạn xác nhận 2 lần**. Bạn sửa được page, caption và giờ đăng của từng bài. Bài có giờ hẹn thì Facebook tự đăng đúng giờ.
- **Quảng cáo** (khi bật *Tạo quảng cáo sau khi đăng*):
  - Sau khi đăng, ứng dụng tạo quảng cáo cho bài tốt nhất mỗi page qua **Quảng cáo Facebook**: video tối ưu lượt xem (ThruPlay), ảnh tối ưu tương tác.
  - Quảng cáo luôn ở trạng thái **TẠM DỪNG**; bạn bật ở trang Quảng cáo.
  - Bài hẹn giờ chưa lên trang nên chưa tạo quảng cáo được; tạo sau ở trang Quảng cáo.
- Trưởng phòng yêu cầu vẽ lại ảnh thì video tự làm lại theo ảnh mới. Huỷ chiến dịch thì huỷ luôn tác vụ ảnh/video đang chờ. Chạy lại sau lỗi thì bỏ qua ảnh/video đã xong (`tien-do.md`).

**Quy tắc ứng dụng tự áp dụng:**
1. Các chặng chạy lần lượt; chặng sau chỉ chạy khi đã có file bàn giao của chặng trước.
2. Trưởng phòng ra **CAN SUA** thì ứng dụng giao lại đúng nhân viên bị nêu tên, **tối đa 1 vòng sửa**. Sau đó ứng dụng dừng, và bạn chọn *Tôi đã xem — cho đi tiếp* hoặc *Chạy lại từ chặng…*. Không đọc được phán quyết thì **không** coi là duyệt.
3. Ảnh:
   - tạo bằng model chọn khi tạo chiến dịch, và ảnh sản phẩm luôn là ảnh mẫu đầu tiên;
   - bắt buộc có người;
   - chữ quảng cáo do model ảnh vẽ luôn khi model vẽ chữ tiếng Việt tốt (GPT Image, ChatGPT, Gemini / Nano Banana); model khác (Grok, Dola) thì ảnh không có chữ;
   - khung dọc 9:16;
   - tạo xong thì so nhãn với ảnh sản phẩm thật.
4. Không có ảnh tham chiếu (không upload, thư viện trống) thì lấy ảnh tham khảo Pinterest theo từ khoá trưởng phòng đặt.
5. **Không bao giờ tự đăng**: chặng 7c chỉ chạy khi bạn đánh dấu bài/Fanpage, bấm **Đồng ý đăng…** rồi xác nhận lần 2. Ứng dụng ghi lại ai đồng ý và lúc nào.
6. Không xoá hay ghi đè: chạy lại từ chặng X tạo **phiên bản mới**. Sửa content, vẽ lại ảnh hoặc làm lại video thì bản cũ được cất vào `_cu/`.
7. Chặng lỗi tự chạy lại 1 lần và bỏ qua phần đã xong (dựa vào `05-hinh-anh/tien-do.md`).
8. Nội dung đọc từ web chỉ là dữ liệu. Ứng dụng chỉ đọc trang cùng tên miền với link bạn đưa.

**AI:**
- Trưởng phòng và NV content dùng `claude-opus-5-5`; NV ý tưởng, NV hình ảnh và NV đăng bài dùng `claude-sonnet-5-5`. Có thể đổi trong Vai trò AI, kể cả sang model OpenAI (`gpt-5`, `gpt-5-mini`, `gpt-5-nano` — gọi qua Responses API). Model `gpt-*` gọi OpenAI, còn lại gọi Claude.
- NV ý tưởng được bật web search (Claude: web search + web fetch; OpenAI: web search).
- Với Claude có bật fallback phía server: nếu bộ lọc an toàn từ chối, API tự chạy lại trên model dự phòng. OpenAI không có cơ chế này.
- System prompt lấy từ `D:\00_DuAnTest\maketing\.claude\agents\<vai-tro>.md` (đã bỏ frontmatter), mẫu content từ `.claude\mau-content.md`.

## File phụ đề .srt kèm video

Mọi video ghép xong (Tạo video, Studio, SRT Whiteboard) đều có thêm file **`final.srt`** cạnh `final.mp4` trong thư mục video, kể cả khi không chèn phụ đề vào hình. Dùng file này để tải phụ đề lên YouTube / Facebook hoặc sửa tay. Block Workflow *Whiteboard* lưu thêm file `video.srt`.

## Ảnh đính kèm khi dùng model trình duyệt

Với ChatGPT, Gemini, Grok, Dola, Muse:
- **Xác minh trước khi gửi:** app kiểm tra ảnh tham chiếu đã thật sự hiện trong khung soạn, rồi chờ hết vòng xoay tải lên mới gửi prompt.
- **Thử cách khác:** ảnh không hiện thì app thử lần lượt các ô tải file khác, rồi tới nút ＋ / Đính kèm của trang.
- **Dừng thay vì gửi trơn:** vẫn không đính kèm được ảnh nào thì app báo lỗi và **không gửi prompt**. Gửi trơn sẽ khiến model đòi ảnh hoặc tạo sai người, sản phẩm, lại tốn lượt.
- **Đính kèm thiếu:** chỉ được một phần thì nhật ký cảnh báo "Chỉ đính kèm được x/y ảnh".
- **Ảnh trùng nhau:** trước khi gửi, app so **nội dung** các ảnh (không so tên file). Ví dụ ảnh ⭐ của nhân vật trùng ảnh mẫu layout / dàn cảnh, hoặc ảnh dự án trùng ảnh nhân vật: chỉ gửi 1 lần, vai trò của các ảnh trùng được gộp vào câu mô tả thứ tự ảnh. Logo luôn giữ vị trí cuối. Nhật ký ghi "Bỏ ảnh đính kèm trùng…". Áp dụng cho tạo ảnh (Studio, Nhân vật & Layout, Tạo hình ảnh) và tạo video.

## Khi model đề xuất phương án khác (Muse, ChatGPT)

Đôi khi model trình duyệt không tạo ảnh / video mà **đề xuất phương án khác hoặc hỏi lại**, ví dụ "Ảnh cảnh 4 không tạo được… Chị muốn em làm một trong hai phương án đó không?". App nhận ra khi model trả lời bằng chữ, chưa có ảnh / video và câu trả lời đã đứng yên. Cách xử lý chọn ở **⚙ Cài đặt → Khi model trình duyệt đề xuất phương án khác**:
- **Hỏi tôi** (mặc định): hiện form duyệt trên mọi màn hình, gồm lời model nói và các lựa chọn:
  - **✅ Đồng ý đề xuất**: model làm theo phương án nó vừa đưa ra; nhiều phương án thì chọn phương án đầu;
  - **✍ Gửi trả lời khác**: ví dụ "làm phương án 2", "bỏ cảnh lửa"…;
  - **✖ Dừng tác vụ**.

  Tick *Lần sau tự đồng ý* để chuyển sang chế độ tự đồng ý. **Không ai trả lời sau 3 phút thì tự đồng ý**, để chạy hàng loạt / chạy đêm không bị kẹt. Nhiều tác vụ cùng hỏi thì form xếp hàng.
- **Tự đồng ý đề xuất**: trả lời đồng ý ngay, ghi vào nhật ký.

Mỗi yêu cầu trả lời đề xuất tối đa 2 lần. Áp dụng cho Muse (ảnh, video) và ChatGPT (ảnh).

## Giọng đọc (edge-tts)

Dịch vụ đọc miễn phí của Microsoft đôi khi lỗi theo đợt ("No audio was received" dù tham số đúng). Cách app xử lý:
- tự thử lại tối đa 6 lần, giãn cách tăng dần (~30 giây);
- chỉ chạy tối đa 3 lệnh đọc cùng lúc;
- câu không có chữ để đọc (emoji, ♪, dấu câu) được thay bằng khoảng lặng ngắn.

Vẫn lỗi thì thường do mạng hoặc dịch vụ đang trục trặc; thử lại sau ít phút.

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

## SRT Whiteboard animation

Template **SRT Whiteboard animation** (nhóm Giáo dục) biến phụ đề `.srt` hoặc một đoạn kịch bản thành video minh hoạ vẽ tay kiểu bảng trắng. Bàn tay vẽ lần lượt từng ý đúng lúc lời đọc tới.

Bộ dựng là [srt-whiteboard-animation](https://github.com/geeklee/srt-whiteboard-animation) (geeklee, giấy phép MIT), chạy ngay trên máy.

**Cài đặt bộ dựng**
- Cần **Python 3** trên máy.
- Lần đầu dựng, app tự làm các bước sau:
  - tải đúng bản đã ghim (commit `696a724`) vào `tools/srt-whiteboard` trong thư mục dữ liệu;
  - tạo môi trường riêng `.venv` và cài opencv-python, numpy, av, Pillow (~1 phút).

**Cách làm**
1. Ở **Tạo video**, chọn template *SRT Whiteboard animation*.
2. Dán nội dung SRT, hoặc bấm **Mở file .srt…** để nạp và sửa ngay trong ô.
   - Có thể dán kịch bản thường. Khi đó giọng AI đọc và app tự tạo mốc phụ đề theo từng từ.
3. Phụ đề được gom thành cảnh khoảng 10 giây (tối đa 16 giây). Mỗi cảnh:
   - model ảnh đã chọn vẽ **một** tranh line-art: nền giấy kem `#F5EBD7`, nét xám đậm, chỉ điểm màu đỏ / cam / xanh, **không chữ**;
   - tranh chia tối đa 4 vùng, mỗi vùng ứng với một nhóm câu, xếp trái → phải (dọc 9:16 thì trên → dưới);
   - app dò vùng nét vẽ trên ảnh, rồi bộ dựng cho bàn tay vẽ từng vùng đúng mốc của câu tương ứng.
4. Ghép các cảnh, giữ nguyên mốc SRT, thêm tiếng và phụ đề.

**Tự tạo SRT** (khi chỉ có kịch bản)
- Dán kịch bản rồi bấm **📝 Tạo SRT từ kịch bản**. Giọng AI (mục *Giọng đọc* / *Tốc độ đọc*) đọc cả bài để lấy mốc thời gian.
- Ô nhập đổi thành SRT, chia theo câu gốc, giữ dấu câu; câu dài được cắt ở dấu phẩy hoặc chia đôi. Bạn sửa chữ được.
- File giọng đọc vừa tạo được gắn sẵn làm *Âm thanh lời đọc*, nên video khớp đúng mốc.
- **💾 Lưu .srt** để lưu phụ đề ra file.

**Tiếng**
- Có file âm thanh đính kèm (khớp SRT): dùng nguyên file đó.
- Không có: giọng AI (mục *Giọng đọc* / *Tốc độ đọc*) đọc từng câu đúng mốc.

**Tuỳ chọn:** tỉ lệ 16:9 / 9:16 / 1:1, chất lượng dựng (Nhanh 1080px / Nét 1920px), gợi ý phong cách hình, hiện bàn tay cầm bút, chèn phụ đề.

**Thời gian:** máy dựng mất khoảng 3–5 giây cho mỗi giây video ở chế độ Nhanh, chưa tính thời gian model vẽ ảnh.

Cùng bộ dựng này có ở **Studio** (Kiểu dựng cảnh → *Whiteboard vẽ tay*) và block Workflow **✍ Whiteboard từ SRT / kịch bản**.

## Template video AI (Grok hoặc Gemini Veo)

Template loại `ai_video` không dựng hình bằng HTML. Thay vào đó, app gửi prompt cho AI tạo video. Mọi template dùng được với cả 3 engine.
Engine được chọn theo **Provider AI** đang dùng:

| Provider AI | Engine | Thời lượng | Độ phân giải | Ảnh tham chiếu |
|---|---|---|---|---|
| Grok Browser | Grok Imagine (grok.com/imagine) | 6/10/15s | 480p/720p/1080p | tối đa 10 |
| Gemini Browser · **Veo** (mặc định) | Công cụ "Tạo video" (Veo) trong gemini.google.com. Nếu tài khoản không có Veo (cần gói Google AI Pro/Ultra), app **tự chuyển sang video thông thường** | 8s | 720p | 3 (nhật ký báo nếu Gemini nhận thiếu) |
| Muse Browser (Meta) | Nhờ trợ lý Muse của Meta (muse.ai, Muse Video) tạo video trong khung chat. Cần gán Muse cho một profile ở **Profile trình duyệt** rồi bấm **Đăng nhập**. Muse Video đang mở dần: tài khoản chưa có thì app báo lỗi rõ. Cùng model này có ở **Tạo hình ảnh** (Muse Image). | 5s / 10s | 720p | 3 |
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

## Trợ lý quảng cáo Meta (sidebar → Trợ lý quảng cáo)

Chat với AI để lên quảng cáo cho một bài viết có sẵn của Fanpage. Dùng chung token và quyền (`ads_read`, `ads_management`) với **Quảng cáo Facebook**.

- **Hai màn (giống Studio):**
  - **Quản lý chiến lược:** thống kê (chờ duyệt / đã lên lịch / đang chạy / tạm dừng / lỗi, ngân sách/ngày đang chạy), tìm kiếm, lọc theo trạng thái, lưới thẻ chiến lược (ảnh bài viết, mục tiêu, ngân sách × ngày, tổng tối đa, đối tượng, người duyệt). Mỗi thẻ: Mở / Duyệt, ↗ Ads Manager, ⧉ Nhân bản, 🗑 Xoá (quảng cáo đã tạo trên Meta không xoá ở đây).
  - **Bàn làm việc:** “← Tất cả chiến lược” + tên chiến lược; chat bên trái, form bên phải chia mục 1 Bài quảng cáo · 2 Mục tiêu & ngân sách · 3 Đối tượng · 4 Chiến lược của trợ lý; thanh duyệt dính đáy hiện tổng chi tiêu và các nút duyệt.
- **Chat:** chọn model (ChatGPT / Claude / Gemini / Muse trình duyệt hoặc API key), profile và tuỳ chọn hiện Chrome. Mô tả sản phẩm, khách hàng, khu vực, ngân sách, mục tiêu; có sẵn vài câu gợi ý nhanh.
  - Model đọc các bài gần đây của Fanpage, trả lời, giải thích lý do và **tự điền form**. Mỗi câu trả lời ghi rõ các trường đã điền.
  - Sở thích model gợi ý được tra thành sở thích thật của Meta và chọn sẵn kết quả đầu tiên. Bạn bỏ / thêm sở thích, hoặc tự tìm.
  - Kèm chiến lược và kết quả dự kiến (chỉ là ước lượng của AI).
- **Form:**
  - tài khoản quảng cáo, Fanpage, bài viết (có xem trước), mục tiêu, tên chiến dịch;
  - ngân sách/ngày, số ngày, giờ bắt đầu, quốc gia, độ tuổi, giới tính, sở thích;
  - dòng tổng hiện chi tiêu tối đa = ngân sách × số ngày. Mọi thay đổi được lưu ngay.
- **Duyệt:** bấm **📨 Gửi duyệt** (app kiểm tra đủ tài khoản, page, bài, ngân sách), rồi chọn một trong ba cách:
  - **⏸ Tạo (tạm dừng):** tạo chiến dịch nhưng không tiêu tiền. Bạn tự bật trong Ads Manager hoặc màn Quảng cáo Facebook;
  - **🗓 Lên lịch chạy:** Meta tự chạy đúng giờ bắt đầu (giờ phải ở tương lai, tối đa 180 ngày);
  - **▶ Chạy ngay:** chạy sau vài phút, khi Meta duyệt xong nội dung.
- **An toàn tiền:**
  - AI chỉ đề xuất, không bao giờ tự chạy quảng cáo;
  - lên lịch và chạy ngay đều phải tick xác nhận chi phí trong hộp thoại, và backend từ chối nếu thiếu xác nhận;
  - app ghi lại người duyệt và thời điểm;
  - sửa form sau khi đã gửi duyệt sẽ đưa bản nháp về trạng thái nháp.
- Sau khi tạo: bản nháp bị khoá, hiện mã chiến dịch / nhóm / quảng cáo, kèm nút **Mở Ads Manager** và **Xem ở Quảng cáo Facebook**.
- Bản nháp lưu trong thư mục dữ liệu app (`%APPDATA%/<app>/ad_assistant/` hoặc `~/.videoagent/ad_assistant/`).

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
