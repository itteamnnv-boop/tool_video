"""Google Flow (labs.google/fx/tools/flow) · tạo video Veo bằng trình duyệt đã đăng nhập tài khoản Google
(profile gán "Google Flow" ở Profile trình duyệt). Mỗi video tốn tín dụng Flow của tài khoản.

Giao diện (11/2026, tiếng Việt / Anh): trang dự án có ô soạn "Bạn muốn tạo gì?" / "What do you want to create?",
nút ＋ (thêm ảnh: Tải lên / Upload), nút ⚙ tuỳ chọn (biểu tượng "tune": loại nội dung, tỉ lệ khung hình, số kết quả mỗi câu
lệnh, model), nút gửi (biểu tượng "arrow_forward"). Biểu tượng là chữ của font Google Symbols nằm trong nút → selector bám
theo chữ đó + nhãn tiếng Việt / Anh. App nhớ 1 dự án Flow (settings.flow_project_url) để mọi video nằm chung 1 chỗ.
"""
import re
import time
from collections import Counter
from pathlib import Path

from playwright.sync_api import Error as PWError
from playwright.sync_api import sync_playwright

from .base import LLMError
from ..browser_profiles import profile_session
from .browser_chat import _launch
from .grok_imagine import FETCH_BLOB_JS, _download

SITE = "flow"
HOME = "https://labs.google/fx/tools/flow"
PROJECT_MARK = "/tools/flow/project/"
PROMPT_BOX = ("textarea[placeholder*='tạo gì' i], textarea[placeholder*='create' i], "
              "[contenteditable='true'][aria-label*='tạo gì' i], [contenteditable='true'][aria-label*='create' i], "
              "div[contenteditable='true'][role='textbox'], textarea")
NEW_PROJECT = re.compile(r"(Dự án mới|New project)", re.I)
ENTER_FLOW = re.compile(r"^(Create with Flow|Tạo bằng Flow|Bắt đầu|Get started)", re.I)
TUNE_BTN = ("button:has(i:text-is('tune')), button[aria-label*='Cài đặt' i], button[aria-label*='Settings' i], "
            "button[aria-label*='Tuỳ chọn' i], button[aria-label*='Tùy chọn' i], button[aria-label*='Options' i]")
SEND_BTN = ("button:has(i:text-is('arrow_forward')), button[aria-label*='Tạo' i]:not([aria-label*='công cụ' i]), "
            "button[aria-label*='Create' i], button[aria-label*='Gửi' i], button[aria-label*='Send' i]")
CONFIRM_CROP = re.compile(r"^(Cắt và lưu|Crop and save|Lưu|Save|Xong|Done|Thêm|Add)$", re.I)
CHOICES = "[role='option'], [role='menuitem'], [role='menuitemradio'], [role='radio'], [role='tab'], li, button"
COMBOS = "[role='combobox'], button[aria-haspopup], mat-select, select"
ASPECT_WORDS = {"9:16": r"9:16|Khổ dọc|Dọc|Portrait", "16:9": r"16:9|Khổ ngang|Ngang|Landscape",
                "1:1": r"1:1|Vuông|Square"}
ANY_ASPECT = re.compile("|".join(ASPECT_WORDS.values()), re.I)
LOGIN_ERROR = ("Chưa đăng nhập Google Flow — vào Profile trình duyệt, gán “Google Flow” cho profile rồi bấm Đăng nhập "
               "(labs.google/fx/tools/flow, lần đầu có thể phải đồng ý điều khoản trong cửa sổ đó)")
ERROR_WORDS = ("không thành công", "thất bại", "failed", "không đủ tín dụng", "hết tín dụng", "insufficient credit",
               "out of credit", "quota", "hết lượt", "vi phạm", "violat", "unsafe", "không thể tạo", "không tạo được",
               "không thể tìm thấy", "couldn't generate", "could not generate", "unable to generate", "thử lại sau",
               "try again later", "something went wrong")
# mọi khối chữ (sâu nhất) đang hiện có lời báo lỗi — ô video "Không thành công", lời Tác nhân, thông báo… Trả cả bản trùng
# để so SỐ LẦN xuất hiện (dự án có sẵn ô lỗi cũ cùng chữ → chỉ tính lỗi MỚI)
ERRORS_JS = """(words) => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const hit = t => { const l = (t || '').toLowerCase(); return words.some(w => l.includes(w)); };
  const out = [];
  for (const n of document.querySelectorAll('body *')) {
    if (['SCRIPT', 'STYLE', 'TEXTAREA'].includes(n.tagName) || !vis(n)) continue;
    const t = (n.innerText || '').replace(/\\s+/g, ' ').trim();
    if (!t || t.length > 400 || !hit(t) || [...n.children].some(c => hit(c.innerText))) continue;
    out.push(t);
  }
  return out;
}"""
AGENT_TOGGLE = re.compile(r"^(Tác nhân|Agent)$", re.I)
APPROVE = re.compile(r"^(Phê duyệt|Approve|Đồng ý|Xác nhận)$", re.I)  # KHÔNG bấm "Luôn phê duyệt" / "Always approve"
COST_JS = """() => {
  const m = (document.body.innerText || '').match(/[^.?!\\n]*\\d+\\s*(tín dụng|credits?)[^.?!\\n]*[.?!]?/gi);
  return m ? m[m.length - 1].trim().slice(0, 160) : '';
}"""
MIN_VIEW_WIDTH = 100
EXPECT_S = 240


