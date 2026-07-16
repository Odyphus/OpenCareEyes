# OpenCareEyes v0.6 GitHub 发布指南

`main` 是唯一规范源码分支。旧 `master` 分支只保留迁移说明，不再接收功能更新。

## 1. 提交前

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,build]"
python -m ruff check src tests scripts
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest -q
python -m PyInstaller --noconfirm --clean opencareyes.spec
```

逐项完成 [UPLOAD_CHECKLIST.md](UPLOAD_CHECKLIST.md)，尤其确认：

- `pyproject.toml` 是版本号唯一来源，版本为 `0.6.1`。
- v0.4.1 的统一效果入口、HDR 安全、休息遮罩稳定性和设置迁移测试保持通过。
- 官方宠物包在启动与构建测试中通过路径、扩展名、帧尺寸、动作、锚点和资源完整性验证；白鼬使用 schema v2、2x atlas 且 v1 兼容测试通过，发行版不包含测试宠物包。
- 宠物切换回滚、动作优先级、隐藏后定时器停止、天气未授权零网络、便签与诊断隔离、回收站确认均有测试。
- README 的白鼬预览来自实际随包资源；v0.4 历史截图/GIF 明确标为旧界面，不能冒充 v0.6“伙伴小屋”。
- 未提交日志、诊断包、构建目录、坐标 URL、便签正文、窗口标题、完整 EXE 路径、鼠标轨迹或使用历史。
- `PRODUCT.md`、`DESIGN.md`、`CHANGELOG.md`、`使用说明.md`、`SECURITY.md` 已记录产品边界、设计约束、用户可见变更、隐私边界和医疗边界。

## 2. 发布版本标签

确认分支保护和 CI 通过后：

```powershell
git switch main
git pull --ff-only
$Version = "v0.6.1" # 必须与 pyproject.toml 一致
git tag -a $Version -m "OpenCareEyes $Version"
git push origin main
git push origin $Version
```

`v*` 标签会触发 Windows CI，构建：

- `OpenCareEyes.exe`
- `OpenCareEyes_Setup_0.6.1.exe`
- `SHA256SUMS.txt`
- `OpenCareEyes_WinGet_0.6.1.zip` 候选清单
- `THIRD_PARTY_NOTICES.md`（安装包和便携版内同时包含完整 `licenses/` 文本）

工作流随后创建 GitHub Release。不要在 Release 工作流成功前创建同名正式 Release，也不要修改已经用于 WinGet 的版本固定资产。

## 3. 验证 GitHub Release

在匿名/无登录浏览器中逐项验证：

1. Tag、Release 标题和 `pyproject.toml` 都是 `0.6.1`。
2. 五个发布资产可下载，文件名无误。
3. `SHA256SUMS.txt` 与实际便携版、安装版、WinGet ZIP 和第三方 notice 完全匹配。
4. 在干净 Windows 环境完成便携启动、单实例唤起、安装、从 v0.5.0 升级和卸载；确认应用名、AppId 与用户设置路径保持兼容。
5. Release Notes 与 `CHANGELOG.md` 及真实提交一致，不宣称未实现的功能。
6. 明确说明 OpenCareEyes 不是医疗器械，不承诺减少蓝光伤害或保护视网膜。
7. 明确说明 SHA-256 与 WinGet 不等同于代码签名，也不能保证消除 SmartScreen。

若 Release 资产发生任何变化，必须重新生成 SHA-256 和 WinGet 清单，再重新执行全部验证；不能只替换文件而沿用旧哈希。

## 4. WinGet 候选清单

仓库和 GitHub Release 中的 `Odyphus.OpenCareEyes` 清单只是候选文件，不能声称已经被 WinGet 官方源收录。正式提交必须在 GitHub Release 资产固定后进行。

使用与 Release 完全相同的最终安装包生成清单：

```powershell
python scripts\generate_winget_manifest.py `
  .\installer_output\OpenCareEyes_Setup_0.6.1.exe `
  --version 0.6.1

winget validate .\winget_output\manifests\o\Odyphus\OpenCareEyes\0.6.1
```

然后按 [Microsoft WinGet 提交流程](https://learn.microsoft.com/windows/package-manager/package/repository) 完成：

1. 检查 `InstallerUrl` 指向版本固定的 `v0.6.1` GitHub Release 资产，不使用 `/latest/`。
2. 检查 `InstallerSha256` 与在线下载的安装包一致。
3. `winget validate` 无错误；不要用忽略警告掩盖需要修复的问题。
4. 在全新 Windows Sandbox 中验证静默安装、正常启动、从上一版本升级和卸载。
5. 确认安装范围、快捷方式、自启动项和用户数据保留/清理行为符合清单与使用说明。
6. 测试通过后再向 `microsoft/winget-pkgs` 提交 Pull Request，并等待自动验证/人工审核完成。

只有社区仓库 PR 合并且客户端源已同步后，才能说明该版本已被 WinGet 收录。WinGet 收录与 SHA-256 都不能替代受信任代码签名，也不能承诺消除 SmartScreen。

## 5. 分支维护

确认 `main` 已包含完整历史与源码后：

1. 在 GitHub 设置中将默认分支设为 `main`。
2. 为 `main` 启用 Pull Request 和 CI 保护规则。
3. 在 `master` 的 README 中保留迁移提示。
4. 所有链接与自动化均转向 `main` 后，再按维护计划删除旧分支。
