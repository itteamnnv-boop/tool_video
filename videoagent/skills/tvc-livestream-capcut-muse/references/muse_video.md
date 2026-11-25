# Clip nói bằng Muse (muse.ai của Meta) — `scripts/muse_video.py`

## Muse là gì, dùng công cụ nào
- muse.ai = tác tử AI cá nhân của Meta, chạy trong một máy ảo Linux riêng của người dùng. Nó tạo được video
  (image-to-video, có giọng nói tiếng Việt khớp khẩu hình) và lưu ở `/workspace/imagine_media/*.mp4` trên máy ảo.
- Điều khiển bằng gói Python **muse-cli** (`pip install --user muse-cli`), gọi bằng `python -P -m muse_cli …`
  (lệnh `muse-cli.exe` có thể không nằm trong PATH của Git Bash).
- **Không nhầm với lệnh `muse`** (`%LOCALAPPDATA%\Programs\muse\muse.cmd`) — đó là Muse Code, trợ lý lập trình
  giống Codex, không tạo video.

## Đăng nhập
- `python -P -m muse_cli status` in `vm_id`, số phiên… = đã đăng nhập (cookie ở `~/.config/muse-cli/cookies.txt`).
- Lỗi `auth error` / không có cookie: người dùng phải tự đăng nhập https://muse.ai/ trong Chrome, sau đó làm theo mục
  "Auth" trong SKILL.md của muse-cli (`site-packages/muse_cli/SKILL.md`; Windows dùng cách 2b/2c/2d). Không tự đăng
  nhập hộ, không in cookie ra.

## Script làm gì
1. Side chat riêng cho dự án: `session.start` + đặt tên "TVC <tên dự án>", id lưu ở `muse_thread` trong du_an.json
   (không làm rối chat chính; các lần chạy sau dùng lại thread này).
2. Đẩy ảnh cảnh: chuyển PNG → JPEG q92 (~450 KB) rồi `fs.write` vào `workspace/tvc_uploads/<dự án>/<id>.jpg`.
   **Bẫy**: mỗi gói tin gateway (mã hoá Noise) tối đa 64 KB → phải ghi từng mảnh 32 KB (`append: true` từ mảnh 2),
   sau đó `fs.stat` so kích thước. Body của `fs.write` bắt buộc đủ trường:
   `{"path", "data_base64", "overwrite", "append", "create_parent"}`.
3. Gửi prompt (tiếng Việt + prompt tiếng Anh) vào thread qua `chat.stream`: image-to-video từ ảnh đã đẩy, 10s, dọc 9:16,
   đọc đúng nguyên văn `dialogue`, không nhạc nền/phụ đề/chữ, "không hỏi lại". Xem prompt: `--print`.
4. Chờ: đọc `chat.history` của thread mỗi 5s; khi có tài nguyên video mới (seq > mốc trước khi gửi) và thread yên 15s
   thì tải file video cuối cùng (`save_resources`) về `05_grok_video/<id>.mp4`; ghi `muse_video` vào clip.
5. In `ffprobe`: kích thước, thời lượng, có tiếng hay không.

## Kiểm tra / xử lý sự cố
- **Muse trả lời "video generation không khả dụng cho tài khoản này ở khu vực hiện tại"** (gặp 2026-11-18, dù trước
  đó tài khoản từng tạo được video; tài khoản thứ hai cũng bị "lỗi 403, chặn lâu dài" cùng ngày → nhiều khả năng chặn
  theo khu vực): giới hạn phía Meta, thử lại hay đổi tài khoản không có tác dụng. Script tự
  dừng sớm khi thấy lời từ chối. Báo người dùng; phương án: dùng skill `tvc-livestream-capcut` (Grok) hoặc chờ Meta mở lại.
- Video ngang (vd 1280x720) hoặc không tiếng → chạy lại `--clip <id>`; nếu lặp lại, đọc Muse nói gì:
  `python -P -m muse_cli history --thread <muse_thread> --limit 5`.
- Hết giờ chờ mà chưa có video: Muse có thể vẫn đang làm → `python -P -m muse_cli files --thread <muse_thread>`
  rồi `python -P -m muse_cli download <sandbox://…mp4> -o <thư mục>` và đổi tên thành `05_grok_video/<id>.mp4`.
- Muse hỏi lại thay vì làm: trả lời trong thread bằng `python -P -m muse_cli send "Làm ngay theo yêu cầu" --thread <id> --wait 0`
  rồi chạy lại script với `--clip <id>`.
- Claude không nghe được âm thanh → luôn nhờ người dùng nghe clip thử (giọng, tốc độ, đọc đúng tên sản phẩm/số).