def generate_video(prompt: str, out_path: Path, *, aspect: str = "9:16", duration: str = "8s", resolution: str = "720p",
                   project_url: str = "", remember_project=None, channel: str = "chrome", show_browser: bool = False,
                   images: list[Path] | None = None, log=print, check_cancel=lambda: None, on_progress=None,
                   timeout_s: int = 1500) -> None:
    with profile_session(SITE) as prof, sync_playwright() as pw:
        try:
            ctx = _launch(pw, channel, visible=show_browser, offscreen=not show_browser, profile=prof)
        except PWError as exc:
            raise LLMError(f"Không mở được trình duyệt '{channel}': {exc}") from exc
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            _open_project(page, project_url, log)
            here = page.url.split("?")[0]
            if remember_project and PROJECT_MARK in here and here != (project_url or "").split("?")[0]:
                remember_project(here)
            _agent_off(page, log, bool(images))  # trước khi gắn ảnh: ảnh gắn ở chế độ Tác nhân không được nhận
            _settings(page, aspect, log)
            if images:
                _attach(page, images, log, check_cancel)
            before = {v["src"] for v in _videos(page)}
            old_errors = Counter(page.evaluate(ERRORS_JS, list(ERROR_WORDS)))
            box = page.locator(PROMPT_BOX).first
            box.click()
            if box.evaluate("e => e.tagName") == "TEXTAREA":
                box.fill(prompt)
            else:
                page.keyboard.insert_text(prompt)
            page.wait_for_timeout(600)
            _send(page)
            log("Đã gửi prompt — Google Flow (Veo) đang tạo video…")
            src = _wait_for_video(page, before, old_errors, timeout_s, check_cancel, on_progress, log)
            data = _fetch(ctx, page, src)
            if len(data) < 20_000:
                raise LLMError("File video tải về từ Google Flow không hợp lệ")
            Path(out_path).write_bytes(data)
        except PWError as exc:
            if "closed" in str(exc).lower():  # bạn đóng cửa sổ Chrome / Chrome tắt giữa chừng
                raise LLMError("Cửa sổ Chrome của Google Flow bị đóng giữa chừng — chạy lại khối này (đừng đóng cửa sổ "
                               "Chrome khi app đang làm)") from exc
            raise
        finally:
            try:
                ctx.close()
            except PWError:
                pass


def _needs_login(page) -> bool:
    return "accounts.google.com" in page.url


def _composer(page, timeout_ms: int):
    box = page.locator(PROMPT_BOX).first
    try:
        box.wait_for(state="visible", timeout=timeout_ms)
        return box
    except PWError:
        return None


def _click_text(page, pattern, timeout_ms: int = 3000) -> bool:
    for role in ("button", "link"):
        el = page.get_by_role(role, name=pattern).first
        try:
            if el.count() and el.is_visible():
                el.click(timeout=timeout_ms)
                return True
        except PWError:
            continue
    return False


def _open_project(page, project_url: str, log):
    """Mở dự án Flow đã nhớ; chưa có (hoặc không mở được) → trang chủ Flow → Dự án mới."""
    for url in ([project_url] if project_url else []) + [HOME]:
        page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except PWError:
            pass
        page.wait_for_timeout(2000)
        if _needs_login(page):
            raise LLMError(LOGIN_ERROR)
        if PROJECT_MARK not in page.url and _click_text(page, ENTER_FLOW):  # trang giới thiệu → vào Flow
            page.wait_for_timeout(4000)
            if _needs_login(page):
                raise LLMError(LOGIN_ERROR)
        if PROJECT_MARK not in page.url and _click_text(page, NEW_PROJECT):  # trang chủ dự án → tạo dự án mới
            log("Google Flow: tạo dự án mới (lần sau dùng lại dự án này)")
            page.wait_for_timeout(4000)
        box = _composer(page, 30_000)
        if box is not None:
            return box
        if url == project_url:
            log("Không mở được dự án Flow đã nhớ — mở trang chủ Flow", "warn")
    raise LLMError("Không thấy ô “Bạn muốn tạo gì?” của Google Flow (chưa đăng nhập, chưa đồng ý điều khoản hoặc "
                   "giao diện đã đổi) — bật “Hiện cửa sổ Chrome” để xem")


