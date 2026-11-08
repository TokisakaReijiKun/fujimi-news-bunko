# Android 1.1.6：Tailscale 自动唤起与 toast

配对（手填或扫码）及手动同步使用 `100.64.0.0/10` 地址时，先检查可见 VPN 网络的 IPv4。尚未连接则打开已安装的 `com.tailscale.ipn`，发送其正式 `CONNECT_VPN` 请求；登录和 Android VPN 授权仍由用户完成。返回文库后等待 VPN 就绪并继续原操作。已连接直接复用，局域网不唤起；未安装、未授权或超时返回实际错误，不产生配对成功状态。等待外部客户端时暂停前端的 45 秒网络超时，返回并开始网络连接后恢复；变更地址及销毁客户端会取消旧操作。

手机设置中的连接和通信操作反馈改用现有 toast。直接删除原反馈段落及动态追加小字的分支；弹窗内把 toast 放入 dialog 上层，底部悬浮显示并自动消失。

验证：110 项核心测试、3 项 Android 设备测试通过。API 35 隔离模拟器从正式 WebView 点击连接，实际唤起官方 Tailscale 1.104.5；取消首次 VPN 授权并返回文库后，真实屏幕显示失败 toast，按钮恢复且没有配对成功。未使用个人账号登录，未验证手机加入用户实际 Tailnet 后的端到端配对。375／390px 的正式打包资源测试通过，含外部登录阶段的超时暂停、toast 层级、反馈节点移除、重复操作和 PC 页面隔离。

沿用原包名及发布签名，版本 1.1.6/code29，可覆盖安装。包内相对 1.1.5 仅有五个静态资源变化：`index.html` 的资源版本、`main.js` 的移动配对阶段回调、`mobile-app.js`、`mobile-settings.js` 和 toast 样式。其余 20 项静态资源及词典一致。打包样式保留 1.1.5，未带入工作区已有的两条无关日刊按钮样式。

安装包：`dist/FujimiShinbunBunkoAndroid/FujimiShinbunBunkoAndroid-1.1.6-release.apk`（73,652,750 字节）。证据与包校验：`build/qa/mobile-tailscale/`；构建和设备测试日志：`logs/mobile-tailscale-*.log`。没有更新 PC 安装目录、迁移或备份用户文库。模拟器和调试转发已关闭。
