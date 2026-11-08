# 1.1.26：声线勾选、试听及词典朗读修复

保留 1.1.25 的声线分层与现有布局，不增加控件。外层仍显示「システム音声（圭太）」和参考声线，内层保留逐项试听。

- 内层勾选依据已保存的 `browser_voice_name`，不再受外层当前参考声线模式影响。选择参考声线时，内层仍显示已配置的圭太或七海。
- 手机词典与 PC 的选择语义一致：使用已配置的浏览器声线，显式向原生接口传入声线 ID。外层选择参考声线不再阻止词典使用圭太，也不更改参考声线选择。
- 圭太、七海原请求使用旧版 GEC，实际请求均返回 403。Android 改用上游当前 v2 格式，保留 TLS 校验；403 时仅依据服务器时间校正并重试一次。收到完整结束消息后，迟到的连接关闭异常不再覆盖成功结果。二进制音频头按完整长度解析。
- GEC 实现参考 [edge-tts 的 drm.py](https://github.com/rany2/edge-tts/blob/master/src/edge_tts/drm.py)，许可证随 APK 收入 `META-INF/edge-tts-LICENSE.txt`。没有更改 PC 的 Python 依赖或客户端。

## 验证与范围

Android core 142 项测试通过，0 失败、0 错误、0 跳过，包含 v2 请求算法的 7 组固定时间向量。JavaScript 语法检查通过。

375/390px 手机界面检查覆盖参考声线选中时的内层圭太勾选、七海独立试听、词典显式调用圭太并保留全局参考声线、原有参考音频及文件/URL 修改流程。1440px PC 页面前后布局一致，无新增溢出或脚本错误。此项 UI 检查的桥接回调为测试替身；实际解码播放另由以下原生测试验证。

隔离的 API 35 Android 模拟器实际完成两声线在线请求、MediaPlayer 解码及播放：圭太、七海均收到 `start`、`done`。保存 MP3、离线复用及保存音频实际播放检查通过；长段落跨请求音频及段落时间检查通过。最终两项播放测试输出 `OK (2 tests)`，见 `logs/voice-playback-device-final.log`。仅模拟器临时使用现有本机代理接入网络，检查结束后已恢复其代理设置并关闭模拟器。未验证真实手机网络或扬声器效果。

正式前端和词典资源以 1.1.25 APK 为基线：33 个文件集合不变，仅 `assets/static/index.html` 的缓存标记、`assets/static/mobile-app.js` 的选中逻辑及缓存标记、`assets/static/main.js` 的手机词典朗读分支变化。词典资源保持逐字节一致。此次不更新 PC 客户端，不迁移用户数据，不创建备份。

## 安装包

`dist/FujimiShinbunBunkoAndroid/FujimiShinbunBunkoAndroid-1.1.26-release.apk`，versionCode 49。

73,799,023 字节，SHA-256 `d5f1f3578da99b36ec452e326c6c9adc052f886c5a92d2582fda8d2c6f37cb52`。

正式签名验证通过，证书 SHA-256 `5fd16c5eeb88d2f10b31f07fd0bb6386cdc353cc1ff904c4d296a8ced492e16b`，与 1.1.25 一致，可覆盖安装。资源和签名核对见 `build/qa/voice-playback-fix/release-check.json`、`release-signature.json`。