def _visible(loc) -> list:
    out = []
    for i in range(min(loc.count(), 60)):
        el = loc.nth(i)
        try:
            if el.is_visible():
                out.append(el)
        except PWError:
            continue
    return out


def _pick(page, current, want) -> bool:
    """Lựa chọn trong bảng tuỳ chọn: nút / thẻ chọn khớp `want` → bấm; hoặc ô thả xuống đang hiện giá trị khớp `current`
    → mở → chọn mục khớp `want`."""
    for el in _visible(page.locator("[role='radio'], [role='tab'], [role='option'], button[aria-pressed]")):
        text = (el.inner_text() or el.get_attribute("aria-label") or "").strip()
        if want.search(text) and len(text) < 40:
            try:
                if el.get_attribute("aria-checked") != "true" and el.get_attribute("aria-selected") != "true":
                    el.click(timeout=3000)
                    page.wait_for_timeout(500)
                return True
            except PWError:
                continue
    for combo in _visible(page.locator(COMBOS)):
        text = (combo.inner_text() or "").strip()
        if not current.search(text) or len(text) > 60:
            continue
        if want.search(text):
            return True
        try:
            combo.click(timeout=3000)
            page.wait_for_timeout(600)
            for item in _visible(page.locator(CHOICES)):
                label = (item.inner_text() or "").strip()
                if want.search(label) and len(label) < 60:
                    item.click(timeout=3000)
                    page.wait_for_timeout(500)
                    return True
            page.keyboard.press("Escape")
        except PWError:
            pass
    return False


def _settings(page, aspect: str, log) -> None:
    """⚙ Tuỳ chọn: loại = Video, tỉ lệ khung hình, 1 kết quả mỗi câu lệnh (đỡ tốn tín dụng)."""
    btn = page.locator(TUNE_BTN).first
    try:
        if not btn.count():
            log("Không thấy nút tuỳ chọn của Google Flow — dùng tuỳ chọn đang đặt trên Flow", "warn")
            return
        btn.click(timeout=4000)
        page.wait_for_timeout(1000)
    except PWError:
        log("Không mở được tuỳ chọn của Google Flow — dùng tuỳ chọn đang đặt trên Flow", "warn")
        return
    _pick(page, re.compile(r"^(Hình ảnh|Image|Video)", re.I), re.compile(r"^\s*Video\s*$", re.I))
    want = ASPECT_WORDS.get(aspect)
    if want and not _pick(page, ANY_ASPECT, re.compile(want, re.I)):
        log(f"Không đặt được tỉ lệ {aspect} trên Google Flow — dùng tỉ lệ đang đặt", "warn")
    if not _pick(page, re.compile(r"^\s*[1-4]\s*$"), re.compile(r"^\s*1\s*$")):
        log("Không đặt được “1 kết quả mỗi câu lệnh” trên Google Flow — nếu Flow tạo nhiều video thì tốn thêm tín dụng, "
            "app lấy video đầu tiên", "warn")
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)


THUMBS_JS = """() => {
  const box = document.querySelector("textarea, [contenteditable='true']");
  const area = box ? (box.closest('form') || box.parentElement.parentElement.parentElement) : document.body;
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 8 && r.height > 8; };
  return [...area.querySelectorAll('img')].filter(vis).length;
}"""


def _thumbs(page) -> int:
    try:
        return int(page.evaluate(THUMBS_JS) or 0)
    except PWError:
        return 0


# nút ＋ của khung soạn: biểu tượng Google Symbols / nhãn; không có → nút ngoài cùng bên trái của khung soạn
MARK_PLUS_JS = """() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const box = document.querySelector("textarea, [contenteditable='true']");
  if (!box) return '';
  let area = box.parentElement;
  while (area && area !== document.body && [...area.querySelectorAll('button')].filter(vis).length < 3) area = area.parentElement;
  const btns = [...(area || document.body).querySelectorAll("button, [role='button']")].filter(vis);
  const icon = /^(add|add_2|add_circle|add_box|attach_file|add_photo_alternate|image|photo|upload|file_upload|\\+|＋)$/i;
  const label = /(thêm|add|tải|upload|đính kèm|attach|hình ảnh|image|media|nội dung)/i;
  let pick = btns.find(b => icon.test((b.innerText || '').trim()))
    || btns.find(b => label.test(b.getAttribute('aria-label') || '') && !/gửi|send|tạo$|create$/i.test(b.getAttribute('aria-label') || ''));
  if (!pick && btns.length) pick = btns.slice().sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left)[0];
  document.querySelectorAll('[data-va-plus]').forEach(e => e.removeAttribute('data-va-plus'));
  if (pick) pick.setAttribute('data-va-plus', '1');
  return btns.map(b => (b.getAttribute('aria-label') || b.innerText || '?').trim().split('\\n')[0].slice(0, 24)).join(' | ');
}"""
UPLOAD_TEXT = re.compile(r"^\s*(Tải( hình ảnh| ảnh| tệp| tệp tin)? lên|Upload( an?)?( image| file| media| photo)?s?|"
                         r"Từ máy tính|From (your )?computer|Từ thiết bị|From device|Chọn tệp|Choose file|Browse)", re.I)
