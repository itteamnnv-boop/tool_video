"""Browser regressions for Dola's wrapper editor, model selection and shared parameter panel."""
import unittest
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

from app.seedance.domain import normalize_config, StudioError
from app.seedance.provider import BrowserAdapter

VIDEO_FIXTURE = '''<button data-input-engine-actionbar-control-key="video-model" onclick="document.querySelector('#models').hidden=false">Model Seedance 2.0</button>
<div id="models" hidden><button role="menuitem" onclick="document.querySelector('[data-input-engine-actionbar-control-key]').textContent='Model Dreamina Seedance 2.5';this.parentElement.hidden=true">Dreamina Seedance 2.5</button></div>
<button id="params" aria-controls="panel" data-input-engine-actionbar-render-entry-key="creation-video-generation-params-panel" onclick="document.querySelector('#panel').hidden=false">Auto · 10s</button>
<div id="panel" role="menu" hidden><section><span>Aspect ratio</span><button onclick="ratio='16:9';update()">16:9</button><button onclick="ratio='9:16';update()">9:16</button></section>
<section><span>Duration</span><span id="duration">10s</span><span role="slider" tabindex="0" aria-valuemin="0" aria-valuemax="6" aria-valuenow="6">●</span><span>4s</span><span>10s</span></section></div>
<div data-testid="chat_input_input"><div contenteditable="true" style="width:500px;min-height:80px"></div></div>
<script>window.sent=0;let ratio='Auto';const slider=document.querySelector('[role=slider]');
function update(){document.querySelector('#duration').textContent=(4+Number(slider.getAttribute('aria-valuenow')))+'s';document.querySelector('#params').textContent=ratio+' · '+document.querySelector('#duration').textContent;}
slider.onkeydown=e=>{let v=Number(slider.getAttribute('aria-valuenow')); if(e.key==='Home')v=0;if(e.key==='ArrowRight')v=Math.min(6,v+1);slider.setAttribute('aria-valuenow',String(v));update();e.preventDefault();};
document.onkeydown=e=>{if(e.key==='Escape'){document.querySelector('#panel').hidden=true;document.querySelector('#models').hidden=true;}};</script>'''


class ProviderBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.page = self.browser.new_page()

    def tearDown(self):
        self.page.close()

    def adapter(self, config=None, context=None):
        return BrowserAdapter(context or self.page.context, self.page, normalize_config(config or {}), lambda: None, lambda *args: None)

    def test_wrapper_editor_and_pro_chat_selection_with_single_submission(self):
        self.page.set_content('''<div id="mode" style="cursor:pointer" onclick="document.querySelector('#menu').hidden=false"><span>Fast ›</span></div>
        <div id="menu" hidden><button role="menuitem" onclick="document.querySelector('#mode span').textContent='Pro ›';this.parentElement.hidden=true">Pro<br>Advanced answers</button></div>
        <div data-testid="chat_input_input"><div contenteditable="true" style="width:500px;min-height:80px"></div></div>
        <button id="flow-end-msg-send">Send</button><div id="history"></div><script>window.sent=0;
        document.querySelector('#flow-end-msg-send').onclick=()=>{window.sent++;const e=document.querySelector('[contenteditable]'),b=document.createElement('div');b.dataset.testid='send_message';b.textContent=e.innerText;document.querySelector('#history').append(b);e.textContent='';};</script>''')
        adapter = self.adapter({'generationRoute': 'chat'})
        self.assertTrue(adapter.editor().evaluate('e=>e.isContentEditable'))
        evidence = adapter.configure()
        self.assertEqual(evidence['chatMode'], 'Pro')
        self.assertFalse(evidence['videoModelVerified'])
        list(adapter.submit('A boat at dawn'))
        self.assertEqual(self.page.evaluate('window.sent'), 1)

    def test_seedance_25_is_selected_in_actual_video_control_and_shared_panel(self):
        self.page.set_content(VIDEO_FIXTURE)
        evidence = self.adapter({'generationRoute': 'video', 'duration': '5s', 'aspectRatio': '9:16'}).configure()
        self.assertTrue(evidence['videoModelVerified'])
        self.assertIn('2.5', evidence['videoModelLabel'])
        self.assertEqual(self.page.locator('#params').inner_text(), '9:16 · 5s')
        self.assertEqual(self.page.evaluate('window.sent'), 0)

    def test_unsupported_duration_fails_before_submitting_instead_of_using_default(self):
        self.page.set_content(VIDEO_FIXTURE)
        with self.assertRaises(StudioError) as caught:
            self.adapter({'generationRoute': 'video', 'duration': '15s'}).configure()
        self.assertEqual(caught.exception.code, 'CONFIG_UNSUPPORTED')
        self.assertEqual(self.page.evaluate('window.sent'), 0)

    def test_master_resolution_requests_clean_variant_and_accepts_unwatermarked_url(self):
        self.page.set_content('<div class="video-player-fixture"></div>')
        self.page.evaluate('''() => {document.querySelector('div').__reactFiberFixture={memoizedProps:{video_model:{
            fallback_api:'https://api.byteintlapi.com/video?id=abc',video_id:'abc'}}};}''')
        requests = []
        def get(url, **kwargs):
            requests.append(url)
            return SimpleNamespace(ok=True, json=lambda: {'video_info': {'main_url': 'https://v.ibytedtos.com/master.mp4?logo_type=unwatermarked'}})
        adapter = self.adapter(context=SimpleNamespace(request=SimpleNamespace(get=get)))
        media = adapter.discover()
        self.assertEqual(len(media), 1)
        self.assertEqual(media[0]['source'], 'provider_master')
        self.assertEqual(media[0]['watermarkStatus'], 'master_requested')
        self.assertEqual(parse_qs(urlsplit(requests[0]).query)['logo_type'], ['unwatermarked'])

    def test_old_quota_message_ignored_but_identical_new_toast_is_detected(self):
        self.page.set_content('<div data-testid="receive_message">Daily limit reached</div>')
        adapter = self.adapter()
        baseline = adapter.notice_snapshot()
        adapter.outcome_error(baseline)
        self.page.evaluate("() => {const el=document.createElement('div');el.setAttribute('role','alert');el.textContent='Daily limit reached';document.body.append(el);}")
        with self.assertRaises(StudioError) as caught:
            adapter.outcome_error(baseline)
        self.assertEqual(caught.exception.code, 'DAILY_LIMIT')
        self.assertEqual(caught.exception.provider_message, 'Daily limit reached')

    def test_limit_reported_during_submit_is_not_submission_uncertain(self):
        self.page.set_content('''<textarea style="width:500px"></textarea><button id="flow-end-msg-send">Send</button>
        <script>document.querySelector('button').onclick=()=>{const a=document.createElement('div');a.setAttribute('role','alert');a.textContent='Not enough credits';document.body.append(a);};</script>''')
        adapter = self.adapter()
        with self.assertRaises(StudioError) as caught:
            list(adapter.submit('A boat', baseline=adapter.notice_snapshot()))
        self.assertEqual(caught.exception.code, 'INSUFFICIENT_CREDITS')


if __name__ == '__main__':
    unittest.main()
