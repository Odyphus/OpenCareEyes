# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)；版本号遵循语义化版本。

## [Unreleased]

## [0.4.0] - 2026-07-13

### Added

- `RuntimeIntent`、`ReconcileResult`、`DisplayHealthState`、`BreakCadenceState`、`BreakPromptState`、`UserNotice` 和 `UpdateState`，用于区分用户偏好、实际效果、提示阶段与异步结果。
- HDR/Advanced Color 能力探测：HDR 开启时抑制 Gamma Ramp、保留用户偏好，并在总览和屏幕舒适度页显示原因及 Windows 夜间模式引导。
- 活动加权的 20-20-20、番茄钟、平衡节奏和自定义短/长休息；空闲达到 5 分钟可作为自然休息重置周期。
- 温和渐进提醒：先显示不抢焦点的桌宠互动卡，支持立即休息、延后 5/10/30 分钟和本次跳过；未处理 60 秒后升级为更醒目的非阻塞提示。
- 托盘一级“显示倒计时桌宠”开关，以及桌宠预览、位置保存、重置和超出可见区域自动回收。
- 自动化日间/夜间方案与日出、日落 `-120` 到 `+120` 分钟偏移。
- 仅由用户触发的 GitHub Release 更新检查，5 秒超时；启动和后台运行不发起更新请求，也不自动下载安装。
- `Odyphus.OpenCareEyes` WinGet 候选清单生成与关键字段测试。正式提交仍需在 Release 固定后运行 `winget validate` 并完成 Windows Sandbox 安装、升级和卸载测试。
- 便携版、安装版和 Release 随附 Python、PyInstaller、PySide6/Qt、Astral、darkdetect 的第三方许可与来源说明。
- schema v4 配置迁移、幂等保护、原子备份/回滚及未来 schema 只读启动。

### Changed

- `EffectCoordinator.reconcile(RuntimeIntent)` 成为色温、调暗、休息和专注实际写入的统一入口；页面、托盘、热键、方案、调度、全局暂停和情境感知只更新意图。
- 命令执行统一为“验证 → 设置快照 → 应用效果 → checked sync → 发布状态”；任一步失败时恢复设置和已应用效果，并在当前操作表面显示中文错误。
- 多输出 Gamma 应用改为全成功或全回滚；显示变化、解锁和睡眠恢复后重新探测能力。
- 热键从 `keyboard` Hook 改为 Win32 `RegisterHotKey`；原子批量注册失败时恢复旧组合。
- 完整状态只在语义变化时发布，倒计时通过独立 `break_tick` 更新，避免稳定情境每秒重建完整 `AppState`。
- 全新安装默认使用渐进提醒和桌宠；v0.3 用户缺失 `reminder_style` 时迁移为原全屏行为。
- 固定时间调度保留原星期规则；旧日出日落调度迁移为全周，再正确应用新的星期规则。
- 产品定位继续限定为观看舒适度和休息习惯，不宣称治疗、减少蓝光伤害或保护视网膜。

### Fixed

- 情境抑制、全局暂停、调度与用户操作不再绕过同一效果入口，避免界面与实际效果不一致或恢复旧快照。
- Gamma Ramp 静默失败、部分输出成功、遮罩创建失败或设置同步失败时不再显示“已生效”。
- 传感器连续失败 5 秒后解除 idle、全屏和应用规则等非安全抑制，避免永久卡在暂停；锁屏和睡眠仍保持安全暂停。
- 日出日落自动化现在正确执行星期规则。
- 高对比度、200% DPI、组合键捕获和可访问状态提示得到补强。

### Privacy

- 不保存每日或逐应用休息历史；重启后从新周期开始。
- EXE 选择器在 UI 层立即提取小写 basename，完整路径不得进入 Controller、设置、日志、备份或诊断包。
- 手动更新检查不发送设备标识；除用户点击检查外保持零更新网络请求。

## [0.3.0] - 2026-07-13

### Added

- 智能免打扰：识别全屏窗口、演示、独占 D3D、空闲、锁屏与睡眠情境，并在情境结束后恢复。
- 按小写 EXE 文件名配置的应用例外，可分别暂停休息、专注、色温和调暗效果。
- 自动化页“当前情境”卡片、总览与托盘统一的暂停原因/恢复条件，以及“本次场景继续提醒”。
- schema v3 配置迁移、未来版本只读保护和迁移失败回滚。
- 桌宠淡入、状态过渡与低频眨眼动画，支持系统减少动画、显式标准和精简模式。

### Changed

- `AppController` 保持命令门面职责；状态投影、情境策略和效果补偿拆分到独立协调器。
- 新安装默认使用 20-20-20、`1200/20` 和工作日 `19:00–07:30` 固定计划；升级用户保留旧有效默认。
- 自动抑制只改变实际运行状态，不覆写用户开关、严格休息或调度设置。

### Fixed

- 同一窗口每秒复查不再重启进入/退出防抖，避免全屏暂停或恢复永久等待。
- 情境效果部分失败时回滚并报告，补偿失败也会在界面与日志中可见。
- 休息倒计时边界增加 Windows 定时器提前唤醒容差，消除偶发重复秒数。

## [0.2.1] - 2026-07-12

### Added

- 可拖动、可关闭并能从休息设置重新开启的置顶倒计时桌宠。

### Fixed

- 所有休息阶段现在都会自动显示置顶全屏提醒，不再只有严格模式才出现遮罩。
- 严格休息会从全屏、主页面和托盘统一禁用延后，同时始终保留按钮和 `Esc` 安全退出。

## [0.2.0] - 2026-07-12

### Added

- Windows 11 Soft Fluent 风格的侧边导航、总览页与三步首次使用流程。
- 全局暂停、休息延后、可编辑热键、下一次自动动作及诊断导出。
- 单实例唤起、动态亮暗主题和本地优先的隐私说明。
- Windows CI：pytest、Ruff、PyInstaller onefile 构建和 EXE 启动冒烟测试。
- 标签发布流程：Inno Setup 安装包、SHA-256 清单和自动生成的 Release Notes。

### Changed

- 主界面、托盘、热键和自动调度改为共享应用状态。
- 休息计时改为基于单调时钟的状态机，调度启用后立即计算当前状态。
- 产品文案聚焦观看舒适度和休息习惯，不再宣称减少蓝光伤害或保护视网膜。
- `pyproject.toml` 成为版本号与 Python 依赖的唯一来源；规范源码分支改为 `main`。
- PyInstaller 与 Inno Setup 统一使用 `dist\OpenCareEyes.exe` 单文件产物。

### Fixed

- 修正 `src/` 布局的源码安装命令、包版本不一致、嵌套源码 ZIP 与安装器输入路径。
- 补全 Apache License 2.0 正文和卸载后本地设置的说明。

[Unreleased]: https://github.com/Odyphus/OpenCareEyes/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/Odyphus/OpenCareEyes/releases/tag/v0.4.0
[0.3.0]: https://github.com/Odyphus/OpenCareEyes/releases/tag/v0.3.0
[0.2.1]: https://github.com/Odyphus/OpenCareEyes/releases/tag/v0.2.1
[0.2.0]: https://github.com/Odyphus/OpenCareEyes/releases/tag/v0.2.0
