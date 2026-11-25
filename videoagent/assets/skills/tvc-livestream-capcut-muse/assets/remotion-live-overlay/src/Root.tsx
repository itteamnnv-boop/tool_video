import React from "react";
import { CalculateMetadataFunction, Composition } from "remotion";
import { LiveOverlay, LiveOverlayProps } from "./LiveOverlay";

const FPS = 30;

const calculateMetadata: CalculateMetadataFunction<LiveOverlayProps> = async ({ props }) => ({
  // làm tròn LÊN để video overlay không ngắn hơn timeline CapCut
  durationInFrames: Math.max(1, Math.ceil(props.durationSec * FPS)),
  // mặc định xuất video trong suốt (ProRes 4444 có alpha) để đặt lên timeline CapCut
  defaultCodec: "prores",
  defaultProResProfile: "4444",
  defaultVideoImageFormat: "png",
  defaultPixelFormat: "yuva444p10le",
});

const defaultProps: LiveOverlayProps = {
  durationSec: 12,
  shopName: "Shop Demo",
  likes: "12,5K",
  viewers: 2947,
  productTitle: "SẢN PHẨM",
  productLine2: "Dòng 2",
  productLine3: "Dòng 3",
  hotline: "0900.000.000",
  avatar: "demo/avatar.png",
  product: "demo/product.png",
  clips: [
    { start: 0, end: 6, comments: [["Út Mười", "Chào em gái nha!"], ["Chị Hai", "Có ship không em?"]] },
    { start: 6, end: 12, comments: [["Bảy Lúa", "Giá bao nhiêu vậy?"], ["Hoàng Nam", "Đã đặt 2 thùng"]] },
  ],
  joiners: ["Anh Tư", "Cô Ba", "Chú Năm"],
};

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="LiveOverlay"
      component={LiveOverlay}
      fps={FPS}
      width={1080}
      height={1920}
      durationInFrames={360}
      defaultProps={defaultProps}
      calculateMetadata={calculateMetadata}
    />
  );
};
