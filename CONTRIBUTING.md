# 参与 OpenCareEyes

## 开发环境

OpenCareEyes v0.2 仅支持 Windows 10/11 和 Python 3.10+。完整源码位于规范分支 `main`。

```powershell
git clone --branch main https://github.com/Odyphus/OpenCareEyes.git
cd OpenCareEyes
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,build]"
```

项目采用 `src/` 布局。不要通过手动修改 `PYTHONPATH` 绕过安装，也不要在代码中复制版本号；版本只在 `pyproject.toml` 中维护。

## 提交前验证

```powershell
python -m ruff check src tests
python -m pytest
python -m PyInstaller --noconfirm --clean opencareyes.spec
```

涉及 Win32、Gamma Ramp、透明遮罩或 DPI 的改动，还应在 Windows 10/11、单屏/多屏、100%–200% 缩放下实测，并在 Pull Request 中写明环境和结果。

## Pull Request

1. 从 `main` 创建范围单一的分支。
2. 说明问题、方案、用户可见变化和验证方式。
3. 修复缺陷时增加复现测试；新功能覆盖成功与失败状态。
4. 不提交 `dist/`、安装包、日志、位置或其他个人数据。
5. 界面截图放在 `docs/images/`，使用真实应用画面，不提交虚构占位图。

提交贡献即表示你同意按项目的 [Apache License 2.0](LICENSE) 许可该贡献。
