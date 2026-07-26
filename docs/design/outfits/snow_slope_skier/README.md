# 雪坡滑雪客 · 样板审校

此目录记录 v0.8.0 的首个完整造型“雪坡滑雪客”的来源帧与审校过程。

- `sheet_*_chroma*.png`：基于用户原图辅助重绘的纯色色键动作表。
- `sheet_*_rgba*.png`：审校过程中的透明来源帧；运行时不直接读取此目录。
- `scripts/refine_magenta_matte.py`：纯本地 NumPy + Pillow 精细 Alpha 工具，不联网、不需要图像 API。
- `scripts/build_snow_slope_skier.py`：按透明安全分隔带生成两张运行时 atlas。

正式运行时资源位于
`assets/pets/snow_ferret/outfits/snow_slope_skier/`，包含：

- 384×384 RGBA；
- 6–8 FPS 的柔和节奏；
- 每套最多两张 2048×2048 atlas；
- `idle` 3 帧、`sleep` 2 帧、`move` 4 帧、`click_reaction` 3 帧、
  `drag_hold` 1 帧、`drag_release` 3 帧、`right_click_reaction` 3 帧、
  `rest_prompt` 3 帧、`play` 4 帧、`look_cursor` 左中右各 1 帧；
- 白鼬毛发、薄荷绿外套、浅蓝护目镜、背包与雪板保持一致；
- 浅色和暗色桌面均不得出现绿边、白边或色污。

用户提供的原始造型设计与本目录中的衍生样板均按项目 Apache-2.0 许可发布。

## 透明边缘审校状态

- 29 帧、10 个动作已完成并接入宠物包 schema v3。
- 点击与拖拽组采用拓扑 trimap、局部颜色线 Alpha 重建和定向去紫；可见洋红残留为 0，外边框 Alpha 为 0。
- 白毛、黑线和红色音符核心保留率均通过自动门禁，并在浅色与深色背景完成审校。
- 所有动作表使用显式透明分隔带，避免机械等分切到尾巴、雪板或雪花。
- `draft_atlas/` 只保留失败前的构建预览，不进入安装包。