UPLOAD_CANDIDATES = ("button, [role='menuitem'], [role='option'], [role='button'], [role='tab'], li, a, label, "
                     "div[tabindex], span")
MENU_TEXT_JS = """() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  return [...document.querySelectorAll("[role='menu'] *, [role='dialog'] *, [role='listbox'] *, [role='menuitem']")]
    .filter(e => vis(e) && e.children.length === 0 && (e.innerText || '').trim())
    .map(e => e.innerText.trim().slice(0, 30)).slice(0, 20).join(' | ');
}"""
DROP_JS = """async ([b64, name, mime]) => {
  const bin = atob(b64); const u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  const dt = new DataTransfer(); dt.items.add(new File([u8], name, {type: mime}));
  const target = document.querySelector("textarea, [contenteditable='true']") || document.body;  // nổi lên mọi khung bao
  for (const type of ['dragenter', 'dragover', 'drop'])
    target.dispatchEvent(new DragEvent(type, {bubbles: true, cancelable: true, dataTransfer: dt}));
  return true;
}"""


def _click_upload_item(page) -> bool:
    for el in _visible(page.locator(UPLOAD_CANDIDATES)):
        try:
            text = (el.inner_text() or el.get_attribute("aria-label") or "").strip()
            if text and len(text) < 50 and UPLOAD_TEXT.search(text):
                el.click(timeout=3000)
                return True
        except PWError:
            continue
    return False


def _upload_one(page, f: str, log) -> str:
    """1 ảnh: ＋ → (Tải lên) → hộp chọn file; ô tải file hiện ra; kéo-thả vào khung soạn. Trả cách đã dùng ("" = không được)."""
    page.evaluate(MARK_PLUS_JS)
    plus = page.locator("[data-va-plus]").first
    try:
        with page.expect_file_chooser(timeout=7000) as chooser:
            if plus.count():
                plus.click(timeout=4000)
                page.wait_for_timeout(1200)
            if not _click_upload_item(page):
                page.wait_for_timeout(1500)  # menu / hộp thoại mở chậm
                _click_upload_item(page)
        chooser.value.set_files(f)
        return "nút ＋ → Tải lên"
    except PWError:
        pass
    inp = page.locator("input[type='file']")
    for i in range(inp.count()):
        accept = (inp.nth(i).get_attribute("accept") or "").lower()
        if accept and not re.search(r"image|\*|png|jpe?g|webp", accept):
            continue
        try:
            inp.nth(i).set_input_files(f, timeout=20_000)
            return "ô tải file"
        except PWError:
            continue
    page.keyboard.press("Escape")
    try:
        import base64

        data = base64.b64encode(Path(f).read_bytes()).decode()
        mime = "image/png" if f.lower().endswith(".png") else "image/jpeg"
        page.evaluate(DROP_JS, [data, Path(f).name, mime])
        return "kéo-thả vào khung soạn"
    except PWError as exc:
        log(f"Google Flow: kéo-thả ảnh không được ({str(exc).splitlines()[0][:80]})", "warn")
        return ""


PICK_CONFIRM = re.compile(r"^(Thêm|Xong|Chọn|Chèn|Sử dụng|Dùng|Add|Done|Select|Insert|Use)\b", re.I)
LIBRARY_WAIT_S = 45
# tên ảnh trong thư viện dự án (bảng ＋ Thêm thành phần) theo thứ tự hiện — Flow xếp ảnh MỚI NHẤT lên đầu
LIB_JS = """() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const ext = /\\.(png|jpe?g|webp|gif|heic)$/i;
  const box = document.querySelector("textarea, [contenteditable='true']");
  const has = r => [...r.querySelectorAll('*')].some(e => !e.children.length && vis(e) && ext.test((e.innerText || '').trim()));
  const pops = [...document.querySelectorAll("[role='dialog'], [role='menu'], [role='listbox'], [popover], "
    + "[data-radix-popper-content-wrapper], [class*='popover' i], [class*='picker' i]")].filter(r => vis(r) && has(r));
  const root = pops.length ? pops[pops.length - 1] : document.body;  // bảng ＋ đang mở (không lấy lưới dự án phía sau)
  const out = [];
  for (const e of root.querySelectorAll('*')) {
    if (e.children.length || !vis(e) || (box && box.contains(e))) continue;
    const t = (e.innerText || e.textContent || '').trim();
    if (t && t.length < 120 && ext.test(t)) { e.setAttribute('data-va-lib', String(out.length)); out.push(t); }
  }
  return out;
}"""


def _confirm_crop(page) -> None:
    for btn in _visible(page.locator("button")):  # hộp cắt ảnh / xác nhận sau khi tải lên
        try:
            if CONFIRM_CROP.search((btn.inner_text() or "").strip()):
                btn.click(timeout=3000)
                page.wait_for_timeout(1000)
                return
        except PWError:
            continue


