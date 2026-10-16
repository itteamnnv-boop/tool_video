"""Thể loại video: định hướng cách AI viết kịch bản."""

# Tốc độ đọc tiếng Việt của edge-tts ở rate +0% (âm tiết / giây), dùng để ước lượng độ dài lời đọc.
WORDS_PER_SECOND = 2.8

GENRES = [
    {
        "id": "trailer", "name": "Trailer nhiều khung", "desc": "Nhịp nhanh, mỗi khung một ý mạnh",
        "guide": "nhịp nhanh như trailer, mỗi khung một ý mạnh, câu ngắn dồn dập, khung cuối để lại tò mò",
        "tone": "kịch tính, cuốn hút", "headline_words": 7,
    },
    {
        "id": "story", "name": "Kể chuyện", "desc": "Mở đầu – cao trào – kết",
        "guide": "kể một câu chuyện liền mạch: mở đầu gợi tò mò, giữa là diễn biến/cao trào, cuối là bài học hoặc cái kết",
        "tone": "ấm áp, lôi cuốn", "headline_words": 8,
    },
    {
        "id": "listicle", "name": "Top / Danh sách", "desc": "Đánh số từng mục",
        "guide": "khung đầu giới thiệu chủ đề; các khung giữa mỗi khung một mục, kicker dạng 'TOP 1', 'TOP 2'...; khung cuối tổng kết và kêu gọi theo dõi",
        "tone": "rõ ràng, nhiều năng lượng", "headline_words": 7,
    },
    {
        "id": "explainer", "name": "Giải thích kiến thức", "desc": "Đơn giản hoá vấn đề phức tạp",
        "guide": "giải thích dễ hiểu từng bước, mỗi khung một khái niệm, có ví dụ đời thường",
        "tone": "thân thiện, dễ hiểu", "headline_words": 8,
    },
    {
        "id": "news", "name": "Bản tin nhanh", "desc": "Cập nhật tin tức ngắn gọn",
        "guide": "phong cách bản tin: khung đầu là tin chính, các khung sau là chi tiết, tác động và điều cần theo dõi",
        "tone": "khách quan, dứt khoát", "headline_words": 8,
    },
    {
        "id": "promo", "name": "Quảng cáo sản phẩm", "desc": "Hook – lợi ích – kêu gọi hành động",
        "guide": "khung đầu là hook nỗi đau/mong muốn, các khung giữa là lợi ích nổi bật, khung cuối là lời kêu gọi hành động",
        "tone": "thuyết phục, hào hứng", "headline_words": 7,
    },
    {
        "id": "product_layout", "name": "Theo layout & sản phẩm mẫu", "desc": "Dùng layout và ảnh sản phẩm bạn tải lên",
        "guide": "video bán/giới thiệu đúng sản phẩm người dùng cung cấp: khung đầu là hook gây chú ý, các khung giữa "
                 "mỗi khung một lợi ích hoặc đặc điểm nổi bật, khung cuối là giá/ưu đãi và kêu gọi mua; "
                 "stat dùng cho giá, % giảm giá hoặc thông số nổi bật (để trống nếu người dùng không cung cấp)",
        "tone": "thuyết phục, hào hứng", "headline_words": 7, "needs_assets": True,
    },
]

_BY_ID = {g["id"]: g for g in GENRES}


def get_genre(genre_id: str) -> dict:
    return _BY_ID.get(genre_id, GENRES[0])
