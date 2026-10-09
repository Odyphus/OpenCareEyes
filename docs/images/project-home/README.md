# 项目首页素材

- `cover.png`：README 横幅，原版蓝色眼睛图标与 v0.9 白鼬预览，统一缩放排版，不修改角色。
- `social-preview.png`：1280×640 的项目分享封面备用文件。
- `home-light.png`、`home-dark.png`：b11 真实 Qt 控件的 980×720 离屏渲染。倒计时与显示状态来自 `DemoController` 演示数据，宠物预览来自实际资源。
- `rest-gaze.png`：b11 真实休息窗口的 1280×720 离屏渲染，使用恢复后的 v0.9 睡眠帧；倒计时为演示数据。
- `interactions.gif`：b11 实际摸摸头、玩一会儿帧的带标题预览；按声明时序播放，段落末尾额外停留 600ms。GIF 为固定调色板展示稿，不是桌面录屏，也不替代运行时播放检查。

在 Windows 开发环境执行：

```powershell
python -m scripts.build_project_home
python -m scripts.capture_ui --theme light --output docs/images/project-home/home-light.png
python -m scripts.capture_ui --theme dark --output docs/images/project-home/home-dark.png
python -m scripts.capture_ui --theme dark --rest-scene gaze --output docs/images/project-home/rest-gaze.png
```

新素材只使用本项目既有图标与角色。沿用 [Apache-2.0](../../../LICENSE) 及素材来源记录，不使用 Codex 的宠物图像。
