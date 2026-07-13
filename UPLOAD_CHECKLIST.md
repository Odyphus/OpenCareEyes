# OpenCareEyes v0.3.0 发布检查表

## 代码与测试

- [ ] `python -m ruff check src tests scripts` 通过。
- [ ] `python -m pytest -q` 通过。
- [ ] 空配置、v1→v2→v3、v2→v3、失败回滚与未来 schema 只读均已验证。
- [ ] 托盘、主界面、快捷键和自动化的状态一致。
- [ ] 亮色、暗色和跟随系统主题无需重启即可生效。

## Windows 实机

- [ ] Windows 10 与 Windows 11 均已启动。
- [ ] 100%、125%、150% 和 200% DPI 下无裁切。
- [ ] 单屏、负坐标双屏和显示器热插拔已验证。
- [ ] 色温、调暗和专注效果失败时会显示原因。
- [ ] 休息提醒可延后、跳过，全屏提示始终可安全退出。
- [ ] 浏览器全屏视频、PowerPoint 放映、D3D 游戏、Alt+Tab 和应用规则已验证。
- [ ] 空闲 2/5 分钟、锁屏、睡眠恢复与“本次场景继续提醒”已验证。
- [ ] 桌宠隐藏后无活动定时器，系统减少动画和 200% DPI 已验证。
- [ ] 状态、日志、配置备份和诊断 ZIP 不含窗口标题或完整 EXE 路径。

## 发布物

- [ ] `pyproject.toml` 版本为 `0.3.0`，Tag 为 `v0.3.0`。
- [ ] `dist\OpenCareEyes.exe` 可在干净系统上启动。
- [ ] `OpenCareEyes_Setup_0.3.0.exe` 可安装、升级与卸载。
- [ ] `SHA256SUMS.txt` 与发布物匹配。
- [ ] README 截图、GIF、隐私说明和功能描述均与本版一致。
- [ ] Release Notes 来自 `CHANGELOG.md` 与真实提交。