def _open_plus(page) -> bool:
    page.evaluate(MARK_PLUS_JS)
    plus = page.locator("[data-va-plus]").first
    try:
        if plus.count():
            plus.click(timeout=4000)
            page.wait_for_timeout(1200)
            return True
    except PWError:
        pass
    return False


def _library(page) -> list:
    """Mở ＋ → danh sách tên ảnh trong thư viện (mới nhất trước); để bảng mở (đánh dấu data-va-lib để bấm)."""
    page.evaluate("() => document.querySelectorAll('[data-va-lib]').forEach(e => e.removeAttribute('data-va-lib'))")
    if not _open_plus(page):
        return []
    try:
        return list(page.evaluate(LIB_JS) or [])
    except PWError:
        return []


def _close(page) -> None:
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)


# từ chữ tên ảnh → ô ảnh bao quanh (có ảnh nhỏ / là nút / ô chọn) để bấm — chữ tên thường chỉ là nhãn nằm trên ô
TILE_JS = """(i) => {
  const leaf = document.querySelector(`[data-va-lib='${i}']`);
  if (!leaf) return null;
  // ô ảnh = khung lớn nhất bao quanh tên mà vẫn chỉ chứa ĐÚNG 1 tên ảnh (không lẫn ô ảnh khác, không phụ thuộc thẻ / role)
  let e = leaf;
  while (e.parentElement && e.parentElement !== document.body
         && e.parentElement.querySelectorAll('[data-va-lib]').length === 1) e = e.parentElement;
  document.querySelectorAll('[data-va-tile]').forEach(x => x.removeAttribute('data-va-tile'));
  e.setAttribute('data-va-tile', '1');
  e.scrollIntoView({block: 'center'});
  const r = e.getBoundingClientRect();
  return [r.x + r.width / 2, r.y + r.height / 2];
}"""
PICKED_JS = """() => {
  const t = document.querySelector('[data-va-tile]');
  if (!t || !t.isConnected) return 'closed';
  const sel = t.closest("[aria-selected='true'], [aria-checked='true'], [aria-pressed='true'], [data-state='checked'], "
    + "[data-selected='true']") || t.querySelector("[aria-selected='true'], [aria-checked='true'], input:checked");
  const r = t.getBoundingClientRect();
  return sel ? 'selected' : (r.width === 0 || r.height === 0 ? 'closed' : '');
}"""


def _pick_tile(page, index: int) -> str:
    """Bấm ảnh thứ `index` trong bảng ＋ đang mở → "" nếu được (bảng đóng / ảnh được chọn / ảnh vào ô nhập), không thì
    lý do. Thử lần lượt: bấm thường → bấm bỏ qua lớp phủ → bấm chuột giữa ô → lệnh click trực tiếp."""
    try:
        pos = page.evaluate(TILE_JS, index)
    except PWError as exc:
        return str(exc).splitlines()[0][:100]
    if not pos:
        return "không thấy ô ảnh"
    thumbs = _thumbs(page)
    tile = page.locator("[data-va-tile]").first
    tries = (("bấm", lambda: tile.click(timeout=3000)), ("bấm bỏ qua lớp phủ", lambda: tile.click(timeout=3000, force=True)),
             ("bấm chuột", lambda: page.mouse.click(pos[0], pos[1])),
             ("click()", lambda: page.evaluate("() => document.querySelector('[data-va-tile]').click()")))
    last = ""
    for name, act in tries:
        try:
            act()
        except PWError as exc:
            last = f"{name}: {str(exc).splitlines()[0][:80]}"
            continue
        page.wait_for_timeout(1000)
        confirm = next((b for b in _visible(page.locator("button")) if PICK_CONFIRM.search((b.inner_text() or "").strip())),
                       None)
        if confirm is not None:  # chọn nhiều → nút xác nhận
            try:
                confirm.click(timeout=3000)
                page.wait_for_timeout(800)
            except PWError:
                pass
            return ""
        try:
            state = page.evaluate(PICKED_JS)
        except PWError:
            state = "closed"
        if state or _thumbs(page) > thumbs:
            return ""
        last = f"{name}: không có tác dụng"
    return last or "không bấm được"


def _diagnose(page) -> str:
    try:
        buttons = page.evaluate(MARK_PLUS_JS)
        menu = page.evaluate(MENU_TEXT_JS) if _open_plus(page) else ""
        page.keyboard.press("Escape")
    except PWError:
        buttons, menu = "", ""
    return f"Nút trong khung soạn: {buttons or 'không thấy'}; bấm ＋ hiện: {menu or 'không có menu'}"


