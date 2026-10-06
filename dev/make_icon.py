# -*- coding: utf-8 -*-
"""生成 icon.ico（黑胶唱片样式）。运行一次即可：py -3 make_icon.py"""
import os

from PIL import Image, ImageDraw, ImageFont

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

cx = cy = S // 2
R = S // 2 - 8

# 盘体
d.ellipse([cx - R, cy - R, cx + R, cy + R], fill=(24, 24, 28, 255),
          outline=(0, 0, 0, 140), width=4)
# 沟槽
for i in range(1, 7):
    rr = int(R * (0.16 + 0.118 * i))
    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
              outline=(255, 255, 255, 42), width=2)
# 绿色标签
lr = int(R * 0.38)
d.ellipse([cx - lr, cy - lr, cx + lr, cy + lr], fill=(30, 215, 96, 255))
# 字
try:
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 96, index=0)
except Exception:
    font = ImageFont.load_default()
bbox = d.textbbox((0, 0), "词", font=font)
tw = bbox[2] - bbox[0]
th = bbox[3] - bbox[1]
d.text((cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1]), "词", font=font,
       fill=(12, 12, 14, 255))
# 中心孔
d.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], fill=(10, 10, 12, 255))

out = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "icon.ico")          # 写到项目根目录（本脚本在 dev/ 下）
img.save(out, sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
print("saved:", out)
