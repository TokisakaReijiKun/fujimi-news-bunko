# 1.1.3：配对联动 Tailscale

开启 PC「文庫互联」后，发现已安装的 Tailscale CLI，已在线则复用，未连接则恢复既有配置；服务不可达时尝试打开已安装的 Tailscale 界面。只有确认在线并获得本机 Tailscale IPv4，才监听该地址的 8429 端口并生成配对码与二维码。没有安装 Tailscale 时保留原局域网路径，已安装但登录或连接失败会给出提示。

未登录时需要用户自行在 Tailscale 完成登录后再次开启配对；官方登录链接只在有效时显示。不代填账号、不重置 DNS／出口节点／访问策略。关闭配对仅关闭文库入口并撤销本应用会话，保留 Tailscale 连接。管理页面仍仅监听本机地址。

Android 沿用现有扫码、手动配对和内容存储，新增接受 `100.64.0.0/10` 地址，普通公网、域名、IPv6 和含账号／路径／参数的地址仍拒绝。手机仍须自己启用 Tailscale 并接入同一网络，使用计费网络时须允许蜂窝网络。

按用户要求，仅做离线检查与构建：Python 全回归 67 项通过，Android core 109 项通过，设置页的准备中、就绪、关闭、待登录及安全链接状态通过 mock 检查；另经独立代码审查。没有启动真实 VPN、登录、实机或跨网验收，没有改动用户文库。

实现参考 Tailscale 官方 [CLI](https://tailscale.com/docs/reference/tailscale-cli) 与 [up 命令](https://tailscale.com/docs/reference/tailscale-cli/up)：无设置参数恢复已保存的连接配置，进程等待有界，原始状态和认证错误不写日志。

APK：`dist/FujimiShinbunBunkoAndroid/FujimiShinbunBunkoAndroid-1.1.3-release.apk`，版本 1.1.3/code26，73,637,514 字节，SHA-256 `a5cb8a4b6dd9d42abfeca67ba7f98d858c15bf42de3bcf5b8f763aecb55d8099`。沿用 1.1.2 签名，25 项正式静态资源与源码一致。

PC 已原位更新 `dist/FujimiShinbunBunko/FujimiShinbunBunko.exe`：65,836,912 字节，SHA-256 `eca0296a6cded191b5bac9988d54f70ccbd95a8dc9a15879d3dfd5da94035478`。只替换 EXE 和 16 项变化／缺失的静态资源，复用全部既有运行依赖；保留现装 PC `book-reader.css` 的字号排版以及原有浅色播放器素材。更新前核对精确进程路径、无活动任务与同步连接，再停止旧桌面进程；更新后未启动新版。

没有数据迁移或备份，没有复制整套 `_internal`。离线包审核及部署记录分别在 `build/qa/mobile-app-1.1.3/`、`build/qa/desktop-1.1.3/`。

## PC 界面范围纠正

用户随后指出 PC 播放器被改动。前一次只保留 `book-reader.css` 并不足够：整份共享主样式、模板和脚本仍带入了 Android 播放器及全局阅读改动，这是部署范围错误。

现以已有旧 PC 构建资源为对照，恢复 PC 默认播放器 DOM、渲染、倍速菜单、阅读排版和样式；现代播放器和阅读差异限定在 `data-redesign-app` 下，Tailscale 设置变化保留。PC 原播放器最大宽度 580px、距底部 12px、圆角 24px，原文／译文排版及控件与旧构建在 1100／1440px 离线逐属性对照一致。手机界面和阅读排版离线回归也通过。

此次仅更新静态界面资源，桌面 EXE、Tailscale 后端和现有 APK 不变。未启动实际桌面程序或 VPN，未操作用户文库；已有窗口需从托盘退出后重新打开以载入更新。对照记录在 `build/qa/pc-scope-restore/`。
