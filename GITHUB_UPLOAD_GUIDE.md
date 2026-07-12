# OpenCareEyes GitHub 发布指南

`main` 是唯一规范源码分支。旧 `master` 分支只保留迁移说明，不再接收功能更新。

## 提交前

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,build]"
python -m ruff check src tests scripts
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest -q
python -m PyInstaller --noconfirm --clean opencareyes.spec
```

同时检查：

- `pyproject.toml` 是版本号的唯一来源。
- README 截图与真实界面一致。
- `CHANGELOG.md` 已记录用户可见变更。
- 未提交日志、诊断包、构建目录或私人位置数据。

## 发布 v0.2.0

```powershell
git switch main
git pull --ff-only
git tag -a v0.2.0 -m "OpenCareEyes v0.2.0"
git push origin main
git push origin v0.2.0
```

`v*` 标签会触发 Windows CI，构建便携 EXE、Inno Setup 安装包和
`SHA256SUMS.txt`，并根据提交记录生成 Release Notes。

## 分支迁移

确认 `main` 已包含完整历史与源码后：

1. 在 GitHub 设置中将默认分支设为 `main`。
2. 为 `main` 启用 Pull Request 和 CI 保护规则。
3. 在 `master` 的 README 中保留一个版本的迁移提示。
4. 所有链接与自动化均转向 `main` 后，再删除旧分支。
