# v0.10 伙伴原画与动作来源

2026-10-08 使用 Codex 内置图像生成工具，根据仓库原版白鼬预览图制作分层原画。`rig-parts.png` 为选定原稿，透明 PNG，1536×1024。

设计要求：保留白鼬身份、比例和柔和插画感；四列三行，分别绘制睁眼、半闭眼、闭眼、侧脸、身体、尾巴、两只前爪、两只脚、睡眠和阅读姿态；真实透明背景，无棋盘、文字或网格。第二轮强调修复透明度和分离部件。

动作由 `scripts/build_companion_motion.py` 中的统一枢轴、注册位置和运动曲线制作，未逐帧生成独立角色。蓝围巾和球为项目内程序绘制元素。源图只用于构建，不进入运行时资源包。使用本项目既有 Apache-2.0 许可声明；此记录仅记录素材来源，不代表著作权登记或独占权审查结论。

重新生成：`python scripts/build_companion_motion.py`，随后 `python scripts/sync_official_outfits.py --check`。图标另见 `scripts/build_brand_icons.py` 与 `assets/icons/*.svg`，为本次项目内矢量设计。未使用 Codex 或其他桌宠项目的图像资产。

旧版 16 张单帧图与蓝围巾 2 张旧图集已按 SHA-256 校验后移至 `legacy-v0.9/`，保留源码历史与再制作用途，不再进入运行时包。清单见 `legacy-v0.9/inventory.json`。
