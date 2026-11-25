# du_an.json — file dự án (02_kich_ban/du_an.json)

Mọi script đọc file này. `init_project.py` tạo bản mẫu; Claude điền nội dung ở bước 2–3.

```json
{
  "name": "KingerLivestream",                 // tên thư mục dự án
  "draft_name": "KingerLivestream_Live",      // tên draft trong CapCut
  "shop_name": "Phân bón ABC",                // tên shop trên thanh live
  "voice_style": "cheerful Southern Vietnamese accent",   // giọng Muse (miền Bắc: "warm Northern Vietnamese accent")
  "music": {"style": "dong_luc", "bpm": 124, "key": "C", "seed": 18, "volume": 0.15},  // nhạc nền tự tạo (mặc định đã duyệt)
  "overlay": {
    "product_title": "KINGER 2",              // dòng 1 thẻ giỏ hàng (xanh, đậm)
    "product_line2": "Vua Trái Cam",          // dòng 2 (cam, đậm)
    "product_line3": "Greenxanh 6",           // dòng 3 (xám)
    "hotline": "0944.20.20.15",
    "viewers": "3.268", "likes": "12,5K",
    "avatar_box": null                        // [x0,y0,x1,y1] vùng mặt trong nguoi_mau.png; null = tự ước lượng
  },
  "keywords": ["Kinger 2", "Vua Trái Cam", "Bo", "1 lít", "500 lít nước", "giỏ hàng", "0944.20.20.15"],
  "clips": [
    {
      "id": "v1",
      "image_prompt": "Use attached image 1 for the woman ... (xem prompts.md)",
      "grok_action": "She waves hello and leans toward the camera with a big smile.",
      "dialogue": "Chào cả nhà đang xem live nha! ...",          // lời Muse nói — số viết bằng CHỮ
      "display": "",                                              // phụ đề hiển thị nếu khác dialogue — số viết bằng SỐ
      "comments": [["Út Mười", "Chào em gái nha!"], ["Chị Hai", "Có ship về Vĩnh Long không em?"]],
      "muse_video": "",                                           // (script ghi) đường dẫn sandbox:// của clip trên Muse
      "fx": [{"type": "reveal", "at": 0.5, "x": 500, "y": 1000}]  // hiệu ứng sản phẩm — xem bảng dưới
    }
  ]
}
```

Quy ước file theo `id` clip:
- ảnh cảnh: `04_anh/codex/<id>.png`
- clip Muse: `05_grok_video/<id>.mp4` (tên thư mục giữ như bản Grok để dùng chung script); id side chat Muse: `muse_thread` (cấp gốc)
- bình luận: `04_anh/overlay/binh_luan_<id>.png`

Gợi ý:
- `keywords`: 10–18 cụm — tên sản phẩm, thành phần chính, liều lượng, lợi ích, "giỏ hàng", hotline.
  Viết đúng như trong `display`/`dialogue` (khớp không phân biệt hoa thường, theo ranh giới từ).
- `dialogue` 22–30 từ/clip cho clip 10s. Câu ngắn, có dấu phẩy để Muse ngắt hơi (phụ đề bám theo chỗ ngắt).
- Bình luận: chào hỏi, hỏi giá/ship/cách dùng, "đã đặt" — **không** viết lời khen hiệu quả sản phẩm (testimonial giả).

## Hiệu ứng `fx` (khung live động Remotion + zoom punch CapCut)

Mỗi phần tử có `type` và **một** mốc thời gian:
- `"at": 0.5` — giây trong clip Muse gốc; hoặc
- `"on": "đen sệt"` — lúc dòng phụ đề chứa từ khoá hiện ra (từ khoá phải nằm trọn 1 dòng), cộng thêm `"delay"` (giây) nếu có.

`x`, `y` là toạ độ khung 1080x1920. `reveal`, `price`, `gift` tự zoom punch video 12% (tắt: `"zoom": false`).

| type | Trường | Mô tả |
|---|---|---|
| `reveal` | x, y (tâm sản phẩm) | Chớp sáng, tia sáng vàng xoay, 2 vòng sóng, tia lấp lánh bung + lấp lánh quanh sản phẩm (~3s) |
| `price` | x, y, scale, pre, text, sub | Huy hiệu sao đỏ "GIÁ CHỈ / 650.000đ" + dải ưu đãi có vệt sáng + pháo giấy, giữ đến hết clip |
| `chips` | x (mép phải), y (dòng đầu), items `[{icon, text}]` | Thẻ xanh viền vàng trượt vào lần lượt, cách nhau 0,45s, giữ đến hết clip |
| `callout` | x, y (điểm chỉ), bx, by (bong bóng), text, dur | Bong bóng chữ + nét đứt chỉ vào chi tiết (chất bên trong, nhãn…) |
| `gift` | x, y, text, dur | Hộp quà 🎁 bật ra + chữ (vd "+1 XÔ") + tim/sao bung |
| `pointer` | x, y | Bàn tay 👇 nhấp nhô + vòng sóng, chỉ xuống giỏ hàng đến hết clip |
| `react` | x, y, items `["🔥","👍"]`, dur | Emoji cảm xúc bay lên |

Tự động (không cần khai báo): ánh sáng mở màn + chớp/vệt sáng ở mỗi lần chuyển clip.

Ví dụ đã duyệt (GoodDamCaAmino):
```json
{"type": "chips", "on": "phân bón hữu cơ", "x": 560, "y": 190,
 "items": [{"icon": "🌿", "text": "Hữu cơ 50%"}, {"icon": "⚖️", "text": "Xô 17 ký"}, {"icon": "🏭", "text": "Việt Nhật"}]},
{"type": "callout", "on": "đen sệt", "x": 480, "y": 850, "bx": 290, "by": 1010, "text": "Đen sệt – sánh mịn", "dur": 3.0},
{"type": "price", "at": 0.35, "x": 860, "y": 560, "scale": 0.72, "pre": "GIÁ CHỈ", "text": "650.000đ", "sub": "MUA 5 TẶNG 1"},
{"type": "gift", "on": "tặng ngay", "x": 760, "y": 900, "text": "+1 XÔ"},
{"type": "pointer", "on": "giỏ hàng", "x": 870, "y": 1230}
```
