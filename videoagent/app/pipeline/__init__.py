ASPECTS = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080), "4:5": (1080, 1350)}

# Giọng đọc bắt đầu sau khi cảnh mở VOICE_LEAD giây và cảnh giữ thêm SCENE_TAIL giây sau câu cuối.
VOICE_LEAD = 0.35
SCENE_TAIL = 0.45


class Cancelled(Exception):
    pass


def scene_dir_name(index: int) -> str:
    return f"{index:02d}"