def _attach(page, images: list[Path], log, check_cancel) -> None:
    """Ảnh (khung đầu / thành phần) → Flow: tải lên thư viện dự án với TÊN RIÊNG (không lẫn ảnh cũ trùng tên), rồi
    ＋ “Thêm thành phần vào ô nhập” → bấm đúng ảnh đó để đưa vào ô nhập. Trang tự đưa ảnh vào ô nhập khi tải → bỏ bước
    chọn. Không được → báo lỗi kèm các nút đang thấy (không gửi prompt, không tốn tín dụng)."""
    import shutil
    import tempfile

    from .uploads import wait_uploads

    stamp = int(time.time())
    folder = Path(tempfile.mkdtemp(prefix="va_flow_"))
    named = []
    for i, p in enumerate(images, 1):
        dst = folder / f"va{stamp}_{i}{Path(p).suffix.lower() or '.png'}"
        shutil.copy2(p, dst)
        named.append(dst)
    log(f"Đang tải {len(named)} ảnh lên Google Flow…")
    lib_before = _library(page)
    _close(page)
    log(f"Google Flow: thư viện dự án đang có {len(lib_before)} ảnh")
    before = _thumbs(page)
    ways = []
    for f in named:
        ways.append(_upload_one(page, str(f), log))
        page.wait_for_timeout(1500)
        _confirm_crop(page)
    wait_uploads(page, log, check_cancel=check_cancel)
    page.keyboard.press("Escape")
    page.wait_for_timeout(800)
    how = ", ".join(sorted({w for w in ways if w})) or "?"
    if _thumbs(page) >= before + len(named):  # trang tự đưa ảnh vào ô nhập
        log(f"Đã đính kèm {len(named)} ảnh lên Google Flow ({how})")
        return
    # chờ ảnh vừa tải hiện trong thư viện: theo tên riêng (va<stamp>_k) hoặc số ảnh tăng thêm
    tag = f"va{stamp}_"
    deadline, lib = time.time() + LIBRARY_WAIT_S, []
    while True:
        check_cancel()
        lib = _library(page)
        mine = [n for n in lib if tag in n]
        if len(mine) >= len(named) or len(lib) >= len(lib_before) + len(named) or time.time() > deadline:
            break
        _close(page)
        page.wait_for_timeout(3000)
    _close(page)
    log(f"Google Flow: thư viện sau khi tải có {len(lib)} ảnh (đầu danh sách: {', '.join(lib[:4]) or 'trống'})")
    if mine:
        targets = [lib.index(n) for n in mine]
        how += " → chọn theo tên"
    elif len(lib) > len(lib_before):
        targets = list(range(min(len(named), len(lib) - len(lib_before))))  # ảnh mới nhất ở đầu danh sách
        how += f" → chọn {len(targets)} ảnh mới nhất (Flow đổi tên ảnh)"
    else:
        raise LLMError("Ảnh đã gửi lên Google Flow nhưng không hiện thêm trong thư viện ＋ “Thêm thành phần” "
                       f"(trước {len(lib_before)}, sau {len(lib)} ảnh) — chưa gửi prompt. {_diagnose(page)}. Gửi dòng "
                       "này để sửa; bật “Hiện cửa sổ Chrome” để xem")
    picked, why = [], ""
    for k in targets:  # mỗi lần chọn bảng ＋ có thể tự đóng → mở lại, đánh dấu lại rồi bấm
        names = _library(page)
        if k >= len(names):
            why = f"bảng ＋ chỉ có {len(names)} ảnh"
        else:
            err = _pick_tile(page, k)
            if err:
                why = err
            else:
                picked.append(names[k])
        _close(page)
    if not picked:
        raise LLMError(f"Không bấm chọn được ảnh trong ＋ “Thêm thành phần” của Google Flow ({why}) — chưa gửi prompt. "
                       f"{_diagnose(page)}. Gửi dòng này để sửa")
    if len(picked) < len(named):
        log(f"Google Flow: chỉ đưa được {len(picked)}/{len(named)} ảnh vào ô nhập", "warn")
    if _thumbs(page) <= before:
        log("Đã chọn ảnh trong thư viện Flow nhưng chưa thấy ảnh nhỏ trong ô nhập — vẫn gửi (xem lại video có dùng ảnh "
            "không)", "warn")
    log(f"Đã đính kèm {len(picked)} ảnh lên Google Flow ({how}: {', '.join(picked)})")
    shutil.rmtree(folder, ignore_errors=True)


def _send(page) -> None:
    btn = page.locator(SEND_BTN).last
    try:
        if btn.count() and btn.is_visible() and btn.is_enabled():
            btn.click(timeout=5000)
            return
    except PWError:
        pass
    page.keyboard.press("Enter")


ICON_PREFIX = re.compile(r"^[a-z][a-z0-9_]*(\s+|(?=[A-ZÀ-ỸĐ]))")  # tên biểu tượng Google Symbols dính đầu nhãn


