# Android 1.0.7 NHK 视频处理记录

日期：2026-10-02。

APP 原来只解析 NHK 的 `.m3u8` 地址并标记为预览，所以文章会显示“NHK 视频需要原站播放授权或 HLS 处理，当前未下载”。PC 客户端会复用同一 HTTP 会话完成海外匿名授权，然后使用 `web.nhk` 的 `z_at` 会话向 `mediatoken.web.nhk/v1/token` 请求短期 `hdnts` 令牌。

本版将该流程接入 Android 日刊后处理：

- 地区检查、匿名授权和令牌请求均使用同一个 TLS、公开地址校验和 Cookie 会话；不读取或保存账号凭据。
- 授权后的 `media.vd.st.nhk` HLS 地址保留为文章媒体 URL，并标记为视频；WebView CSP 允许 NHK 官方 HLS.js 资源，APP 内直接播放。
- HLS 仍是在线授权播放，令牌过期后需要重新获取文章或重新执行日刊。Android 端没有 PC 的 ffmpeg 合并链，因此不把它伪装成本地 MP4，也不写入另一套媒体目录。
- 授权失败、地区不满足或令牌无效时，保留原站预览地址和明确失败提示，不显示假视频。

交付 APK：`dist/FujimiShinbunBunkoAndroid/FujimiShinbunBunkoAndroid-1.0.7-release.apk`，70,015,271 字节；SHA-256：`31a00888bd4e53ee8e5d093e7b1deb552389bb16075a39c58ea9fb69a0224604`。包名 `jp.fujimi.newsbunko.next`，versionCode 8；APK Signature Scheme v2 通过，证书 SHA-256 为 `5fd16c5eeb88d2f10b31f07fd0bb6386cdc353cc1ff904c4d296a8ced492e16b`。

验证：Kotlin/Android debug 与 release 构建通过，核心测试 71 项通过；Android 设置 WebView 测试页 375/390/812px 和桌面布局检查通过；三份前端 JavaScript、验收脚本语法检查和 `git diff --check` 通过。当前没有在真机或真实 NHK 授权会话中测试；最终设备回归时模拟器已离线，不应把此前 1.0.6 的 14 项设备结果当作本版 NHK 授权证据。模拟器没有写入用户文库。
