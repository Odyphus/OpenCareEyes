# OpenCareEyes — LEARNING_LOG

## 1. 决策背后的"为什么" (The Reasoning)

### 为什么选择 PySide6 而非 Tkinter / PyQt / Electron
- **PySide6 (Qt for Python)** 是 Qt 官方维护的 Python 绑定，采用 LGPL 许可，商业友好
- 相比 Tkinter：PySide6 提供更丰富的控件（QSystemTrayIcon、QTabWidget）、更好的多显示器支持、原生样式表（QSS）
- 相比 PyQt6：许可证更宽松（LGPL vs GPL），API 几乎相同
- 相比 Electron：内存占用低一个数量级，启动速度快，适合常驻后台的工具类应用

### 为什么用 SetDeviceGammaRamp 实现蓝光过滤
- **直接操作显卡 Gamma 查找表**，零性能开销，不影响游戏帧率
- 替代方案对比：
  - 覆盖窗口 + 橙色半透明：会影响鼠标点击、截图颜色失真
  - ICC 色彩配置文件：修改复杂，恢复困难
  - Direct3D Hook：侵入性强，兼容性差
- LightBulb、f.lux、Redshift 等成熟项目均采用此方案

### 为什么用透明覆盖窗口实现调光而非 Gamma Ramp
- Gamma Ramp 已被蓝光过滤占用，两者共用会互相覆盖
- 覆盖窗口方案通过 `WA_TransparentForMouseEvents` 实现点击穿透，用户无感知
- 调光和蓝光过滤可以独立控制、叠加使用

### 为什么用 SetWinEventHook 实现专注模式
- **非侵入式**：不需要 DLL 注入，使用 `WINEVENT_OUTOFCONTEXT` 在进程外接收事件
- 替代方案 `SetWindowsHookEx` 需要 DLL 注入到目标进程，复杂且有安全风险
- `EVENT_SYSTEM_FOREGROUND` 事件精确捕获前台窗口切换

### 为什么用 QSettings 而非 JSON/YAML 配置文件
- QSettings 在 Windows 上自动使用注册表存储，符合平台惯例
- 自动处理类型序列化/反序列化
- 线程安全，无需手动处理文件锁

### 为什么用 QLocalServer 实现单实例控制
- Qt 原生方案，跨平台兼容
- 替代方案（文件锁、命名互斥体）在异常退出时可能残留锁文件

## 2. 隐藏的陷阱与 Bug (Bugs & Pitfalls)

### Gamma Ramp 值溢出
- **问题**：`i * r * 257` 在 i=255, r=1.0 时结果为 65535，但中间计算可能因浮点精度超出 `c_ushort` 范围
- **解决**：在 `_build_gamma_ramp` 中使用 `min(65535, int(...))` 钳位

### WINEVENTPROC 回调被垃圾回收
- **问题**：ctypes 回调函数如果没有保持 Python 引用，会被 GC 回收，导致段错误
- **解决**：在 `FocusMode.__init__` 中将 `WINEVENTPROC(self._win_event_callback)` 存储为 `self._callback` 实例属性

### MONITORENUMPROC 回调同理
- **问题**：`EnumDisplayMonitors` 的回调如果定义为局部变量装饰器，在某些 Python 版本下可能被提前回收
- **解决**：在 `MonitorManager.refresh()` 中使用 `@MONITORENUMPROC` 装饰器并在函数作用域内保持引用

### QApplication 退出时 Gamma Ramp 未恢复
- **问题**：如果程序崩溃或被强制终止，屏幕会保持修改后的色温
- **解决**：在 `__main__.py` 中通过 `app.aboutToQuit.connect(on_exit)` 注册清理函数；`BlueLightFilter` 在 `enable()` 时保存原始 ramp

### 覆盖窗口在全屏游戏中的行为
- **潜在问题**：`WindowStaysOnTopHint` 在独占全屏（Exclusive Fullscreen）模式下可能不生效
- **缓解**：大多数现代游戏使用无边框全屏（Borderless Fullscreen），覆盖窗口可正常工作

### QSettings 类型丢失
- **问题**：QSettings 从注册表读取值时，所有值默认为字符串
- **解决**：在每个 `value()` 调用中显式传入 `type=bool`/`type=int`/`type=float` 参数

## 3. 核心逻辑解释 (Core Logic)

### 色温转换算法 (Tanner Helland)
基于黑体辐射的经验公式，将开尔文色温映射到 RGB 乘数。核心思路：色温越低，蓝色通道衰减越多（模拟烛光/日落），红色通道始终保持较高值。算法分 66K（6600K）为界，低于此值时 R=1.0 且 G/B 按对数/幂函数衰减。

### Gamma Ramp 构建
256 级灰度 × 3 通道 = 768 个 `unsigned short` 值。每个值 = `灰度级 × 通道乘数 × 257`，其中 257 将 0-255 映射到 0-65535（因为 `255 × 257 = 65535`）。这保证了线性映射且充分利用 16 位精度。

### 日出日落调度
使用 `astral` 库根据经纬度计算当日日出日落时间，通过 `QTimer.singleShot` 在精确时刻触发蓝光过滤的开/关。如果当日两个事件都已过去，自动计算次日日出时间。

## 4. 导师建议 (Tutor's Advice)

### 深入学习方向
- **Win32 API 编程**：推荐阅读 Charles Petzold《Programming Windows》了解 GDI、消息循环、窗口管理的底层原理
- **Qt/PySide6 进阶**：阅读 Qt 官方文档中的 [Signals & Slots](https://doc.qt.io/qt-6/signalsandslots.html) 和 [The Event System](https://doc.qt.io/qt-6/eventsandfilters.html)
- **色彩科学**：了解 CIE 色度图、色温与黑体辐射的关系，推荐《Color Science: Concepts and Methods》
- **ctypes 深入**：阅读 Python 官方文档 [ctypes — A foreign function library](https://docs.python.org/3/library/ctypes.html)，特别是回调函数、结构体对齐、内存管理部分
- **软件架构**：本项目采用了简单的分层架构（platform → core → ui），如果后续功能增多，可以学习 MVVM 模式，推荐阅读《Clean Architecture》(Robert C. Martin)

### 实践建议
- 尝试用 `pyinstaller` 打包为单文件 exe，理解 frozen 环境下的路径处理
- 添加日志文件输出（`logging.FileHandler`），方便用户反馈问题时提供日志
- 考虑添加 CI/CD（GitHub Actions）自动运行测试和构建
