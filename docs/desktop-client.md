# Windows 桌面客户端

桌面客户端使用 pywebview 的 WebView2 窗口承载现有页面。启动时，它先在 `127.0.0.1:8428` 绑定同一套 Flask API，然后打开桌面窗口。点击窗口关闭按钮会将窗口隐藏到 Windows 托盘，服务和日刊定时器继续运行；点击托盘图标或在右键菜单中选择“打开窗口”可恢复。选择托盘菜单“退出”才会停止服务和 TTS 队列。原站链接在系统浏览器中打开。

## 从源码运行

在 Windows 上安装 Microsoft Edge WebView2 Runtime，并使用 Tokyo 环境安装桌面依赖：

```powershell
conda run -n Tokyo python -m pip install -r requirements-desktop.txt
./start-desktop.ps1
```

源码桌面版直接使用项目的 `data/`、`.env`、词典和 Irodori 模型，功能与本地 Web 服务相同。Web 服务默认使用 8427，桌面版默认使用 8428，两者可以同时打开。桌面进程将 PID 写入 `logs/desktop.pid`，不会覆盖 Web 服务的 `logs/server.pid`。可用 `./start-desktop.ps1 -Port 8430` 另选端口。

源码版与 Web 服务共用 `data/` 时，请避免两端同时写入。即使没有手动操作，两端的自动日刊任务仍可能并发写入；需要完全隔离时，设置不同的 `FUJIMI_DATA_DIR`。

## 制作 Windows 程序

```powershell
./build-desktop.ps1
```

构建结果是 `dist/FujimiShinbunBunko/FujimiShinbunBunko.exe` 及同目录的运行文件，分发时需要保留整个文件夹。构建会包含正式前端和只读词典，不包含 `data/`、`.env`、日志或 Irodori 的多 GB 模型。安装包需要 WebView2 Runtime；构建脚本不会下载模型或修改原 APK 资源。

在本项目的 `dist/FujimiShinbunBunko/` 内运行时，独立程序默认使用项目 `data/`，与 Web 服务显示同一文库。移出项目后，默认数据目录为 `%LOCALAPPDATA%/FujimiShinbunBunko/data/`；也可在启动前设置 `FUJIMI_DATA_DIR` 指定文库目录，此设置始终优先。日志写到所选数据目录内的 `logs/`。切换默认目录不会搬移或删除旧目录中的数据。两端共用目录时避免同时写入，包括自动日刊任务。

独立程序从所选数据目录的上级目录读取本机 `.env`，进程环境变量优先；密钥不会打包。

Microsoft Edge 中保存的在线自然声线不会自动出现在 WebView2 中。桌面窗口显示本机日语声线和 Edge 在线声线，但声线选择始终读写与 Web 端相同的 `voice-mode` 设置，不使用独立的桌面声线配置。书籍、文章和其他文库数据仍沿用所选 `data/`。
安装桌面依赖中的 `edge-tts` 后，桌面声线菜单还提供圭太与七海两条在线声线。选中后，客户端通过本机服务向 Edge 在线语音服务请求 MP3；需要网络，失败会报错且不会假装已朗读。Web 端和桌面端看到的是同一个当前声线。

在文章阅读器的“読み返し”中，当前共享声线若为圭太或七海，点击生成会把在线 MP3 保存到该文章的 `audio/` 目录，文章状态变为已完成音频；再次生成时直接查找对应文件，不依赖附件登记。其他普通“浏览器本机声线”仍只即时播放，不能导出文件。

独立程序不打包 Irodori 模型或推理环境。在本项目内运行且找到 `Irodori-TTS/model/model.safetensors` 与 conda Tokyo Python 时，它会使用项目现有模型和 `data/voices/` 声线文件，支持与 Web 端相同的本地 Irodori 合成。Tokyo 路径不在常见安装位置时，可设置 `FUJIMI_TTS_PYTHON` 为该环境的 `python.exe`。移出项目或缺少运行环境时，Irodori 不启用，仍可使用 WebView2 本机日语朗读。两端共用文库时避免同时生成同一文章或章节的音频。通过托盘菜单退出时若有未完成的日刊、导入、翻译或朗读任务，会先询问是否中断。
