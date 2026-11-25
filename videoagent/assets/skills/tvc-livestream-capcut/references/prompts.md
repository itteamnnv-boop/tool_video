# Mẫu prompt

## Ảnh cảnh (Codex) — trường `image_prompt`

Codex nhận 2 ảnh tham chiếu: image 1 = người mẫu, image 2 = sản phẩm. Mở đầu mọi prompt bằng câu giữ danh tính,
rồi mô tả cảnh. Giữ cùng một bối cảnh cho cả 5 cảnh để video liền mạch. **Mặc định = nhà máy phân bón**
(khi người dùng không mô tả bối cảnh); studio chỉ dùng khi người dùng yêu cầu.

Mở đầu chung — **Bối cảnh nhà máy (mặc định)**:
> Use attached image 1 for the woman (keep her exact face, hairstyle and outfit identical) and attached image 2 for
> the product (keep the label exactly unchanged and legible). Photorealistic vertical 9:16 smartphone livestream photo,
> she stands in a large, busy, brightly lit fertilizer manufacturing factory: many workers in blue uniforms and yellow
> hard hats working in the background, a bucket-filling line on stainless steel conveyors, mixing tanks, a forklift,
> and many pallets and tall stacks of the same product (identical labels) all around her. Bright, clean, even
> lighting. Leave the top 20% and bottom 30% of the frame visually simple (for on-screen UI). No added text, no logos.

Bối cảnh studio (chỉ khi người dùng yêu cầu): thay câu bối cảnh bằng "in a bright, cozy livestream sales studio:
ring light, small microphone on a stand, the product on the desk, warm softly blurred background with shelves and plants".

Phần cảnh theo clip (ghép sau câu mở đầu):
1. **Chào**: she stands facing the camera, waist-up framing, smiling and waving hello; product beside her.
2. **Giới thiệu**: she holds the product up with both hands next to her face, label facing the camera, enthusiastic smile.
3. **Trải nghiệm**: she opens/uses the product toward the camera (e.g. lid removed showing the contents inside;
   for cosmetics: pumps a little onto the back of her hand), excited expression.
4. **Cách dùng**: she demonstrates usage (e.g. pouring/measuring/mixing, applying), focused and smiling, product label visible.
5. **CTA**: she smiles warmly and points down toward the lower right corner of the frame, other hand on the product.

Nếu không có ảnh người mẫu (người mẫu AI): thay câu đầu bằng mô tả người mẫu cụ thể (tuổi, tóc, trang phục
màu thương hiệu) và lặp lại y hệt mô tả đó ở cả 5 prompt để giữ nhất quán.

## Clip nói (Grok Imagine) — `scripts/grok_prompts.py` ghép tự động

```
Authentic vertical smartphone livestream footage, slight handheld micro-movement, natural room light.
The Vietnamese woman is a lively, energetic online sales host. <grok_action> She speaks very fast, crisp and decisive in
Vietnamese with a <voice_style>: short punchy delivery, no drawn-out vowels, no pauses between phrases, natural lip sync, she says: "<dialogue>"
Keep her face and the product label unchanged and legible. No background music, no subtitles, no text.
```

`grok_action` gợi ý theo clip:
1. She waves, leans toward the camera with a big smile.
2. She lifts the product proudly toward the camera and taps the label with her finger.
3. She sets the lid aside and tilts the open product toward the camera so the contents shine.
4. She pours/demonstrates while glancing at the camera, then raises one finger.
5. She pats the product, then points down toward the lower right corner with excitement.

Viết `dialogue` để Grok đọc tự nhiên: số đọc bằng chữ ("không chín bốn bốn, hai mươi, hai mươi, mười lăm",
"một lít cho năm trăm lít nước"), tên riêng tiếng Anh giữ nguyên (Grok đọc khá ổn), câu ngắn có dấu phẩy.
