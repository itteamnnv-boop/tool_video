// Dữ liệu app (Python) truyền vào — xem app/pipeline/remotion_post.py. Thời gian tính bằng giây trên cả video.
export type Word = {t: string; s: number; e: number; k?: number};
export type Caption = {scene: number; start: number; end: number; words: Word[]};
export type Scene = {index: number; start: number; end: number; headline: string; narration: string};

export type CaptionStyle = 'karaoke' | 'pop' | 'box' | 'bounce';
export type HookStyle = 'slam' | 'slide' | 'typewriter';

// Kế hoạch dựng do model (Claude trình duyệt) chọn — chỉ là dữ liệu, app đã kiểm tra + giới hạn giá trị
export type Plan = {
	theme: {accent: string; text: string; stroke: string; panel: string};
	caption_style: CaptionStyle;
	caption_y: number; // tâm dòng phụ đề, tỉ lệ chiều cao (0.55–0.78)
	hook: {text: string; style: HookStyle; duration: number};
	titles: {at: number; duration: number; text: string}[];
	callouts: {at: number; duration: number; text: string}[];
	zooms: {at: number; duration: number; scale: number}[];
	end_card: {title: string; cta: string; seconds: number};
	progress: boolean;
};

export type PostProps = {
	video: string; // tệp trong public dir (--public-dir)
	width: number;
	height: number;
	fps: number;
	duration: number;
	fonts: {file: string; weight: number}[];
	captions: Caption[];
	scenes: Scene[];
	plan: Plan;
};

export const DEFAULT_PROPS: PostProps = {
	video: '',
	width: 1080,
	height: 1920,
	fps: 30,
	duration: 5,
	fonts: [],
	captions: [],
	scenes: [],
	plan: {
		theme: {accent: '#FFD400', text: '#FFFFFF', stroke: '#000000', panel: 'rgba(0,0,0,0.55)'},
		caption_style: 'karaoke',
		caption_y: 0.68,
		hook: {text: 'Hook mở đầu', style: 'slam', duration: 2.5},
		titles: [],
		callouts: [],
		zooms: [],
		end_card: {title: '', cta: '', seconds: 0},
		progress: true,
	},
};
