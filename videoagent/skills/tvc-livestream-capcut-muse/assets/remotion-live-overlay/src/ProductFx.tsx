import React from "react";
import { AbsoluteFill, interpolate, random, spring, useCurrentFrame, useVideoConfig } from "remotion";

// Một hiệu ứng trên timeline (t, end: giây tuyệt đối). x, y: toạ độ khung 1080x1920.
export type Fx = {
  type: "reveal" | "price" | "chips" | "callout" | "gift" | "pointer" | "react";
  t: number;
  end: number;
  x?: number;
  y?: number;
  text?: string; // price: dòng giá lớn, vd "650.000đ"
  pre?: string; // price: dòng nhỏ phía trên, vd "GIÁ CHỈ"
  sub?: string; // price: dải ưu đãi, vd "MUA 5 TẶNG 1"
  scale?: number; // price: thu nhỏ/phóng to huy hiệu (mặc định 1)
  items?: { icon: string; text?: string }[] | string[]; // chips: [{icon,text}], react: ["🔥","👍"]
  bx?: number; // callout: tâm bong bóng chữ
  by?: number;
  dur?: number; // callout/gift/react: thời gian hiện (giây)
};

const GOLD = ["#FFD84D", "#FFF6C2", "#FFFFFF", "#FFC21A", "#FFE98A"];
const CONFETTI = ["#FF3B5C", "#FFD23F", "#3BCEAC", "#4D9DE0", "#FF8A3D", "#FFFFFF"];
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

const Star4: React.FC<{ size: number; color: string }> = ({ size, color }) => (
  <svg width={size} height={size} viewBox="-10 -10 20 20">
    <path d="M0 -10 C1.2 -1.2 1.2 -1.2 10 0 C1.2 1.2 1.2 1.2 0 10 C-1.2 1.2 -1.2 1.2 -10 0 C-1.2 -1.2 -1.2 -1.2 0 -10 Z" fill={color} />
  </svg>
);

// ---------- Sản phẩm xuất hiện: chớp sáng + tia sáng + sóng + lấp lánh ----------
const Reveal: React.FC<{ fx: Fx; age: number; id: number }> = ({ fx, age, id }) => {
  const { fps } = useVideoConfig();
  const x = fx.x ?? 540;
  const y = fx.y ?? 900;
  const flash = interpolate(age, [0, 2, 10], [0, 0.5, 0], clamp);
  const rayScale = spring({ frame: age, fps, config: { damping: 12, stiffness: 120 } });
  const rayOpacity = interpolate(age, [0, 5, 35, 60], [0, 0.85, 0.55, 0], clamp);
  const ring = (delay: number, max: number, color: string, w: number) => {
    const a = age - delay;
    if (a < 0 || a > 26) return null;
    const r = interpolate(a, [0, 26], [30, max], { easing: (v) => 1 - Math.pow(1 - v, 3), ...clamp });
    return (
      <div
        style={{
          position: "absolute", left: x - r, top: y - r, width: r * 2, height: r * 2, borderRadius: "50%",
          border: `${w}px solid ${color}`, opacity: interpolate(a, [0, 4, 26], [0, 1, 0], clamp),
          boxShadow: `0 0 30px ${color}`,
        }}
      />
    );
  };
  // tia lấp lánh bung ra (có trọng lực)
  const sparks = [];
  for (let i = 0; i < 30; i++) {
    const life = 30 + random(`l${id}-${i}`) * 22;
    if (age > life) continue;
    const ang = random(`a${id}-${i}`) * Math.PI * 2;
    const sp = 10 + random(`v${id}-${i}`) * 16;
    const px = x + Math.cos(ang) * sp * age;
    const py = y + Math.sin(ang) * sp * age + 0.35 * age * age;
    const size = 18 + random(`s${id}-${i}`) * 30;
    sparks.push(
      <div
        key={`s${i}`}
        style={{
          position: "absolute", left: px - size / 2, top: py - size / 2,
          opacity: interpolate(age, [0, 3, life * 0.6, life], [0, 1, 1, 0], clamp),
          transform: `rotate(${age * 9 + i * 30}deg) scale(${interpolate(age, [0, life], [1.2, 0.4], clamp)})`,
          filter: "drop-shadow(0 0 8px rgba(255,220,90,0.9))",
        }}
      >
        <Star4 size={size} color={GOLD[i % GOLD.length]} />
      </div>,
    );
  }
  // lấp lánh quanh sản phẩm ~3s
  const glints = [];
  for (let i = 0; i < 16; i++) {
    const start = 8 + i * 5;
    const a = age - start;
    if (a < 0 || a > 24) continue;
    const ang = random(`ga${id}-${i}`) * Math.PI * 2;
    const rad = 90 + random(`gr${id}-${i}`) * 170;
    const size = 26 + random(`gs${id}-${i}`) * 34;
    glints.push(
      <div
        key={`g${i}`}
        style={{
          position: "absolute", left: x + Math.cos(ang) * rad - size / 2, top: y + Math.sin(ang) * rad - size / 2,
          opacity: Math.sin((a / 24) * Math.PI), transform: `rotate(${a * 4}deg) scale(${0.4 + Math.sin((a / 24) * Math.PI)})`,
          filter: "drop-shadow(0 0 10px rgba(255,255,255,0.95))",
        }}
      >
        <Star4 size={size} color="#FFFFFF" />
      </div>,
    );
  }
  return (
    <>
      <AbsoluteFill style={{ background: "white", opacity: flash }} />
      <div
        style={{
          position: "absolute", left: x - 520, top: y - 520, width: 1040, height: 1040, opacity: rayOpacity,
          transform: `scale(${rayScale}) rotate(${age * 1.2}deg)`,
          background: "repeating-conic-gradient(from 0deg, rgba(255,226,120,0.75) 0deg 5deg, rgba(255,226,120,0) 5deg 18deg)",
          WebkitMaskImage: "radial-gradient(circle, rgba(0,0,0,1) 8%, rgba(0,0,0,0) 62%)",
          maskImage: "radial-gradient(circle, rgba(0,0,0,1) 8%, rgba(0,0,0,0) 62%)",
        }}
      />
      <div
        style={{
          position: "absolute", left: x - 260, top: y - 260, width: 520, height: 520, borderRadius: "50%",
          background: "radial-gradient(circle, rgba(255,245,200,0.55) 0%, rgba(255,220,100,0) 70%)",
          opacity: interpolate(age, [0, 6, 50, 75], [0, 1, 0.6, 0], clamp),
        }}
      />
      {ring(0, 460, "#FFE16B", 12)}
      {ring(7, 380, "#FFFFFF", 7)}
      {sparks}
      {glints}
    </>
  );
};

