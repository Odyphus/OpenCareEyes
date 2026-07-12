# OpenCareEyes v0.2.0 发布检查表

## 代码与测试

- [ ] `python -m ruff check src tests scripts` 通过。
- [ ] `python -m pytest -q` 通过。
- [ ] 全新设置与 v0.1.1 设置迁移均已验证。
- [ ] 托盘、主界面、快捷键和自动化的状态一致。
- [ ] 亮色、暗色和跟随系统主题无需重启即可生效。

## Windows 实机

- [ ] Windows 10 与 Windows 11 均已启动。
- [ ] 100%、125%、150% 和 200% DPI 下无裁切。
- [ ] 单屏、负坐标双屏和显示器热插拔已验证。
- [ ] 色温、调暗和专注效果失败时会显示原因。
- [ ] 休息提醒可延后、跳过，全屏提示始终可安全退出。

## 发布物

- [ ] `pyproject.toml` 版本为 `0.2.0`，Tag 为 `v0.2.0`。
- [ ] `dist\OpenCareEyes.exe` 可在干净系统上启动。
- [ ] `OpenCareEyes_Setup_0.2.0.exe` 可安装、升级与卸载。
- [ ] `SHA256SUMS.txt` 与发布物匹配。
- [ ] README 截图、GIF、隐私说明和功能描述均与本版一致。
- [ ] Release Notes 来自 `CHANGELOG.md` 与真实提交。
