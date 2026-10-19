r"""Run the real UI and Python bridge in headless Chromium, using a temporary Studio.

No Dola/Doubao requests or generation. Run from videoagent:
  .venv\Scripts\python tests/smoke_seedance_ui.py
"""
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright

from app.api import Api
from app.config import settings
from app.seedance.domain import normalize_config
from app.seedance.provider import BrowserAdapter
from app.seedance.studio import Studio
from app.server import start_server
from app.ffmpeg import run as ffmpeg_run
from types import SimpleNamespace


def run():
    with ExitStack() as cleanup:
        temp = cleanup.enter_context(tempfile.TemporaryDirectory())
        cleanup.enter_context(patch('app.browser_profiles.list_profiles', return_value=[{
            'id': 'default', 'name': 'Mặc định', 'sites': ['gemini', 'grok', 'chatgpt', 'dola', 'doubao'],
            'channel': '', 'busy': '', 'exists': True}]))
        with patch('app.seedance.studio.DATA_DIR', Path(temp)):
            api = Api()
        cleanup.callback(api._seedance.store.db.close)
        def wait_processing():
            deadline = time.monotonic() + 10
            while api._seedance.cleaning and time.monotonic() < deadline:
                time.sleep(.05)
        cleanup.callback(wait_processing)
        url = start_server()
        errors = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1600, 'height': 1000}, device_scale_factor=1)
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.expose_binding('__bridge', lambda source, name, args: getattr(api, name)(*args))
            page.add_init_script("""window.pywebview={api:new Proxy({}, {get:(_,name)=>(...args)=>window.__bridge(name,args)})};
                window.addEventListener('DOMContentLoaded',()=>window.dispatchEvent(new Event('pywebviewready')));""")
            page.goto(url)
            page.locator('[data-view="seedance"]').click()
            page.wait_for_function("document.querySelector('#sdStatus').textContent === 'Sẵn sàng'")
            page.locator('#sdPromptText').fill('A wooden boat at dawn.\nThe camera follows the boat.\n\nA mountain under a starry sky.')
            assert page.locator('#sdPromptCount').inner_text() == '2 cảnh'
            page.locator('#sdAddPrompts').click()
            page.wait_for_function("document.querySelectorAll('.sd-job').length===2")
            page.locator('#sdAspect').select_option('none')
            page.locator('#sdModel').select_option('2.0')
            page.wait_for_timeout(600)
            assert api._seedance.store.config()['aspectRatio'] == 'none', page.locator('#toast').inner_text()
            assert api._seedance.store.config()['model'] == '2.0'
            assert page.locator('[data-sd-style]').count() == 6
            page.locator('[data-sd-style="anime"]').click()
            page.wait_for_function("async () => (await window.pywebview.api.seedance_state()).studio.config.preset==='anime'")
            assert 'makoto shinkai' in page.locator('#sdStyleDescription').inner_text()
            page.locator('[data-sd-style="anime"]').click()
            assert page.locator('#sdPreset').input_value() == ''
            page.locator('#sdRoute').select_option('chat')
            page.locator('#sdDuration').select_option('15s')
            page.locator('#sdModel').select_option('2.5')
            page.locator('#sdRoute').select_option('video')
            assert page.locator('#sdDuration').input_value() == '10s'
            page.locator('#sdSearch').fill('mountain')
            assert page.locator('.sd-job').count() == 1
            page.locator('#sdSearch').fill('')
            page.locator('[data-job-act="edit"]').first.click()
            page.locator('#sdEditText').fill('A wooden boat at dawn, cinematic tracking shot.')
            page.locator('#sdSaveEdit').click()
            page.wait_for_function("document.querySelector('#modal').classList.contains('hidden')")
            page.locator('[data-sd-mode="image"]').click()
            assert '2 cảnh chưa ghép' in page.locator('#sdPairing').inner_text()
            page.locator('[data-sd-tab="images"]').click()
            assert page.locator('#sdView-images').is_visible()
            page.locator('[data-sd-tab="media"]').click()
            assert page.locator('#sdHistory').is_visible()
            page.locator('[data-sd-tab="logs"]').click()
            assert 'Đã nhập 2 cảnh' in page.locator('#sdLogs').inner_text()
            page.locator('[data-sd-tab="queue"]').click()
            page.locator('[data-sd-mode="text"]').click()
            # Sidebar changes keep existing screens available.
            for view in ('images', 'profiles', 'create', 'seedance'):
                page.locator(f'[data-view="{view}"]').click()
            page.wait_for_timeout(200)
            overflow = page.evaluate("""() => [...document.querySelectorAll('#page-seedance button,#page-seedance input,#page-seedance select')]
              .filter(e=>e.getBoundingClientRect().width && (e.getBoundingClientRect().right > innerWidth+1)).map(e=>e.id)""")
            assert not overflow, overflow
            screenshot = Path(temp) / 'seedance-studio.png'
            page.screenshot(path=str(screenshot), full_page=True)
            # Store review screenshot in the OS temp directory, not in app data.
            review = Path(tempfile.gettempdir()) / 'videoagent-seedance-review.png'
            review.write_bytes(screenshot.read_bytes())
            page.set_viewport_size({'width': 1200, 'height': 760})
            page.wait_for_timeout(100)
            assert page.evaluate("document.querySelector('#page-seedance').scrollWidth <= document.querySelector('#page-seedance').clientWidth+1")

            # Exercise the actual native watermark action through the UI bridge on a synthetic MP4.
            test_output = Path(temp) / 'output'
            test_output.mkdir()
            fixture = test_output / 'fixture.mp4'
            ffmpeg_run(['-f','lavfi','-i','color=c=blue:s=160x90:d=1','-vf','drawbox=x=90:y=50:w=20:h=10:color=white:t=fill','-c:v','libx264','-pix_fmt','yuv420p',fixture])
            original = fixture.read_bytes()
            api._seedance.settings = SimpleNamespace(output_dir=test_output, get=settings.get)
            api._seedance.store.put('media', {'id':'fixture','title':'Watermark sample','provider':'dola','source':'fixture',
                'url':'https://v.ibytedtos.com/fixture.mp4','path':str(fixture),'localUrl':'/fixture.mp4',
                'outputDir':str(test_output),'width':160,'height':90,'duration':1,'sceneId':'','error':''})
            page.route('**/fixture.mp4', lambda route: route.fulfill(body=original, content_type='video/mp4'))
            page.evaluate('window.SeedanceStudio.refresh()')
            page.locator('[data-sd-tab="media"]').click()
            page.locator('[data-media-act="watermark"]').click()
            page.locator('#sdLogoFrame').wait_for(state='visible')
            box = page.locator('#sdLogoCanvas').bounding_box()
            page.mouse.move(box['x']+box['width']*.54, box['y']+box['height']*.51)
            page.mouse.down()
            page.mouse.move(box['x']+box['width']*.72, box['y']+box['height']*.72)
            page.mouse.up()
            assert float(page.locator('#sdLogo-w').input_value()) > 10
            page.locator('#sdRemoveLogo').click()
            deadline = time.monotonic() + 10
            while not api._seedance.store.get('media', 'fixture').get('cleanPath') and time.monotonic() < deadline:
                page.wait_for_timeout(100)
            assert fixture.read_bytes() == original
            assert (test_output / 'fixture_clean.mp4').is_file(), json.dumps(api._seedance.snapshot()['events'][-2:], ensure_ascii=True)

            # A local provider fixture exercises real Playwright editor/model/upload/submit operations.
            provider = browser.new_page()
            provider.set_content('''<button data-valid-btn="mode-select-action-btn">Pro</button>
              <div class="chat-input"><input type="file" accept="image/png"><div class="attachment"></div>
              <div data-testid="chat_input_input" contenteditable="true" style="width:500px;min-height:90px"></div>
              <button id="flow-end-msg-send">Send</button></div><div id="history"></div>
              <script>window.sent=0;
                document.querySelector('input').onchange=()=>{const im=document.createElement('img'); im.src=URL.createObjectURL(document.querySelector('input').files[0]); document.querySelector('.attachment').append(im);};
                document.querySelector('#flow-end-msg-send').onclick=()=>{window.sent++;const editor=document.querySelector('[contenteditable]');const bubble=document.createElement('div');bubble.dataset.testid='send_message';bubble.textContent=editor.innerText;document.querySelector('#history').append(bubble);editor.textContent='';};
              </script>''')
            adapter = BrowserAdapter(provider.context, provider, normalize_config({}), lambda: None, lambda *args: None)
            assert adapter.ready()
            adapter.configure()
            from PIL import Image
            image = Path(temp) / 'ref.png'
            Image.new('RGB', (20,20)).save(image)
            gen = adapter.attach({'path': str(image), 'name': 'ref.png'})
            try:
                while True:
                    next(gen)
                    provider.wait_for_timeout(100)
            except StopIteration as result:
                assert result.value['verified']
            list(adapter.submit('A boat drifting across the water.'))
            assert provider.evaluate('window.sent') == 1
            assert provider.locator('[data-testid="send_message"]').count() == 1
            assert not errors, errors
            browser.close()
        print(json.dumps({'ok': True, 'ui': 'import/edit/config/filter/navigation/responsive', 'provider_fixture': 'model + verified attachment + single acknowledged submit', 'screenshot': str(review)}, ensure_ascii=False))


if __name__ == '__main__':
    run()
