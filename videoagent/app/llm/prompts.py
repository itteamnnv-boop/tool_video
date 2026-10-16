SCRIPT_PROMPT = """Bạn là biên kịch video ngắn tiếng Việt (TikTok / Reels / Shorts).

Yêu cầu của người dùng:
\"\"\"{topic}\"\"\"

Thể loại: {genre_name} — {genre_guide}
Số khung hình (scene): đúng {num_scenes}.
Mỗi khung khoảng {seconds} giây → lời đọc (narration) mỗi khung khoảng {words_min}-{words_max} từ.
Tỉ lệ khung hình: {aspect}.
{template_block}
Quy tắc:
- Tiếng Việt tự nhiên, có dấu, giọng {tone}.
- headline: tối đa {headline_words} từ, gây chú ý.
- highlight: 1-2 từ lấy NGUYÊN VĂN từ headline để tô màu nhấn.
- subtext: 1 câu ngắn (≤ 18 từ) bổ sung thông tin.
- kicker: nhãn nhỏ ≤ 4 từ, VIẾT HOA (ví dụ "CUNG CẦU CHAO ĐẢO").
- stat: một con số/chỉ số ngắn nổi bật (ví dụ "+3,2%") hoặc "" nếu không phù hợp.
- trend: "up" | "down" | "flat" — xu hướng của khung.
- narration: lời thuyết minh đọc thành tiếng, không lặp nguyên văn headline, không emoji, không markdown.
- Không khẳng định số liệu cụ thể như sự thật nếu không chắc; dùng cách nói ước lượng.

Chỉ trả về JSON hợp lệ, không giải thích, đúng schema:
{{
  "title": "tiêu đề video ≤ 8 từ",{template_field}
  "scenes": [
    {{"kicker": "...", "headline": "...", "highlight": "...", "subtext": "...", "stat": "", "trend": "up", "narration": "..."}}
  ]
}}
"""

TEMPLATE_BLOCK = """Chọn MỘT template hình ảnh phù hợp nhất với chủ đề trong danh sách (trả id vào "template_id"):
{options}
"""

SHORTEN_PROMPT = """Các trường chữ sau đang bị tràn khỏi khung hình video ({fields}).
Hãy viết lại NGẮN HƠN khoảng 30-40%, giữ nguyên ý chính, tiếng Việt có dấu.
Nếu rút gọn "headline" thì "highlight" vẫn phải là 1-2 từ nằm trong headline mới.

Nội dung hiện tại:
{current}

Chỉ trả về JSON gồm các trường đã rút gọn (và "highlight" nếu đổi headline)."""