// ---------- Huy hiệu giá + dải ưu đãi + pháo giấy ----------
const starPoints = (n: number, R: number, r: number) =>
  Array.from({ length: n * 2 }, (_, i) => {
    const ang = (Math.PI * i) / n - Math.PI / 2;
    const rad = i % 2 ? r : R;
    return `${(Math.cos(ang) * rad).toFixed(1)},${(Math.sin(ang) * rad).toFixed(1)}`;
  }).join(" ");

const Price: React.FC<{ fx: Fx; age: number; left: number; id: number }> = ({ fx, age, left, id }) => {
  const { fps } = useVideoConfig();
  const x = fx.x ?? 540;
  const y = fx.y ?? 470;
  const pop = spring({ frame: age, fps, config: { damping: 9, stiffness: 160 } });
  const out = interpolate(left, [0, 8], [0, 1], clamp);
  const pulse = 1 + 0.04 * Math.sin(age / 4.5);
  const ribbon = spring({ frame: age - 7, fps, config: { damping: 11, stiffness: 150 } });
  const shine = interpolate((age - 12) % 45, [0, 18], [-160, 760], clamp);
  const confetti = [];
  for (let i = 0; i < 70; i++) {
    const delay = random(`cd${id}-${i}`) * 25;
    const a = age - delay;
    if (a < 0 || a > 95) continue;
    const cx = random(`cx${id}-${i}`) * 1080;
    const fall = 9 + random(`cv${id}-${i}`) * 9;
    const w = 14 + random(`cw${id}-${i}`) * 14;
    confetti.push(
      <div
        key={`c${i}`}
        style={{
          position: "absolute", left: cx + Math.sin(a / 7 + i) * 40, top: -40 + a * fall, width: w, height: w * 0.55,
          background: CONFETTI[i % CONFETTI.length], borderRadius: 3,
          transform: `rotate(${a * (8 + (i % 7))}deg) rotateX(${a * 12}deg)`,
          opacity: interpolate(a, [0, 4, 80, 95], [0, 1, 1, 0], clamp),
        }}
      />,
    );
  }
  return (
    <>
      {confetti}
      <div style={{ position: "absolute", left: x, top: y, transform: `translate(-50%,-50%) scale(${pop * out * pulse * (fx.scale ?? 1)})` }}>
        <div style={{ position: "relative", width: 520, height: 520, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <svg width="520" height="520" viewBox="-260 -260 520 520" style={{ position: "absolute", transform: `rotate(${age * 0.5}deg)`, filter: "drop-shadow(0 12px 22px rgba(0,0,0,0.45))" }}>
            <defs>
              <radialGradient id={`pg${id}`}>
                <stop offset="0%" stopColor="#FF5A36" />
                <stop offset="100%" stopColor="#D80F2A" />
              </radialGradient>
            </defs>
            <polygon points={starPoints(18, 235, 195)} fill={`url(#pg${id})`} stroke="#FFE14D" strokeWidth="8" />
          </svg>
          <div style={{ position: "relative", textAlign: "center", fontFamily: "'Segoe UI', Arial, sans-serif", marginTop: -40 }}>
            {fx.pre ? <div style={{ color: "white", fontSize: 44, fontWeight: 800, letterSpacing: 2 }}>{fx.pre}</div> : null}
            <div style={{ color: "#FFF27A", fontSize: 96, fontWeight: 900, lineHeight: 1.05, textShadow: "0 4px 0 #8A0010, 0 0 18px rgba(255,230,80,0.8)" }}>
              {fx.text}
            </div>
          </div>
        </div>
        {fx.sub ? (
          <div
            style={{
              position: "absolute", left: "50%", top: 395, transform: `translateX(-50%) scale(${ribbon})`,
              background: "linear-gradient(180deg,#FFE14D,#FFB800)", color: "#B0001A", fontSize: 58, fontWeight: 900,
              padding: "14px 44px", borderRadius: 18, whiteSpace: "nowrap", overflow: "hidden",
              boxShadow: "0 10px 24px rgba(0,0,0,0.45)", border: "5px solid white",
            }}
          >
            {fx.sub}
            <div style={{ position: "absolute", top: 0, left: shine, width: 90, height: "100%", background: "rgba(255,255,255,0.65)", transform: "skewX(-20deg)" }} />
          </div>
        ) : null}
      </div>
    </>
  );
};


const EMOJI = "'Segoe UI Emoji','Apple Color Emoji','Noto Color Emoji',sans-serif";

// ---------- Thẻ thông tin trượt vào lần lượt (icon + chữ) ----------
const Chips: React.FC<{ fx: Fx; age: number; left: number }> = ({ fx, age, left }) => {
  const { fps } = useVideoConfig();
  const x = fx.x ?? 1050;
  const y = fx.y ?? 330;
  const out = interpolate(left, [0, 8], [0, 1], clamp);
  const items = (fx.items ?? []) as { icon: string; text?: string }[];
  return (
    <>
      {items.map((it, i) => {
        const a = age - i * Math.round(0.45 * fps);
        if (a < 0) return null;
        const s = spring({ frame: a, fps, config: { damping: 12, stiffness: 170 } });
        const glow = interpolate(a, [0, 6, 22], [0, 1, 0], clamp);
        const bob = Math.sin((a + i * 9) / 9) * 4;
        return (
          <div
            key={i}
            style={{
              position: "absolute", right: 1080 - x, top: y + i * 100 + bob, opacity: out,
              transform: `translateX(${(1 - s) * 460}px) scale(${0.85 + 0.15 * s})`, transformOrigin: "100% 50%",
              display: "flex", alignItems: "center", gap: 14, whiteSpace: "nowrap",
              background: "linear-gradient(90deg, rgba(14,96,36,0.93), rgba(34,150,66,0.93))",
              border: "4px solid #FFE14D", borderRadius: 46, padding: "8px 30px 8px 10px",
              boxShadow: `0 6px 18px rgba(0,0,0,0.45), 0 0 ${28 * glow}px rgba(255,225,77,${glow})`,
              color: "white", fontSize: 40, fontWeight: 800,
            }}
          >
            <span style={{ fontFamily: EMOJI, fontSize: 40, width: 64, height: 64, borderRadius: 32, background: "white", display: "flex", alignItems: "center", justifyContent: "center" }}>
              {it.icon}
            </span>
            {it.text}
          </div>
        );
      })}
    </>
  );
};

// ---------- Chú thích: bong bóng chữ + đường nét đứt chỉ vào sản phẩm ----------
const Callout: React.FC<{ fx: Fx; age: number }> = ({ fx, age }) => {
  const { fps } = useVideoConfig();
  const dur = Math.round((fx.dur ?? 3.2) * fps);
  if (age > dur) return null;
  const x = fx.x ?? 540;
  const y = fx.y ?? 900;
  const bx = fx.bx ?? x - 260;
  const by = fx.by ?? y - 260;
  const pop = spring({ frame: age, fps, config: { damping: 10, stiffness: 170 } });
  const out = interpolate(age, [dur - 8, dur], [1, 0], clamp);
  const draw = interpolate(age, [3, 14], [0, 1], clamp);
  const ex = bx + (x - bx) * draw;
  const ey = by + (y - by) * draw;
  return (
    <>
      <svg width={1080} height={1920} style={{ position: "absolute", left: 0, top: 0, opacity: out }}>
        <line x1={bx} y1={by} x2={ex} y2={ey} stroke="#FFE14D" strokeWidth={7} strokeDasharray="16 10" strokeLinecap="round" />
        <circle cx={x} cy={y} r={(20 + 8 * Math.sin(age / 4)) * draw} fill="none" stroke="#FFE14D" strokeWidth={7} />
        <circle cx={x} cy={y} r={9 * draw} fill="#FFE14D" />
      </svg>
      <div
        style={{
          position: "absolute", left: bx, top: by,
          transform: `translate(-50%,-50%) scale(${pop * out}) rotate(${-3 + Math.sin(age / 10) * 1.5}deg)`,
          background: "white", color: "#151515", borderRadius: 28, padding: "14px 30px", border: "6px solid #FFE14D",
          fontSize: 48, fontWeight: 900, whiteSpace: "nowrap", boxShadow: "0 10px 22px rgba(0,0,0,0.45)",
        }}
      >
        {fx.text}
      </div>
    </>
  );
};

// ---------- Hộp quà bật ra + chữ "+1 XÔ" + tim/sao bung ----------
const Gift: React.FC<{ fx: Fx; age: number; id: number }> = ({ fx, age, id }) => {
  const { fps } = useVideoConfig();
  const dur = Math.round((fx.dur ?? 2.8) * fps);
  if (age > dur) return null;
  const x = fx.x ?? 900;
  const y = fx.y ?? 1050;
  const pop = spring({ frame: age, fps, config: { damping: 7, stiffness: 180 } });
  const out = interpolate(age, [dur - 10, dur], [1, 0], clamp);
  const wob = Math.sin(age / 3) * interpolate(age, [0, 30], [14, 3], clamp);
  const parts = [];
  for (let i = 0; i < 16; i++) {
    const a = age - 4;
    if (a < 0 || a > 40) continue;
    const ang = (i / 16) * Math.PI * 2 + random(`ga${id}-${i}`) * 0.4;
    const sp = 9 + random(`gv${id}-${i}`) * 8;
    parts.push(
      <div key={i} style={{ position: "absolute", left: x + Math.cos(ang) * sp * a - 20, top: y + Math.sin(ang) * sp * a + 0.25 * a * a - 20, opacity: interpolate(a, [0, 30, 40], [1, 1, 0], clamp), fontFamily: EMOJI, fontSize: 40 }}>
        {i % 2 ? "💖" : "✨"}
      </div>,
    );
  }
  return (
    <>
      {parts}
      <div style={{ position: "absolute", left: x, top: y, transform: `translate(-50%,-50%) scale(${pop * out})`, textAlign: "center" }}>
        <div style={{ fontFamily: EMOJI, fontSize: 170, lineHeight: 1, transform: `rotate(${wob}deg)`, filter: "drop-shadow(0 10px 16px rgba(0,0,0,0.45))" }}>🎁</div>
        {fx.text ? (
          <div style={{ marginTop: -10, color: "#FFF27A", fontSize: 76, fontWeight: 900, whiteSpace: "nowrap", textShadow: "0 0 3px #B0001A, 0 4px 0 #B0001A, 0 0 22px rgba(255,90,60,0.9)" }}>{fx.text}</div>
        ) : null}
      </div>
    </>
  );
};

// ---------- Bàn tay nhấp nhô chỉ xuống giỏ hàng ----------
const Pointer: React.FC<{ fx: Fx; age: number; left: number }> = ({ fx, age, left }) => {
  const { fps } = useVideoConfig();
  const x = fx.x ?? 880;
  const y = fx.y ?? 1240;
  const pop = spring({ frame: age, fps, config: { damping: 10, stiffness: 160 } });
  const out = interpolate(left, [0, 8], [0, 1], clamp);
  const bounce = Math.abs(Math.sin(age / 6)) * 26;
  const ring = (age % 24) / 24;
  return (
    <>
      <div style={{ position: "absolute", left: x - 20 - 70 * ring, top: y + 100 - 40 * ring, width: 40 + 140 * ring, height: 40 + 80 * ring, borderRadius: "50%", border: "6px solid #FFE14D", opacity: (1 - ring) * out }} />
      <div style={{ position: "absolute", left: x, top: y + bounce, transform: `translate(-50%,-50%) scale(${pop * out})`, fontFamily: EMOJI, fontSize: 120, filter: "drop-shadow(0 8px 12px rgba(0,0,0,0.5))" }}>👇</div>
    </>
  );
};

// ---------- Emoji cảm xúc bay lên ----------
const Reactions: React.FC<{ fx: Fx; age: number; id: number }> = ({ fx, age, id }) => {
  const { fps } = useVideoConfig();
  const dur = Math.round((fx.dur ?? 2.6) * fps);
  if (age > dur + 45) return null;
  const x = fx.x ?? 900;
  const y = fx.y ?? 1350;
  const given = (fx.items ?? []) as string[];
  const list = given.length ? given : ["🔥", "👍", "😍", "💯", "❤️"];
  const out = [];
  for (let i = 0; i < 22; i++) {
    const a = age - Math.round((i / 22) * dur);
    if (a < 0 || a > 45) continue;
    const t = a / 45;
    const size = 54 + random(`rs${id}-${i}`) * 40;
    out.push(
      <div key={i} style={{ position: "absolute", left: x + (random(`rx${id}-${i}`) - 0.5) * 220 + Math.sin(t * 6 + i) * 30 - size / 2, top: y - t * 620, fontFamily: EMOJI, fontSize: size, opacity: interpolate(t, [0, 0.1, 0.75, 1], [0, 1, 1, 0], clamp), transform: `scale(${interpolate(t, [0, 0.15], [0.3, 1], clamp)})` }}>
        {list[i % list.length]}
      </div>,
    );
  }
  return <>{out}</>;
};

// ---------- Ánh sáng mở màn + vệt sáng mỗi lần chuyển clip ----------
export const Transitions: React.FC<{ cuts: number[] }> = ({ cuts }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const intro = interpolate(frame, [0, 4, 26], [0, 0.75, 0], clamp);
  return (
    <>
      <AbsoluteFill style={{ opacity: intro, background: "radial-gradient(circle at 15% 10%, rgba(255,190,90,0.95), rgba(255,120,60,0.45) 35%, rgba(255,120,60,0) 70%)" }} />
      {cuts.map((c, i) => {
        const a = frame - Math.round(c * fps);
        if (a < -2 || a > 12) return null;
        const pos = interpolate(a, [-2, 12], [-700, 1500], clamp);
        return (
          <React.Fragment key={i}>
            <AbsoluteFill style={{ background: "white", opacity: interpolate(a, [-2, 0, 6], [0, 0.45, 0], clamp) }} />
            <div style={{ position: "absolute", top: -400, left: pos, width: 260, height: 2800, transform: "rotate(18deg)", background: "linear-gradient(90deg, rgba(255,255,255,0), rgba(255,250,220,0.85), rgba(255,255,255,0))" }} />
          </React.Fragment>
        );
      })}
    </>
  );
};

export const ProductFx: React.FC<{ fx?: Fx[] }> = ({ fx }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <>
      {(fx ?? []).map((f, i) => {
        const age = frame - Math.round(f.t * fps);
        if (age < 0) return null;
        if (f.type === "reveal") return age <= 100 ? <Reveal key={i} fx={f} age={age} id={i} /> : null;
        if (f.type === "callout") return <Callout key={i} fx={f} age={age} />;
        if (f.type === "gift") return <Gift key={i} fx={f} age={age} id={i} />;
        if (f.type === "react") return <Reactions key={i} fx={f} age={age} id={i} />;
        const left = Math.round(f.end * fps) - frame;
        if (left < 0) return null;
        if (f.type === "chips") return <Chips key={i} fx={f} age={age} left={left} />;
        if (f.type === "pointer") return <Pointer key={i} fx={f} age={age} left={left} />;
        return <Price key={i} fx={f} age={age} left={left} id={i} />;
      })}
    </>
  );
};
