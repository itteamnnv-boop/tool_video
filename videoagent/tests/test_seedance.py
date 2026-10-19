"""Acceptance checks without a provider account or external generation requests."""
import base64
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.seedance.domain import DEFAULT_CONFIG, StudioError, distribute, format_prompt, normalize_config, parse_prompts
from app.seedance.provider import allowed_url, extract_media
from app.seedance.store import Store
from app.seedance.studio import Studio


class InputTests(unittest.TestCase):
    def test_paragraphs_keep_multiline_and_remove_empty(self):
        self.assertEqual([r['text'] for r in parse_prompts('\ufeff First\r\nsecond\r\n \r\n third\r\n\r\n')], ['First\nsecond', 'third'])

    def test_lines_without_blank_separator(self):
        self.assertEqual(len(parse_prompts('One\rTwo\rThree')), 3)

    def test_csv_quoted_newlines_and_commas(self):
        rows = parse_prompts('title,prompt\n"Scene 1","A boat, at dawn\nCamera tracks"\nScene 2,Sunset', 'scenes.csv')
        self.assertEqual(rows[0], {'title': 'Scene 1', 'text': 'A boat, at dawn\nCamera tracks'})
        self.assertEqual(len(rows), 2)

    def test_json_project_roundtrip_and_invalid_schema(self):
        rows = parse_prompts(json.dumps({'scenes': [{'title': 'A', 'text': 'One'}, 'Two', '']}), 'project.json')
        self.assertEqual(len(rows), 2)
        with self.assertRaises(ValueError):
            parse_prompts('{"hello":1}', 'invalid.json')
        with self.assertRaises(ValueError):
            parse_prompts('a,b\nc,d', 'missing_header.csv')

    def test_none_does_not_insert_ratio_and_prefix_not_duplicated(self):
        cfg = normalize_config({'aspectRatio': 'none', 'model': '2.0', 'duration': '5s'})
        result = format_prompt('tạo video: Hồ nước', cfg)
        self.assertEqual(result.count('tạo video:'), 1)
        self.assertNotIn('tỉ lệ', result)
        self.assertIn('Seedance 2.0', result)
        self.assertIn('thời lượng 5s', result)

    def test_explicit_old_settings_replaced(self):
        result = format_prompt('Forest, ratio 16:9, duration 10s, Seedance 2.0', normalize_config({'aspectRatio': '9:16', 'duration': '15s'}))
        self.assertIn('tỉ lệ 9:16', result)
        self.assertNotIn('16:9', result)
        self.assertNotIn('10s', result)
        self.assertNotIn('2.0', result)

    def test_unsupported_duration_and_resource_limit(self):
        with self.assertRaises(ValueError):
            normalize_config({'duration': '60s'})
        with self.assertRaises(ValueError):
            normalize_config({'profileIds': ['a', 'b', 'c', 'd'], 'tabsPerProfile': 4})

    def test_two_scene_round_robin(self):
        self.assertEqual(distribute(list('ABCDEF'), 2), [list('ABEF'), list('CD')])

    def test_resolver_prefers_larger_variant_and_decodes_base64(self):
        url = 'https://v.ibytedtos.com/video.mp4'
        result = extract_media({'video_list': {'low': {'main_url': 'https://v.ibytedtos.com/low', 'width': 640, 'height': 360},
                                               'high': {'main_url': base64.b64encode(url.encode()).decode(), 'vwidth': 1920, 'vheight': 1080}}})
        self.assertEqual(result[0]['url'], url)
        self.assertEqual(result[0]['width'], 1920)

    def test_url_boundary_and_encrypted_adapter(self):
        self.assertFalse(allowed_url('https://www.dola.com.evil.test/x'))
        self.assertFalse(allowed_url('http://127.0.0.1/x'))
        self.assertFalse(allowed_url('https://www.doubao.com/chat/x', 'dola'))
        self.assertTrue(allowed_url('https://www.dola.com/chat/x', 'dola'))
        result = extract_media({'key_seed': 'seed', 'video_list': [{'main_url': 'qAABfake'}]}, lambda token, seed: 'https://v.ibytedtos.com/decoded')
        self.assertEqual(result[0]['url'], 'https://v.ibytedtos.com/decoded')


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.events = []
        self.studio = Studio(SimpleNamespace(output_dir=root / 'output', get=lambda key: 'chromium'),
                             SimpleNamespace(require_active=lambda: None), lambda *event: self.events.append(event), root / 'data')

    def tearDown(self):
        self.studio.store.db.close()
        self.temp.cleanup()

    def jobs(self, count=4):
        self.studio.import_prompts('\n'.join(f'Scene {i}' for i in range(count)))
        return self.studio.store.list('jobs')

    def test_restart_requires_manual_retry_and_preserves_submitted_evidence(self):
        job = self.jobs(1)[0]
        self.studio.store.update('jobs', job['id'], status='generating', submittedAt=123, chatUrl='https://www.dola.com/chat/123')
        reopened = Store(self.studio.store.root)
        record = reopened.get('jobs', job['id'])
        self.assertEqual(record['status'], 'interrupted')
        self.assertEqual(record['submittedAt'], 123)
        reopened.db.close()

    def test_cannot_mutate_queue_or_start_duplicate_batch(self):
        self.studio.running = True
        with self.assertRaises(ValueError):
            self.studio.import_prompts('Another scene')
        with self.assertRaises(ValueError):
            self.studio.start(DEFAULT_CONFIG)

    def test_images_are_copied_verified_and_ordered(self):
        from PIL import Image
        path = Path(self.temp.name) / 'reference.png'
        Image.new('RGB', (64, 64), 'green').save(path)
        data_url = 'data:image/png;base64,' + base64.b64encode(path.read_bytes()).decode()
        self.studio.import_image_data('first.png', data_url)
        self.studio.import_images([str(path)])
        images = self.studio.store.list('images')
        self.assertEqual(images[0]['name'], 'first.png')
        self.assertNotEqual(Path(images[0]['path']), path)
        self.assertTrue(Path(images[0]['path']).is_file())
        self.studio.change_image(images[1]['id'], 'up')
        self.assertEqual(self.studio.store.get('images', images[1]['id'])['order'], 0)

    def test_image_pairing_and_unmatched_scenes_remain_queued(self):
        from PIL import Image
        jobs = self.jobs(3)
        path = Path(self.temp.name) / 'ref.png'
        Image.new('RGB', (10, 10)).save(path)
        self.studio.import_images([str(path)])
        profiles = [{'id': 'default', 'sites': ['dola']}]
        with patch('app.seedance.studio.browser_profiles.list_profiles', return_value=profiles), patch.object(self.studio, '_coordinate'):
            result = self.studio.start({**DEFAULT_CONFIG, 'mode': 'image'})
        self.assertEqual(result['count'], 1)
        records = self.studio.store.list('jobs')
        self.assertTrue(records[0]['imageId'])
        self.assertEqual(records[1]['batchId'], '')
        self.assertEqual(records[2]['status'], 'queued')

    def fake_adapter(self, fail_new_chat=False):
        studio = self.studio
        class Fake:
            page = SimpleNamespace(url='https://www.dola.com/chat/fixture')
            context = SimpleNamespace(cookies=lambda: [])
            calls = []
            def execute(self, job, image, checkpoint, media_found):
                self.calls.append(job['id'])
                checkpoint('submitting')
                yield
                studio.check()
                checkpoint('submitted', submittedAt=123)
                checkpoint('generating')
                media_found({'url': 'https://v.ibytedtos.com/' + job['id'], 'source': 'fixture'})
            def new_chat(self):
                if fail_new_chat:
                    raise StudioError('NEW_CHAT_FAILED', 'fixture failed')
                yield
        return Fake()

    def test_stop_prevents_next_img2vid_pair(self):
        jobs = self.jobs()
        cfg = normalize_config({'mode': 'image', 'delaySeconds': 0, 'autoDownload': False})
        adapter = self.fake_adapter()
        lane = self.studio._lane(adapter, jobs, cfg, 'default', 'default:1', self.studio.settings.output_dir, None)
        next(lane)
        self.studio.stop_event.set()
        list(lane)
        self.assertEqual(adapter.calls, [jobs[0]['id']])
        self.assertTrue(all(j['status'] == 'cancelled' for j in self.studio.store.list('jobs')))

    def test_new_chat_failure_stops_lane(self):
        jobs = self.jobs()
        adapter = self.fake_adapter(fail_new_chat=True)
        cfg = normalize_config({'mode': 'image', 'delaySeconds': 0, 'autoDownload': False})
        list(self.studio._lane(adapter, jobs, cfg, 'default', 'default:1', self.studio.settings.output_dir, None))
        self.assertEqual(adapter.calls, [jobs[0]['id']])
        self.assertEqual(self.studio.store.get('jobs', jobs[1]['id'])['code'], 'NEW_CHAT_FAILED')
        self.assertEqual(self.studio.snapshot()['counts']['submitted'], 1)
        self.assertEqual(self.studio.snapshot()['counts']['ready'], 1)
        self.assertEqual(self.studio.snapshot()['counts']['downloaded'], 0)

    def test_zip_policy_suppresses_download_for_every_discovery_source(self):
        cfg = normalize_config({'zipMode': True, 'autoDownload': True})
        adapter = self.fake_adapter()
        with patch.object(self.studio, '_download') as download:
            for index, source in enumerate(('dom', 'provider_response')):
                self.studio._media({'url': f'https://v.ibytedtos.com/{index}', 'source': source}, None, adapter, cfg, self.studio.settings.output_dir, 'default')
            download.assert_not_called()

    def test_quota_blocks_only_new_submissions_for_affected_profile(self):
        jobs = self.jobs(3)
        cfg = normalize_config({'autoDownload': False, 'delaySeconds': 0})
        bad = self.fake_adapter()
        def execute(job, image, checkpoint, media_found):
            raise StudioError('DAILY_LIMIT', 'Daily limit reached', provider_message='Daily limit reached')
            yield
        bad.execute = execute
        list(self.studio._lane(bad, jobs[:2], cfg, 'limited', 'limited:1', self.studio.settings.output_dir, None))
        self.assertFalse(self.studio.stop_event.is_set())
        self.assertIn('limited', self.studio.account_limits)
        self.assertEqual(self.studio.store.get('jobs', jobs[0]['id'])['providerMessage'], 'Daily limit reached')
        good = self.fake_adapter()
        list(self.studio._lane(good, jobs[2:], cfg, 'healthy', 'healthy:1', self.studio.settings.output_dir, None))
        self.assertEqual(self.studio.store.get('jobs', jobs[2]['id'])['status'], 'media_ready')

    def test_signed_url_refresh_does_not_duplicate_media(self):
        adapter = self.fake_adapter()
        cfg = normalize_config({'autoDownload': False})
        for token in ('old', 'new'):
            self.studio._media({'url': 'https://v.ibytedtos.com/a?token=' + token}, None, adapter, cfg, self.studio.settings.output_dir, 'default')
        media = self.studio.store.list('media')
        self.assertEqual(len(media), 1)
        self.assertTrue(media[0]['url'].endswith('new'))

    def test_history_video_can_recover_an_interrupted_scene_without_resubmission(self):
        job = self.jobs(1)[0]
        self.studio.store.update('jobs', job['id'], status='interrupted', submittedAt=123)
        self.studio._media({'url': 'https://v.ibytedtos.com/history'}, None, self.fake_adapter(),
                           normalize_config({'autoDownload': False}), self.studio.settings.output_dir, 'default')
        media = self.studio.store.list('media')[0]
        self.studio.link_media(media['id'], job['id'])
        scene = self.studio.store.get('jobs', job['id'])
        self.assertEqual(scene['status'], 'media_ready')
        self.assertEqual(scene['submittedAt'], 123)
        self.assertEqual(scene['attempt'], 0)

    def test_download_marks_completed_only_after_validating_real_mp4(self):
        from app.ffmpeg import run
        fixture = Path(self.temp.name) / 'fixture.mp4'
        run(['-f', 'lavfi', '-i', 'color=c=green:s=160x90:d=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', fixture])
        payload = fixture.read_bytes()
        job = self.jobs(1)[0]
        self.studio._media({'url': 'https://v.ibytedtos.com/fixture'}, job, self.fake_adapter(),
                           normalize_config({'autoDownload': False}), self.studio.settings.output_dir, 'default')
        media = self.studio.store.list('media')[0]
        class Response:
            is_redirect = False
            def raise_for_status(self): pass
            def iter_content(self, size): yield payload
            def __enter__(self): return self
            def __exit__(self, *args): pass
        class Session:
            def get(self, *args, **kwargs): return Response()
            def __enter__(self): return self
            def __exit__(self, *args): pass
        with patch('app.seedance.studio.requests.Session', Session):
            target = self.studio._download(media)
        record = self.studio.store.get('media', media['id'])
        self.assertEqual(target.read_bytes(), payload)
        self.assertEqual((record['width'], record['height']), (160, 90))
        self.assertEqual(self.studio.store.get('jobs', job['id'])['status'], 'completed')

    def test_invalid_download_retains_ready_video_and_removes_partial_file(self):
        job = self.jobs(1)[0]
        self.studio._media({'url': 'https://v.ibytedtos.com/expired'}, job, self.fake_adapter(),
                           normalize_config({'autoDownload': False}), self.studio.settings.output_dir, 'default')
        media = self.studio.store.list('media')[0]
        class Response:
            is_redirect = False
            def raise_for_status(self): pass
            def iter_content(self, size): yield b'<html>Expired URL</html>'
            def __enter__(self): return self
            def __exit__(self, *args): pass
        class Session:
            def get(self, *args, **kwargs): return Response()
            def __enter__(self): return self
            def __exit__(self, *args): pass
        with patch('app.seedance.studio.requests.Session', Session), self.assertRaises(Exception):
            self.studio._download(media)
        self.assertEqual(self.studio.store.get('jobs', job['id'])['status'], 'media_ready')
        self.assertFalse(list(self.studio.settings.output_dir.glob('*.part')))

    def test_zip_is_ordered_streamed_and_records_each_failure(self):
        adapter = self.fake_adapter()
        cfg = normalize_config({'autoDownload': False})
        jobs = self.jobs(3)
        for index in (2, 0, 1):
            self.studio._media({'url': f'https://v.ibytedtos.com/{index}'}, jobs[index], adapter, cfg, self.studio.settings.output_dir, 'default')
        def download(record, **kwargs):
            if record['sceneId'] == jobs[1]['id']:
                raise ValueError('fixture expired URL')
            target = self.studio.settings.output_dir / (record['sceneId'] + '.mp4')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(record['sceneId'].encode())
            return target
        with patch.object(self.studio, '_download', side_effect=download):
            self.studio.export_zip()
            until = time.monotonic() + 5
            while self.studio.exporting and time.monotonic() < until:
                time.sleep(0.02)
        self.assertFalse(self.studio.exporting)
        output = self.studio.store.list('exports')[0]['path']
        with zipfile.ZipFile(output) as archive:
            names = archive.namelist()
            self.assertEqual([n[:4] for n in names], ['0001', '0002', '0003'])
            self.assertEqual(archive.read(names[0]).decode(), jobs[0]['id'])
            self.assertTrue(names[1].endswith('_error.txt'))
            self.assertIn(b'expired URL', archive.read(names[1]))


if __name__ == '__main__':
    unittest.main()
