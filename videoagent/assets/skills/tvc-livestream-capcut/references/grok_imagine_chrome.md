# Grok Imagine qua Claude in Chrome — quy trình đã chạy được

## Vì sao Chrome của người dùng
Trình duyệt tích hợp (mcp__Claude_Browser) bị Cloudflare chặn ở grok.com (vòng "Verify you are human" lặp lại).
Dùng **Claude in Chrome** (mcp__claude-in-chrome__*). Nạp một lần bằng ToolSearch:
`select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__find,mcp__claude-in-chrome__file_upload,mcp__claude-in-chrome__javascript_tool,mcp__claude-in-chrome__tabs_create_mcp,mcp__claude-in-chrome__tabs_close_mcp`
Nếu chưa đăng nhập / gặp trang chọn tài khoản Google / CAPTCHA → dừng và nhờ người dùng tự làm (không tự đăng nhập,
không tự bấm CAPTCHA, không tự chọn tài khoản).

## Tạo 1 clip (lặp cho mỗi clip — làm tuần tự trong 1 tab đang hiển thị)
Cập nhật 2026-11-18: tab chạy nền bị Chrome đóng băng (screenshot/JS timeout 30–45s) nên **không** làm song song
nhiều tab nữa. Trong 1 tab: gửi clip xong → ghi post_id → `navigate` lại /imagine làm clip kế (Grok vẫn tạo tiếp
clip trước ở máy chủ). Sau khi upload, trang post hiện trình sửa ảnh (bảng Segments bên phải); ô nhập ở đáy có
các icon: + · ảnh · **máy quay (Video)** · …; bấm máy quay rồi mới thấy "720p · 10s" (đã được nhớ).
Nếu hiện thông báo **"Rate limit reached — Available again at <giờ>"**: dừng, báo người dùng giờ mở lại.

1. `tabs_create_mcp` → `navigate` tới `https://grok.com/imagine` → chờ 4s.
2. `find` "hidden file input (type=file) in the imagine prompt section" → lấy ref đầu tiên (thường `ref_96`).
3. `file_upload` với `paths: ["<project>\\04_anh\\codex\\<id>.png"]`. **Không click** vào nút upload (sẽ mở hộp thoại hệ thống).
4. Chờ 15–30s đến khi URL thành `/imagine/post/<id>` (tab nền xử lý chậm — "Extracting text…").
5. Chụp màn hình. Ô nhập ở đáy: bấm **icon máy quay** (chế độ Video) — cạnh icon ảnh, bên trái ô nhập.
   Lần đầu: bấm nút độ phân giải → **720p**; nút thời lượng → **10s** (cài đặt được nhớ cho lần sau).
   (Ở màn hình 1568px ngang, toạ độ từng gặp: video ≈ (648, 683–728), ô text ≈ (833, 640–685), gửi ≈ (1147, 683–728) —
   chiều cao viewport thay đổi 726/772 nên luôn chụp màn hình để xác nhận.)
6. Bấm vào ô text, `type` prompt từ `scripts/grok_prompts.py --clip <id>`; `zoom` vùng ô nhập để thấy "720p · 10s".
7. Bấm gửi. URL đổi sang post mới `/imagine/post/<post_id>?conversation=...` — **ghi lại post_id** vào du_an.json.
8. Clip 10s mất ~1–2 phút. Kiểm tra xong bằng JS (HEAD với cookie):
   ```js
   const base='https://assets.grok.com/users/<user_id>/generated/';
   // user_id lấy từ src của <video> bất kỳ trên trang: document.querySelector('video').currentSrc
   await fetch(base+'<post_id>/generated_video.mp4',{method:'HEAD',credentials:'include'}).then(r=>[r.status,r.headers.get('content-length')])
   ```
   200 + content-length > 0 là xong; 404 là đang tạo.

## Thử trước, làm sau
Tạo clip 1 trước, nhờ người dùng **bấm phát nghe** trong tab (Claude không nghe được). Đạt → làm 4 clip còn lại
nối tiếp trong cùng tab (gửi lệnh xong quay lại /imagine làm clip kế, không chờ clip trước xong). Không đạt → chỉnh prompt (giọng, tốc độ) hoặc chuyển phương án.

## Tải về (phải xin phép trước, nêu: tên file, nguồn assets.grok.com, dung lượng)
- `curl` trực tiếp → 403 (cần cookie). Script fetch+blob ở trang grok.com chỉ tải được file đầu, sau đó Chrome chặn
  "tải nhiều file tự động" từ grok.com.
- Cách chạy ổn định: **mỗi file một tab riêng** (cùng tab tải file thứ 2 trở đi bị chặn im lặng), `navigate` tới chính URL asset
  `https://assets.grok.com/users/<user_id>/generated/<post_id>/generated_video.mp4`, rồi chạy:
  ```js
  const a=document.createElement('a'); a.href=location.href; a.download='<prefix>_<id>.mp4';
  document.body.appendChild(a); a.click(); a.remove();
  ```
- Rồi: `python -P scripts/collect_downloads.py --project <dir> --prefix <prefix>` (chuyển vào 05_grok_video, kiểm tra có tiếng).
- Xong việc: đóng các tab đã tạo bằng `tabs_close_mcp` (tab đã đổi sang URL asset có thể không đóng được — báo người dùng).
