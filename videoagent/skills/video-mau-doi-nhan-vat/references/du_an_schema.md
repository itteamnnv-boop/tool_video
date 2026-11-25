# du_an.json — file dự án (02_kich_ban/du_an.json)

`phan_tich_video.py` tạo khung sườn (mỗi cảnh phát hiện được = 1 phần tử `shots`); Claude điền phần còn lại
sau khi xem lưới cảnh/lưới phụ đề. Mọi script đọc file này.

```json
{
  "name": "RemakeKinger_n26",            // tên thư mục dự án
  "draft_name": "RemakeKinger_n26",      // tên draft CapCut
  "video_mau": "C:\\...\\mau.mp4",       // video mẫu
  "width": 1080, "height": 1920, "fps": 30,
  "nhan_vat": {
    "anh": "00_input/nhan_vat.png",      // ảnh nhân vật mới (mặt rõ, chính diện)
    "mo_ta": "",                          // mô tả ngắn (tuổi, tóc) — giúp Codex/Grok giữ nhân vật
    "trang_phuc": "",                     // rỗng = giữ trang phục như video mẫu; điền để đổi
    "giong": "cheerful young Southern Vietnamese female voice",  // giọng Grok (Bắc: "warm Northern Vietnamese ...")
    "toc": "",                            // (tuỳ chọn) kiểu tóc trong video nếu khác ảnh — dùng cho sheet nhân vật
    "kinh": false                         // (tuỳ chọn) true nếu nhân vật đeo kính
  },
  // NHIỀU NHÂN VẬT (cặp đôi, 2 người dẫn…): dùng "nhan_vats" thay cho "nhan_vat" khi tạo ảnh
  "nhan_vats": [
    {"vai": "bride", "anh": "00_input/nhan_vat_nu.png", "trang_phuc": "...", "toc": "bridal updo ..."},
    {"vai": "groom", "anh": "00_input/nhan_vat_nam.png", "trang_phuc": "...", "kinh": true}
  ],
  // Storyboard nhân vật (tao_sheet_nhan_vat.py): 00_input/sheet/<vai>_mat.png + <vai>_toan_than.png
  // (một nhân vật không có "vai" → nhan_vat_mat.png / nhan_vat_toan_than.png). tao_anh.py tự dùng nếu có.
  "am_thanh": {
    "nhac": "khong",                      // "khong" | "file" | "tach_goc"
    "nhac_file": "",                      // khi nhac = "file"
    "nhac_volume": 0.18
  },
  "phu_de_kieu": {},                      // ghi đè kiểu chữ mặc định (xem dưới)
  "shots": [
    {
      "id": "s01", "start": 0.0, "end": 2.633,      // mốc cảnh trong video mẫu (giữ nguyên)
      "hinh": "tao_moi",                  // "tao_moi" | "giu_goc"
      "giong": "clip",                    // "clip" | "giong_rieng" | "goc" | "khong"
      "giong_anh": "s01",                 // (giong_rieng) ảnh cảnh lộ mặt dùng làm clip giọng
      "khung": "01_phan_tich/canh/s01_a.png",   // (tuỳ chọn) khung mẫu cho Codex, mặc định <id>_a
      "mo_ta": "...",                     // mô tả cảnh bằng tiếng Anh (bối cảnh, trang phục, đạo cụ, bố cục)
      "hanh_dong": "...",                 // chuyển động trong cảnh, tiếng Anh, theo đúng video mẫu
      "camera": "Static medium shot ...", // chuyển động máy quay của video mẫu
      "dialogue": "...",                  // lời nói (đã sửa lỗi whisper theo phụ đề/nhãn); số viết bằng CHỮ
      "image_prompt": "",                 // để trống = prompt mặc định "dựng lại khung, thay người"
      "grok_prompt": "", "grok_prompt_giong": "",   // để trống = tự ghép
      "phu_de": [                          // phụ đề như video mẫu — mốc theo giây của VIDEO MẪU
        {"t0": 0.0, "t1": 2.63, "dong": [
          {"text": "chào quý khách", "kieu": "dan"},
          {"text": "Kinger Đại Phát", "kieu": "nhan"},
          {"text": "PHÂN BÓN LÁ CAO CẤP", "kieu": "hoa", "y": -0.68}]}   // "y" tuỳ chọn
      ]
    }
  ]
}
```

## Chọn `hinh` / `giong` cho từng cảnh

| Cảnh trong video mẫu | hinh | giong |
|---|---|---|
| Nhân vật lộ mặt, đang nói | `tao_moi` | `clip` |
| Không lộ mặt (cận sản phẩm, bàn tay), lời nói vẫn chạy | `tao_moi` (khung có chữ dính cứng hoặc lộ tay/da) / `giu_goc` (khung sạch, không người) | `giong_rieng` |
| Không có lời, chỉ hình nhân vật | `tao_moi` | `khong` |
| B-roll không nhân vật, không chữ dính, không lời | `giu_goc` | `khong` hoặc `goc` (nếu chỉ có nhạc/tạp âm) |

**Không bao giờ** dùng `giong: "goc"` cho cảnh có giọng nhân vật cũ. `giu_goc` cắt luôn cả chữ dính cứng của video
mẫu → nếu video mẫu có phụ đề/hiệu ứng chữ in sẵn, mọi cảnh phải `tao_moi` (Codex xoá chữ khi dựng lại khung).

## Kiểu phụ đề (`phu_de_kieu`) — mặc định đo từ video mẫu canvas-n26

| kieu | size (CapCut) | px (xem trước) | màu | kiểu | y | xuất hiện |
|---|---|---|---|---|---|---|
| `dan` | 6 | 48 | #FFFFFF | thường | -0.45 | ngay, fade-in |
| `nhan` | 12 | 100 | #E8D5FF | đậm nghiêng (Times BI khi xem trước) | -0.57 | +0,12s, pop-up |
| `hoa` | 10 | 82 | #FFFFFF | đậm, viết IN HOA trong text | -0.68 | +0,24s, pop-up |

`y` theo hệ CapCut: 0 = giữa khung, -1 = mép dưới (pixel = 960 × (1 − y) với khung 1920).
Thêm/sửa kiểu: `"phu_de_kieu": {"nhan": {"color": "#FFE14D"}, "gia": {"size": 14, "px": 120, "color": "#FF3B30", "bold": true, "y": -0.3}}`
(trường: size, px, color, bold, italic, y, font (file trong C:\Windows\Fonts), delay, anim: fade-in/pop-up/typewriter/zoom-in-text).
Font chữ trong CapCut không đặt được qua CLI — nhắc người dùng chọn font serif nghiêng cho tầng `nhan` nếu muốn giống hệt.

## File theo `id`
- khung mẫu: `01_phan_tich/canh/<id>_{a,b,c}.png`
- ảnh khung đầu (Codex): `04_anh/<id>.png`
- clip hình (Grok): `05_video/<id>.mp4`; clip giọng: `05_video/<id>_giong.mp4`
- đoạn đã chuẩn hoá: `06_doan/<id>.mp4`
