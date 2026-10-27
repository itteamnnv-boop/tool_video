import React from 'react';
import {loadFont} from '@remotion/fonts';
import {
	AbsoluteFill,
	continueRender,
	delayRender,
	Easing,
	interpolate,
	OffthreadVideo,
	spring,
	staticFile,
	useCurrentFrame,
	useVideoConfig,
} from 'remotion';
import {Caption, Plan, PostProps} from './types';

// Font tiếng Việt app nhúng sẵn (Segoe UI của Windows, đủ dấu) — máy khác rơi về font hệ thống có dấu
const FAMILY = 'VA Viet';
const STACK = `'${FAMILY}', 'Segoe UI', system-ui, -apple-system, 'Helvetica Neue', Arial, sans-serif`;

const useFonts = (fonts: PostProps['fonts']) => {
	const [handle] = React.useState(() => delayRender('Đang nạp font tiếng Việt'));
	React.useEffect(() => {
		Promise.all(fonts.map((f) => loadFont({family: FAMILY, url: staticFile(f.file), weight: String(f.weight)})))
			.catch(() => undefined)
			.finally(() => continueRender(handle));
	}, [fonts, handle]);
};

// chữ đọc rõ trên mọi nền: viền + bóng đổ (paint-order để viền nằm dưới chữ)
const outlined = (theme: Plan['theme'], size: number): React.CSSProperties => ({
	color: theme.text,
	WebkitTextStroke: `${Math.max(2, size * 0.09)}px ${theme.stroke}`,
	paintOrder: 'stroke fill',
	textShadow: `0 ${size * 0.06}px ${size * 0.18}px rgba(0,0,0,0.55)`,
});

