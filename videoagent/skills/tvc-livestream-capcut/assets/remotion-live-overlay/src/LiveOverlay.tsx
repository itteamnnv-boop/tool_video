import React from "react";
import {
  AbsoluteFill,
  Img,
  interpolate,
  random,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { Fx, ProductFx, Transitions } from "./ProductFx";

export type LiveOverlayProps = {
  durationSec: number;
  shopName: string;
  likes: string;
  viewers: number;
  productTitle: string;
  productLine2: string;
  productLine3: string;
  hotline: string;
  avatar: string; // đường dẫn trong public/ (staticFile)
  product: string;
  clips: { start: number; end: number; comments: [string, string][] }[];
  joiners: string[];
  fx?: Fx[]; // hiệu ứng sản phẩm xuất hiện / huy hiệu giá
};

const FONT = "'Segoe UI', Arial, sans-serif";
const PINK = "#FF4062";
const NAME_COLORS = ["#FFC850", "#82DCFF", "#AAFF96", "#FFA0C8"];

const Heart: React.FC<{ size: number; color: string }> = ({ size, color }) => (
  <svg width={size} height={size} viewBox="0 0 24 24">
    <path
      fill={color}
      d="M12 21s-7.5-4.6-10-9.3C.4 8.3 2.3 4 6.3 4c2.2 0 3.7 1.3 4.7 2.8C12 5.3 13.5 4 15.7 4c4 0 5.9 4.3 4.3 7.7C19.5 16.4 12 21 12 21z"
    />
  </svg>
);

const TopBar: React.FC<LiveOverlayProps> = (p) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const dot = 0.45 + 0.55 * Math.abs(Math.sin((frame / fps) * Math.PI));
  const viewers = Math.floor(p.viewers + frame * 0.35 + 18 * Math.sin(frame / 40));
  return (
    <>
      <div
        style={{
          position: "absolute", left: 30, top: 50, width: 530, height: 100, borderRadius: 50,
          background: "rgba(0,0,0,0.43)", display: "flex", alignItems: "center",
        }}
      >
        <Img src={staticFile(p.avatar)} style={{ width: 84, height: 84, borderRadius: 42, marginLeft: 8, objectFit: "cover" }} />
        <div style={{ marginLeft: 16, flex: 1, overflow: "hidden" }}>
          <div style={{ color: "white", fontSize: 34, fontWeight: 700, whiteSpace: "nowrap" }}>{p.shopName}</div>
          <div style={{ color: "#e6e6e6", fontSize: 24 }}>{p.likes} lượt thích</div>
        </div>
        <div style={{ background: PINK, color: "white", fontSize: 22, fontWeight: 700, borderRadius: 28, padding: "14px 18px", marginRight: 14 }}>
          + Theo dõi
        </div>
      </div>
      <div
        style={{
          position: "absolute", left: 600, top: 70, width: 120, height: 56, borderRadius: 10, background: "#FF2050",
          display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
        }}
      >
        <div style={{ width: 12, height: 12, borderRadius: 6, background: "white", opacity: dot }} />
        <span style={{ color: "white", fontSize: 30, fontWeight: 800 }}>LIVE</span>
      </div>
      <div
        style={{
          position: "absolute", left: 732, top: 70, width: 188, height: 56, borderRadius: 28, background: "rgba(0,0,0,0.47)",
          display: "flex", alignItems: "center", paddingLeft: 18, gap: 10, color: "white", fontSize: 28, fontWeight: 700,
        }}
      >
        <svg width="26" height="20" viewBox="0 0 26 20"><ellipse cx="13" cy="10" rx="11" ry="8" fill="none" stroke="white" strokeWidth="3" /><circle cx="13" cy="10" r="4" fill="white" /></svg>
        {viewers.toLocaleString("de-DE")}
      </div>
      <div style={{ position: "absolute", left: 985, top: 66, color: "white", fontSize: 54 }}>×</div>
    </>
  );
};

