// Cầu nối Zalo (zca-js — thư viện KHÔNG chính thức, đăng nhập bằng tài khoản cá nhân) cho VideoAgent.
// CHỈ ĐỌC: đăng nhập (QR hoặc thông tin đã lưu), liệt kê nhóm, nghe tin nhắn nhóm. KHÔNG gửi tin / không thao tác gì.
// Giao tiếp: mỗi dòng stdout là 1 sự kiện JSON; stdin nhận lệnh JSON ({"cmd": "groups"} | {"cmd": "stop"}).
// Chạy: node zalo_bridge.mjs <đường dẫn credentials.json>   (file được tạo sau khi quét QR, chỉ nằm trên máy)
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { createInterface } from "node:readline";
import { Zalo, ThreadType, LoginQRCallbackEventType } from "zca-js";

const credsPath = process.argv[2];
const out = (obj) => process.stdout.write(JSON.stringify(obj) + "\n");
const fail = (stage, err) => out({ type: "error", stage, message: String((err && err.message) || err).slice(0, 500) });

let api = null;

async function login() {
  const zalo = new Zalo({ selfListen: false, checkUpdate: false, logging: false });
  if (credsPath && existsSync(credsPath)) {
    try {
      const creds = JSON.parse(readFileSync(credsPath, "utf8"));
      out({ type: "status", status: "connecting", message: "Đang đăng nhập bằng phiên đã lưu…" });
      return await zalo.login(creds);
    } catch (err) {
      fail("login_saved", err);  // phiên hết hạn → quét QR lại
    }
  }
  out({ type: "status", status: "need_qr", message: "Quét mã QR bằng ứng dụng Zalo trên điện thoại" });
  return await zalo.loginQR({}, (event) => {
    switch (event.type) {
      case LoginQRCallbackEventType.QRCodeGenerated:
        out({ type: "qr", image: event.data.image });
        break;
      case LoginQRCallbackEventType.QRCodeScanned:
        out({ type: "status", status: "scanned", message: `Đã quét: ${event.data.display_name} — xác nhận đăng nhập trên điện thoại` });
        break;
      case LoginQRCallbackEventType.QRCodeExpired:
        out({ type: "status", status: "need_qr", message: "Mã QR hết hạn — đang tạo mã mới" });
        event.actions.retry();
        break;
      case LoginQRCallbackEventType.QRCodeDeclined:
        out({ type: "status", status: "need_qr", message: "Đăng nhập bị từ chối trên điện thoại — đang tạo mã mới" });
        event.actions.retry();
        break;
      case LoginQRCallbackEventType.GotLoginInfo:
        if (credsPath) writeFileSync(credsPath, JSON.stringify(event.data), { encoding: "utf8", mode: 0o600 });
        break;
    }
  });
}

async function sendGroups() {
  try {
    const all = await api.getAllGroups();
    const ids = Object.keys(all.gridVerMap || {});
    const groups = [];
    for (let i = 0; i < ids.length; i += 50) {
      const info = await api.getGroupInfo(ids.slice(i, i + 50));
      for (const [id, g] of Object.entries(info.gridInfoMap || {})) {
        groups.push({ id, name: g.name || id, members: g.totalMember || (g.memVerList || []).length || 0 });
      }
    }
    groups.sort((a, b) => a.name.localeCompare(b.name, "vi"));
    out({ type: "groups", groups });
  } catch (err) {
    fail("groups", err);
  }
}

function textOf(content) {
  if (typeof content === "string") return content;
  if (content && typeof content === "object") {  // tin dạng link / ảnh có chú thích → lấy chữ + link
    return [content.title, content.description, content.href].filter((x) => typeof x === "string" && x).join("\n");
  }
  return "";
}

async function main() {
  try {
    api = await login();
  } catch (err) {
    fail("login", err);
    process.exit(2);
  }
  let name = "";
  try {
    const info = await api.fetchAccountInfo();
    name = (info && (info.profile?.displayName || info.displayName || info.zaloName)) || "";
  } catch { /* không bắt buộc */ }
  out({ type: "login", self: api.getOwnId ? api.getOwnId() : "", name });
  await sendGroups();

  api.listener.on("connected", () => out({ type: "status", status: "connected", message: "Đang nghe tin nhắn nhóm" }));
  api.listener.on("closed", (code, reason) => out({ type: "closed", code, reason: String(reason || "") }));
  api.listener.on("error", (err) => fail("listener", err));
  api.listener.on("message", (m) => {
    if (m.type !== ThreadType.Group || m.isSelf) return;
    const text = textOf(m.data.content);
    if (!text.trim()) return;
    out({ type: "message", group: m.threadId, msgId: m.data.msgId, from: m.data.dName || "", uid: m.data.uidFrom || "",
          ts: Number(m.data.ts) || Date.now(), text: text.slice(0, 8000) });
  });
  api.listener.start({ retryOnClose: true });

  createInterface({ input: process.stdin }).on("line", async (line) => {
    let cmd = {};
    try { cmd = JSON.parse(line); } catch { return; }
    if (cmd.cmd === "groups") await sendGroups();
    if (cmd.cmd === "stop") { try { api.listener.stop(); } catch { /* bỏ qua */ } process.exit(0); }
  });
}

main();