const fade = (t: number, start: number, end: number, edge = 0.18) =>
	interpolate(t, [start, start + edge, end - edge, end], [0, 1, 1, 0], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

// -------------------------------------------------------------------- zoom nhấn (punch-in) trên video nền
const zoomAt = (t: number, zooms: Plan['zooms']) => {
	let scale = 1;
	for (const z of zooms) {
		if (t < z.at || t > z.at + z.duration) continue;
		const ramp = Math.min(0.25, z.duration / 3);
		const k = interpolate(t, [z.at, z.at + ramp, z.at + z.duration - ramp, z.at + z.duration], [0, 1, 1, 0], {
			easing: Easing.inOut(Easing.quad),
			extrapolateLeft: 'clamp',
			extrapolateRight: 'clamp',
		});
		scale = Math.max(scale, 1 + (z.scale - 1) * k);
	}
	return scale;
};

// -------------------------------------------------------------------- phụ đề theo từng từ
const Captions: React.FC<{captions: Caption[]; plan: Plan; u: number}> = ({captions, plan, u}) => {
	const frame = useCurrentFrame();
	const {fps, height} = useVideoConfig();
	const t = frame / fps;
	const line = captions.find((c) => t >= c.start && t < c.end);
	if (!line) return null;
	const size = 74 * u;
	const enter = spring({frame: frame - Math.round(line.start * fps), fps, config: {damping: 14, stiffness: 180}});
	const style = plan.caption_style;
	const box = style === 'box';
	return (
		<div
			style={{
				position: 'absolute',
				left: 70 * u,
				right: 140 * u,
				top: plan.caption_y * height,
				transform: `translateY(-50%) scale(${style === 'pop' ? interpolate(enter, [0, 1], [0.7, 1]) : 1})`,
				display: 'flex',
				flexWrap: 'wrap',
				justifyContent: 'center',
				gap: `${size * 0.12}px ${size * 0.26}px`,
				fontFamily: STACK,
				fontWeight: 900,
				fontSize: size,
				lineHeight: 1.35,
				textAlign: 'center',
				opacity: interpolate(enter, [0, 0.4], [0, 1], {extrapolateRight: 'clamp'}),
			}}
		>
			{line.words.map((w, i) => {
				const spoken = t >= w.s;
				const key = Boolean(w.k);
				const pop = spring({frame: frame - Math.round(w.s * fps), fps, config: {damping: 11, stiffness: 220}});
				const color = key ? plan.theme.accent : spoken || style !== 'karaoke' ? plan.theme.text : 'rgba(255,255,255,0.55)';
				const scale =
					style === 'bounce'
						? interpolate(pop, [0, 1], [0.4, key ? 1.15 : 1])
						: key && spoken
							? interpolate(pop, [0, 1], [1, 1.12])
							: 1;
				return (
					<span
						key={i}
						style={{
							...outlined(plan.theme, size),
							color,
							display: 'inline-block',
							paddingTop: '0.12em',
							transform: `scale(${scale})`,
							opacity: style === 'bounce' ? (spoken ? 1 : 0) : 1,
							...(box
								? {
										background: key && spoken ? plan.theme.accent : plan.theme.panel,
										color: key && spoken ? plan.theme.stroke : plan.theme.text,
										WebkitTextStroke: '0px transparent',
										textShadow: 'none',
										padding: `${size * 0.12}px ${size * 0.22}px 0`,
										borderRadius: size * 0.18,
									}
								: {}),
						}}
					>
						{w.t}
					</span>
				);
			})}
		</div>
	);
};

// -------------------------------------------------------------------- hook 3 giây đầu
const Hook: React.FC<{plan: Plan; u: number}> = ({plan, u}) => {
	const frame = useCurrentFrame();
	const {fps, height} = useVideoConfig();
	const {text, style, duration} = plan.hook;
	const t = frame / fps;
	if (!text || t > duration) return null;
	const size = 88 * u;
	const enter = spring({frame, fps, config: {damping: 12, stiffness: 160}});
	const shown =
		style === 'typewriter' ? Array.from(text).slice(0, Math.ceil((t / Math.max(0.6, duration * 0.5)) * text.length)).join('') : text;
	const transform =
		style === 'slam'
			? `scale(${interpolate(enter, [0, 1], [1.7, 1])})`
			: style === 'slide'
				? `translateX(${interpolate(enter, [0, 1], [-110, 0])}%)`
				: 'none';
	return (
		<div
			style={{
				position: 'absolute',
				left: 60 * u,
				right: 140 * u,
				top: height * 0.13,
				display: 'flex',
				justifyContent: 'center',
				opacity: fade(t, 0, duration, 0.2),
				transform,
			}}
		>
			<div
				style={{
					background: plan.theme.accent,
					color: plan.theme.stroke,
					fontFamily: STACK,
					fontWeight: 900,
					fontSize: size,
					lineHeight: 1.3,
					padding: `${size * 0.32}px ${size * 0.4}px ${size * 0.2}px`,
					borderRadius: size * 0.22,
					textAlign: 'center',
					boxShadow: `0 ${size * 0.12}px ${size * 0.4}px rgba(0,0,0,0.45)`,
					rotate: style === 'slam' ? '-2deg' : '0deg',
				}}
			>
				{shown}
			</div>
		</div>
	);
};

// -------------------------------------------------------------------- tiêu đề cảnh + nhấn (badge)
const Titles: React.FC<{plan: Plan; u: number}> = ({plan, u}) => {
	const frame = useCurrentFrame();
	const {fps, height} = useVideoConfig();
	const t = frame / fps;
	const size = 52 * u;
	return (
		<>
			{plan.titles
				.filter((x) => t >= x.at && t <= x.at + x.duration)
				.map((x, i) => {
					const enter = spring({frame: frame - Math.round(x.at * fps), fps, config: {damping: 16}});
					return (
						<div
							key={`t${i}`}
							style={{
								position: 'absolute',
								left: 0,
								top: height * 0.24,
								opacity: fade(t, x.at, x.at + x.duration),
								transform: `translateX(${interpolate(enter, [0, 1], [-100, 0])}%)`,
								background: plan.theme.panel,
								borderLeft: `${12 * u}px solid ${plan.theme.accent}`,
								color: plan.theme.text,
								fontFamily: STACK,
								fontWeight: 700,
								fontSize: size,
								lineHeight: 1.35,
								padding: `${size * 0.35}px ${size * 0.6}px ${size * 0.2}px ${size * 0.45}px`,
								maxWidth: '78%',
							}}
						>
							{x.text}
						</div>
					);
				})}
			{plan.callouts
				.filter((x) => t >= x.at && t <= x.at + x.duration)
				.map((x, i) => {
					const pop = spring({frame: frame - Math.round(x.at * fps), fps, config: {damping: 9, stiffness: 200}});
					const big = 96 * u;
					return (
						<div
							key={`c${i}`}
							style={{
								position: 'absolute',
								left: 60 * u,
								right: 140 * u,
								top: height * 0.38,
								display: 'flex',
								justifyContent: 'center',
								opacity: fade(t, x.at, x.at + x.duration, 0.12),
								transform: `scale(${interpolate(pop, [0, 1], [0.3, 1])}) rotate(${interpolate(pop, [0, 1], [-8, -3])}deg)`,
							}}
						>
							<div
								style={{
									...outlined(plan.theme, big),
									color: plan.theme.accent,
									fontFamily: STACK,
									fontWeight: 900,
									fontSize: big,
									lineHeight: 1.3,
									paddingTop: '0.15em',
									textAlign: 'center',
								}}
							>
								{x.text}
							</div>
						</div>
					);
				})}
		</>
	);
};

// -------------------------------------------------------------------- thẻ kết (lời kêu gọi)
const EndCard: React.FC<{plan: Plan; u: number}> = ({plan, u}) => {
	const frame = useCurrentFrame();
	const {fps, durationInFrames, height} = useVideoConfig();
	const {title, cta, seconds} = plan.end_card;
	const start = durationInFrames - Math.round(seconds * fps);
	if (!seconds || (!title && !cta) || frame < start) return null;
	const enter = spring({frame: frame - start, fps, config: {damping: 15}});
	const size = 78 * u;
	return (
		<AbsoluteFill
			style={{
				background: `rgba(0,0,0,${interpolate(enter, [0, 1], [0, 0.55])})`,
				alignItems: 'center',
				justifyContent: 'center',
				paddingBottom: height * 0.12,
			}}
		>
			<div
				style={{
					display: 'flex',
					flexDirection: 'column',
					alignItems: 'center',
					gap: size * 0.45,
					padding: `0 ${140 * u}px 0 ${60 * u}px`,
					transform: `translateY(${interpolate(enter, [0, 1], [60 * u, 0])}px)`,
					opacity: enter,
				}}
			>
				{title ? (
					<div
						style={{
							...outlined(plan.theme, size),
							fontFamily: STACK,
							fontWeight: 900,
							fontSize: size,
							lineHeight: 1.35,
							textAlign: 'center',
						}}
					>
						{title}
					</div>
				) : null}
				{cta ? (
					<div
						style={{
							background: plan.theme.accent,
							color: plan.theme.stroke,
							fontFamily: STACK,
							fontWeight: 900,
							fontSize: size * 0.72,
							lineHeight: 1.3,
							padding: `${size * 0.3}px ${size * 0.7}px ${size * 0.18}px`,
							borderRadius: size,
							transform: `scale(${1 + 0.04 * Math.sin(((frame - start) / fps) * Math.PI * 2)})`,
						}}
					>
						{cta}
					</div>
				) : null}
			</div>
		</AbsoluteFill>
	);
};

const Progress: React.FC<{plan: Plan; u: number}> = ({plan, u}) => {
	const frame = useCurrentFrame();
	const {durationInFrames} = useVideoConfig();
	return (
		<div
			style={{
				position: 'absolute',
				left: 0,
				top: 0,
				height: 8 * u,
				width: `${(frame / Math.max(1, durationInFrames - 1)) * 100}%`,
				background: plan.theme.accent,
			}}
		/>
	);
};

export const PostVideo: React.FC<PostProps> = ({video, fonts, captions, plan}) => {
	useFonts(fonts);
	const frame = useCurrentFrame();
	const {fps, width} = useVideoConfig();
	const u = width / 1080; // thiết kế theo khung 1080 rộng, tự co theo video thật
	const scale = zoomAt(frame / fps, plan.zooms);
	return (
		<AbsoluteFill style={{backgroundColor: '#000'}}>
			<AbsoluteFill style={{transform: `scale(${scale})`}}>
				{video ? <OffthreadVideo src={staticFile(video)} style={{width: '100%', height: '100%', objectFit: 'cover'}} /> : null}
			</AbsoluteFill>
			<Titles plan={plan} u={u} />
			<Captions captions={captions} plan={plan} u={u} />
			<Hook plan={plan} u={u} />
			<EndCard plan={plan} u={u} />
			{plan.progress ? <Progress plan={plan} u={u} /> : null}
		</AbsoluteFill>
	);
};