const FloatingHearts: React.FC = () => {
  const frame = useCurrentFrame();
  const LIFE = 75;
  const EVERY = 7;
  const items = [];
  for (let k = Math.max(0, Math.floor((frame - LIFE) / EVERY)); k * EVERY <= frame; k++) {
    const age = frame - k * EVERY;
    if (age < 0 || age > LIFE) continue;
    const t = age / LIFE;
    const sway = Math.sin(t * Math.PI * 2 + random(`s${k}`) * 6) * 28;
    const size = 34 + random(`z${k}`) * 30;
    const colors = ["#FF4670", "#FF8CAA", "#FF5A82", "#FFB4C8", "#FF2D55", "#FFD166"];
    items.push(
      <div
        key={k}
        style={{
          position: "absolute",
          left: 975 + sway - size / 2 + (random(`x${k}`) - 0.5) * 30,
          top: 1330 - t * 520,
          opacity: interpolate(t, [0, 0.1, 0.7, 1], [0, 1, 0.9, 0]),
          transform: `scale(${interpolate(t, [0, 0.15], [0.3, 1], { extrapolateRight: "clamp" })})`,
        }}
      >
        <Heart size={size} color={colors[Math.floor(random(`c${k}`) * colors.length)]} />
      </div>,
    );
  }
  return <>{items}</>;
};

const Comments: React.FC<LiveOverlayProps> = ({ clips, joiners }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const all: { at: number; name: string; text: string; color: string }[] = [];
  clips.forEach((c) =>
    c.comments.forEach(([name, text], k) =>
      all.push({ at: Math.round((c.start + 0.5 + k * 1.7) * fps), name, text, color: NAME_COLORS[all.length % 4] }),
    ),
  );
  const shown = all.filter((c) => c.at <= frame);
  const BASE = 1626;
  const ROW = 74;
  // thông báo "vừa tham gia" xoay vòng mỗi 5s
  const slot = Math.floor(frame / (5 * fps));
  const inSlot = frame - slot * 5 * fps;
  const joinOpacity = interpolate(inSlot, [0, 8, 50, 62], [0, 1, 1, 0], { extrapolateRight: "clamp" });
  return (
    <>
      {shown.map((c, i) => {
        // vị trí trượt mượt: mỗi bình luận mới hơn đẩy dòng này lên 1 hàng
        let lift = 0;
        for (let j = i + 1; j < shown.length; j++) {
          lift += spring({ frame: frame - shown[j].at, fps, config: { damping: 18, stiffness: 160 } });
        }
        const enter = spring({ frame: frame - c.at, fps, config: { damping: 14, stiffness: 140 } });
        const opacity = interpolate(lift, [2.6, 3.4], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) * enter;
        if (opacity <= 0.01) return null;
        return (
          <div
            key={i}
            style={{
              position: "absolute", left: 30, top: BASE - lift * ROW, maxWidth: 630, height: 62, borderRadius: 31,
              background: "rgba(0,0,0,0.47)", display: "flex", alignItems: "center", padding: "0 24px", gap: 12,
              opacity, transform: `translateX(${(1 - enter) * -60}px)`, fontFamily: FONT, whiteSpace: "nowrap", overflow: "hidden",
            }}
          >
            <span style={{ color: c.color, fontSize: 28, fontWeight: 700 }}>{c.name}</span>
            <span style={{ color: "white", fontSize: 30, overflow: "hidden", textOverflow: "ellipsis" }}>{c.text}</span>
          </div>
        );
      })}
      <div
        style={{
          position: "absolute", left: 30, top: BASE - 3.3 * ROW - 64, height: 54, borderRadius: 27, padding: "0 22px",
          background: "rgba(255,170,0,0.75)", display: "flex", alignItems: "center", gap: 10, opacity: joinOpacity,
          transform: `translateX(${interpolate(joinOpacity, [0, 1], [-40, 0])}px)`, color: "white", fontSize: 26, fontWeight: 700,
        }}
      >
        <Heart size={26} color="white" /> {joiners[slot % Math.max(1, joiners.length)] ?? "Khách"} vừa tham gia
      </div>
    </>
  );
};