def _last_line(el) -> str:
    """Chữ của nút bỏ tên biểu tượng Google Symbols: "check\\nPhê duyệt" / "check Phê duyệt" / "checkPhê duyệt" →
    "Phê duyệt"."""
    lines = [s.strip() for s in (el.inner_text() or "").split("\n") if s.strip()]
    text = lines[-1] if lines else (el.get_attribute("aria-label") or "").strip()
    rest = ICON_PREFIX.sub("", text, count=1)
    return rest if rest.strip() else text


# chip "Tác nhân" trong khung soạn: đánh dấu + trạng thái (thuộc tính bật/tắt, không có thì theo màu nền — chip bật
# nền SÁNG như ảnh chụp Flow 11/2026)
AGENT_JS = """() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const re = /^(Tác nhân|Agent)$/i;
  const lines = e => (e.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean);
  let chip = [...document.querySelectorAll('body *')].find(e => vis(e) && !['TEXTAREA', 'SCRIPT'].includes(e.tagName)
    && lines(e).length && re.test(lines(e).slice(-1)[0]) && lines(e).length <= 2 && e.querySelectorAll('*').length < 8);
  if (!chip) return null;
  const btn = chip.closest("button, [role='button'], [role='switch'], [role='checkbox'], [role='tab']") || chip;
  document.querySelectorAll('[data-va-agent]').forEach(x => x.removeAttribute('data-va-agent'));
  btn.setAttribute('data-va-agent', '1');
  const st = ['aria-pressed', 'aria-checked', 'aria-selected', 'data-state'].map(a => btn.getAttribute(a) || '').join(' ');
  let e = btn, bg = '';
  for (let d = 0; d < 4 && e; d++, e = e.parentElement) {
    const c = getComputedStyle(e).backgroundColor;
    if (c && !/rgba\\(\\s*0,\\s*0,\\s*0,\\s*0\\)|transparent/.test(c)) { bg = c; break; }
  }
  const m = bg.match(/\\d+(\\.\\d+)?/g) || [];
  const lum = m.length >= 3 ? (0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]) / 255 : -1;
  return {state: st.trim(), lum};
}"""
MODE_OPTION = re.compile(r"(Thành phần sang video|Ingredients to video|Văn bản sang video|Text to video|"
                         r"Khung hình sang video|Frames to video|^Video$|^Tạo video$)", re.I)


def _agent_on(info) -> bool | None:
    if not info:
        return None
    if re.search(r"\b(true|on|checked|active)\b", info["state"]):
        return True
    if re.search(r"\b(false|off|unchecked|inactive)\b", info["state"]):
        return False
    return info["lum"] > 0.6 if info["lum"] >= 0 else None


def _agent_off(page, log, with_images: bool = False) -> None:
    """Chế độ “Tác nhân” đang bật → tắt: prompt + ảnh đi thẳng vào bộ tạo video (ở chế độ Tác nhân ảnh đính kèm không
    được nhận — “Không thể tìm thấy ID hình ảnh hợp lệ”, và Tác nhân hỏi phê duyệt chi phí)."""
    try:
        info = page.evaluate(AGENT_JS)
    except PWError:
        return
    on = _agent_on(info)
    if not on:
        if on is None and info:
            log("Google Flow: không biết chế độ “Tác nhân” đang bật hay tắt — để nguyên", "warn")
        return
    try:
        page.locator("[data-va-agent]").first.click(timeout=3000)
        page.wait_for_timeout(900)
        opts = [o for o in _visible(page.locator("[role='option'], [role='menuitem'], [role='menuitemradio'], li, button"))
                if MODE_OPTION.search(_last_line(o))]
        if opts:  # chip mở menu chọn chế độ → chọn chế độ tạo video
            pref = re.compile(r"Thành phần|Ingredients" if with_images else r"Văn bản|Text", re.I)
            pick = next((o for o in opts if pref.search(_last_line(o))), opts[0])
            label = _last_line(pick)
            pick.click(timeout=3000)
            page.wait_for_timeout(800)
            log(f"Google Flow: đổi chế độ “Tác nhân” → “{label}”")
            return
        after = _agent_on(page.evaluate(AGENT_JS))
        log("Google Flow: tắt chế độ “Tác nhân” — gửi thẳng vào bộ tạo video" if after is not True
            else "Google Flow: bấm “Tác nhân” nhưng vẫn đang bật — Flow có thể hỏi phê duyệt chi phí", "warn"
            if after is True else "info")
    except PWError:
        log("Google Flow: không tắt được chế độ “Tác nhân”", "warn")


def _approve(page, log, done: list) -> None:
    """Flow (Tác nhân) hỏi phê duyệt chi phí → bấm “Phê duyệt” 1 lần (bạn đã bấm chạy khối Video); không bấm “Luôn …”."""
    if len(done) >= 2:
        return
    for el in _visible(page.locator("button, [role='button'], [role='option'], [role='menuitem'], [role='radio']")):
        try:
            if APPROVE.search(_last_line(el)):
                cost = page.evaluate(COST_JS)
                el.click(timeout=3000)
                done.append(cost)
                log(f"Google Flow hỏi phê duyệt chi phí ({cost or 'không rõ'}) — đã bấm “Phê duyệt” 1 lần", "warn")
                page.wait_for_timeout(1500)
                return
        except PWError:
            continue


