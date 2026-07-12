# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)；版本号遵循语义化版本。

## [Unreleased]

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

[0.2.0]: https://github.com/Odyphus/OpenCareEyes/releases/tag/v0.2.0
