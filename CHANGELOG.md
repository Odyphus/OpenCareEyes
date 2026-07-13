# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)；版本号遵循语义化版本。

## [Unreleased]

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

[Unreleased]: https://github.com/Odyphus/OpenCareEyes/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Odyphus/OpenCareEyes/releases/tag/v0.3.0
[0.2.1]: https://github.com/Odyphus/OpenCareEyes/releases/tag/v0.2.1
[0.2.0]: https://github.com/Odyphus/OpenCareEyes/releases/tag/v0.2.0