# video trong dự án Flow: ô lưới / khung Tác nhân chỉ hiện ẢNH THU NHỎ + ▶, thẻ <video> chưa nạp (preload none) → chưa có
# độ dài, đường dẫn có thể nằm ở <source> con. Nhận cả video chưa nạp (không đòi độ dài).
FLOW_VIDEOS_JS = """() => [...document.querySelectorAll('video')].map(v => {
  const src = v.currentSrc || v.src || ((v.querySelector('source') || {}).src) || '';
  const r = v.getBoundingClientRect();
  return {src, dur: isFinite(v.duration) ? v.duration : 0, w: Math.round(r.width)};
}).filter(v => v.src && !v.src.startsWith('data:'))"""
# ô video có nút ▶ (biểu tượng Google Symbols / nhãn) → rê chuột để Flow nạp thẻ <video> của ô đó
PLAY_TILES_JS = """() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 40 && r.height > 40; };
  const out = [];
  for (const e of document.querySelectorAll('i, span, [aria-label]')) {
    const t = ((e.innerText || '') + ' ' + (e.getAttribute('aria-label') || '')).trim().toLowerCase();
    if (!/(^|\\s)(play_circle|play_arrow|phát|play)(\\s|$)/.test(t)) continue;
    let tile = e;
    for (let d = 0; d < 6 && tile.parentElement && !(vis(tile) && tile.querySelector('img, video')); d++) tile = tile.parentElement;
    if (!vis(tile) || !tile.querySelector('img, video')) continue;
    const r = tile.getBoundingClientRect();
    out.push([Math.round(r.x + r.width / 2), Math.round(r.y + r.height / 2)]);
  }
  return out.slice(0, 6);
}"""


def _videos(page) -> list:
    try:
        return list(page.evaluate(FLOW_VIDEOS_JS) or [])
    except PWError:
        return []


def _hover_tiles(page) -> None:
    """Rê chuột lên các ô ▶ (mới nhất trước) → Flow nạp video của ô đó; xong đưa chuột ra chỗ trống."""
    try:
        for x, y in page.evaluate(PLAY_TILES_JS) or []:
            page.mouse.move(x, y)
            page.wait_for_timeout(700)
        page.mouse.move(5, 5)
    except PWError:
        pass


def _wait_for_video(page, before: set, old_errors: Counter, timeout_s: int, check_cancel, on_progress, log=print) -> str:
    t0 = time.time()
    stable, since, last_note, hovered = "", 0.0, 0.0, 0.0
    approved: list = []
    while time.time() - t0 < timeout_s:
        check_cancel()
        allv = _videos(page)
        fresh = [v for v in allv if v["src"] not in before and (v.get("w", 0) >= MIN_VIEW_WIDTH or v.get("w", 0) == 0)]
        if fresh:
            src = fresh[0]["src"]
            if src != stable:
                stable, since = src, time.time()
                log(f"Google Flow: thấy video mới — chờ ổn định rồi tải về ({len(fresh)} video mới / {len(allv)} trên trang)")
            elif time.time() - since > 5:
                return src
        else:
            if time.time() - hovered > 15 and time.time() - t0 > 20:  # video xong mà chưa nạp → rê chuột vào ô ▶
                _hover_tiles(page)
                hovered = time.time()
            if time.time() - last_note > 60:
                log(f"Google Flow: đang chờ video ({int(time.time() - t0)} giây) — trang có {len(allv)} video, "
                    f"{len(before)} có từ trước", "info")
                last_note = time.time()
            _approve(page, log, approved)
            now = Counter(page.evaluate(ERRORS_JS, list(ERROR_WORDS)))
            new = [t for t, n in now.items() if n > old_errors.get(t, 0)]
            if new:
                detail = max(new, key=len)  # câu dài nhất thường là lời giải thích (vd lời Tác nhân)
                raise LLMError(f"Google Flow báo lỗi: {detail[:300]}")
        if on_progress:
            on_progress(min(95, int(100 * (time.time() - t0) / EXPECT_S)))
        page.wait_for_timeout(3000)
    raise LLMError("Google Flow chưa tạo xong video (hết thời gian chờ) — video có thể vẫn xong trong dự án Flow")


def _fetch(ctx, page, src: str) -> bytes:
    import base64

    if src.startswith("blob:"):
        return base64.b64decode(page.evaluate(FETCH_BLOB_JS, src))
    try:
        resp = ctx.request.get(src, headers={"Referer": "https://labs.google/"}, timeout=180_000)
        if resp.ok:
            return resp.body()
    except PWError:
        pass
    return _download(ctx, page, src)
