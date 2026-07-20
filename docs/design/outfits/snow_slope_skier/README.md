# 雪坡滑雪客 · 样板审校

此目录是 v0.8.0 的首个美术里程碑，不会进入当前运行时资源包。

- `action_contact_sheet_rgba.png`：AI 基于用户原图辅助重绘，并由官方 chroma-key 工具生成透明 RGBA 联系表。
- `action_map.json`：12 个样板姿势与 10 个业务动作的对应关系。
- `preview.html`：在亮、暗背景上检查身份、服装、透明边缘及动作节奏。

样板确认后再按冻结规范制作每个动作的正式多帧资源。正式资源仍需满足：

- 384×384 RGBA；
- 6–8 FPS 的柔和节奏；
- 每套最多两张 2048×2048 atlas；
- `idle` 3 帧、`sleep` 2 帧、`move` 4 帧、`click_reaction` 3 帧、
  `drag_hold` 1 帧、`drag_release` 3 帧、`right_click_reaction` 3 帧、
  `rest_prompt` 3 帧、`play` 4 帧、`look_cursor` 左中右各 1 帧；
- 白鼬毛发、薄荷绿外套、浅蓝护目镜、背包与雪板保持一致；
- 浅色和暗色桌面均不得出现绿边、白边或色污。

当前联系表仅用于确认角色比例、动作方向和服装细节，不能作为正式 atlas 发布。

用户提供的原始造型设计与本目录中的衍生样板均按项目 Apache-2.0 许可发布。
