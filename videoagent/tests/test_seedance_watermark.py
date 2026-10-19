"""Regression coverage for master resolution and actual pixel/audio processing."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from app.ffmpeg import FFMPEG, NO_WINDOW, run, video_size, has_audio
from app.seedance.domain import PRESETS, normalize_config, format_prompt
from app.seedance.media import is_watermarked_url, master_api_url
from app.seedance.watermark import logo_rectangle, remove_logo


class WatermarkTests(unittest.TestCase):
    def test_unwatermarked_is_not_misclassified_by_substring(self):
        for url in ('https://v.ibytedtos.com/a?logo_type=unwatermarked',
                    'https://v.ibytedtos.com/a?lr=unwatermarked', 'https://v.ibytedtos.com/normal.mp4'):
            self.assertFalse(is_watermarked_url(url))
        for url in ('https://v.ibytedtos.com/video_gen_watermark/a',
                    'https://v.ibytedtos.com/a?logo_type=wm', 'https://v.ibytedtos.com/a?lr=watermarked'):
            self.assertTrue(is_watermarked_url(url))

    def test_master_request_preserves_provider_identifiers(self):
        url = master_api_url('https://api.byteintlapi.com/video?id=a%2Fb&key_seed=x%2By&logo_type=wm&codec_type=1&channel=old')
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query['id'], ['a/b'])
        self.assertEqual(query['key_seed'], ['x+y'])
        self.assertEqual(query['logo_type'], ['unwatermarked'])
        self.assertEqual(query['codec_type'], ['8'])
        self.assertEqual(query['channel'], ['no'])

    def test_full_style_labels_and_exact_descriptors_are_in_prompts(self):
        self.assertEqual([v[0].split(' ', 1)[1] for v in PRESETS.values()],
                         ['Hollywood 4K', 'Chân Dung 8K', 'Hành Động', 'Anime 60FPS', 'Cyberpunk', 'Fantasy 3D'])
        for preset, (_, descriptor) in PRESETS.items():
            self.assertIn(descriptor, format_prompt('A boat', normalize_config({'preset': preset})))

    def test_video_skill_prompt_uses_native_settings_without_chat_commands(self):
        prompt = format_prompt('tạo video: A boat at dawn', normalize_config({'preset': 'fantasy'}), video_mode=True)
        self.assertTrue(prompt.startswith('A boat at dawn'))
        self.assertNotIn('human artifact', prompt)
        self.assertNotIn('Seedance 2.5', prompt)
        self.assertIn(PRESETS['fantasy'][1], prompt)

    def test_rectangle_is_validated_and_leaves_an_interpolation_border(self):
        self.assertEqual(logo_rectangle({'x': .5, 'y': .5, 'w': .3, 'h': .2}, 100, 100),
                         {'x': 50, 'y': 50, 'w': 30, 'h': 20})
        for rectangle in ({'x': .9, 'y': .1, 'w': .2, 'h': .2}, {'x': float('nan'), 'y': 0, 'w': .2, 'h': .2}):
            with self.assertRaises(ValueError):
                logo_rectangle(rectangle, 100, 100)

    def test_fixed_logo_is_removed_from_real_pixels_and_audio_is_retained(self):
        with tempfile.TemporaryDirectory() as temp:
            source, target = Path(temp) / 'source.mp4', Path(temp) / 'clean.mp4'
            run(['-f', 'lavfi', '-i', 'color=c=blue:s=160x90:d=1', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
                 '-vf', 'drawbox=x=90:y=50:w=20:h=10:color=white:t=fill', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', source])
            original = source.read_bytes()
            remove_logo(source, target, {'x': 86/160, 'y': 46/90, 'w': 28/160, 'h': 18/90})
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(video_size(target), (160, 90))
            self.assertTrue(has_audio(target))
            def pixel(path):
                p = subprocess.run([FFMPEG, '-v', 'error', '-i', str(path), '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                                   capture_output=True, creationflags=NO_WINDOW, check=True)
                offset = (55 * 160 + 100) * 3
                return tuple(p.stdout[offset:offset+3])
            self.assertTrue(all(v > 200 for v in pixel(source)))
            red, green, blue = pixel(target)
            self.assertGreater(blue - red, 150)


if __name__ == '__main__':
    unittest.main()