const CartCard: React.FC<LiveOverlayProps> = (p) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const cycle = 4 * fps;
  const bounce = spring({ frame: frame % cycle, fps, config: { damping: 8, stiffness: 180 } });
  const scale = 1 + 0.05 * Math.sin(bounce * Math.PI);
  const shine = interpolate(frame % (3 * fps), [0, 30], [-120, 360], { extrapolateRight: "clamp" });
  return (
    <div style={{ position: "absolute", left: 696, top: 1360, width: 360, transform: `scale(${scale})`, transformOrigin: "50% 100%" }}>
      <div style={{ display: "inline-block", background: "#FFAA00", color: "white", fontSize: 28, fontWeight: 700, borderRadius: 28, padding: "12px 26px", marginBottom: 14 }}>
        Giỏ hàng (1)
      </div>
      <div style={{ background: "rgba(255,255,255,0.97)", borderRadius: 26, padding: 14, boxShadow: "0 10px 24px rgba(0,0,0,0.45)" }}>
        <div style={{ display: "flex", gap: 12 }}>
          <Img src={staticFile(p.product)} style={{ width: 150, height: 150, objectFit: "contain" }} />
          <div style={{ paddingTop: 8, overflow: "hidden" }}>
            <div style={{ color: "#146E28", fontSize: 30, fontWeight: 800 }}>{p.productTitle}</div>
            <div style={{ color: "#E65A00", fontSize: 26, fontWeight: 700 }}>{p.productLine2}</div>
            <div style={{ color: "#3c3c3c", fontSize: 22 }}>{p.productLine3}</div>
          </div>
        </div>
        {p.hotline ? <div style={{ color: "#C81428", fontSize: 26, fontWeight: 800, margin: "12px 4px" }}>Hotline: {p.hotline}</div> : null}
        <div style={{ position: "relative", overflow: "hidden", background: PINK, borderRadius: 22, height: 64, display: "flex", alignItems: "center", justifyContent: "center", color: "white", fontSize: 30, fontWeight: 800 }}>
          MUA NGAY
          <div style={{ position: "absolute", top: 0, left: shine, width: 60, height: "100%", background: "rgba(255,255,255,0.45)", transform: "skewX(-20deg)" }} />
        </div>
      </div>
    </div>
  );
};

const BottomBar: React.FC = () => (
  <div style={{ position: "absolute", left: 30, top: 1770, width: 1020, height: 80, display: "flex", alignItems: "center", gap: 24 }}>
    <div style={{ width: 610, height: 80, borderRadius: 40, background: "rgba(255,255,255,0.24)", color: "#f0f0f0", fontSize: 30, display: "flex", alignItems: "center", paddingLeft: 40 }}>
      Nói gì đó...
    </div>
    {["♪", "+", "•••"].map((s) => (
      <div key={s} style={{ width: 76, height: 76, borderRadius: 38, background: "rgba(255,255,255,0.24)", color: "white", fontSize: 36, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>
        {s}
      </div>
    ))}
    <div style={{ width: 76, height: 76, borderRadius: 38, background: "rgba(255,255,255,0.24)", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <Heart size={44} color={PINK} />
    </div>
  </div>
);

export const LiveOverlay: React.FC<LiveOverlayProps> = (props) => {
  return (
    <AbsoluteFill style={{ fontFamily: FONT, backgroundColor: "transparent" }}>
      <AbsoluteFill style={{ background: "linear-gradient(to bottom, rgba(0,0,0,0.47) 0px, rgba(0,0,0,0) 260px)" }} />
      <AbsoluteFill style={{ background: "linear-gradient(to top, rgba(0,0,0,0.59) 0px, rgba(0,0,0,0) 700px)" }} />
      <TopBar {...props} />
      <FloatingHearts />
      <Comments {...props} />
      <CartCard {...props} />
      <BottomBar />
      <ProductFx fx={props.fx} />
      <Transitions cuts={props.clips.slice(1).map((c) => c.start)} />
    </AbsoluteFill>
  );
};
