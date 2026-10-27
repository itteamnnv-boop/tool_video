import React from 'react';
import {CalculateMetadataFunction, Composition} from 'remotion';
import {PostVideo} from './PostVideo';
import {DEFAULT_PROPS, PostProps} from './types';

// Độ dài / khung hình lấy từ props (app truyền --props=props.json) — mỗi video hậu kỳ một kích thước riêng
const calculateMetadata: CalculateMetadataFunction<PostProps> = ({props}) => ({
	durationInFrames: Math.max(1, Math.round(props.duration * props.fps)),
	fps: props.fps,
	width: props.width,
	height: props.height,
});

export const RemotionRoot: React.FC = () => (
	<Composition
		id="PostVideo"
		component={PostVideo}
		durationInFrames={150}
		fps={30}
		width={1080}
		height={1920}
		defaultProps={DEFAULT_PROPS}
		calculateMetadata={calculateMetadata}
	/>
);
