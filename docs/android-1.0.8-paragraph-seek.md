# Android 1.0.8：段落播放定位

包名 `jp.fujimi.newsbunko.next`，versionCode `9`。可以使用原签名覆盖安装 1.0.7。

## 本次修正

- 接入原 APK 前端已经存在的 `setupMobileMediaPlayer` 和 `playMedia`、`mediaStatus`、`seekMedia` 等桥接入口。继续使用同一个播放器、段落点击、进度条、暂停和倍速控件。
- Media3 直接打开 ArticleAudioAccess 验证后的本地文章文件，使用 EXACT 定位和 MP3 索引定位。文章音频无需通过 WebView 的虚拟 HTTPS 音频响应解码，也不需要 PC。
- 原生播放器建立时立即构建段落时间轴，使刚打开文章或刚生成音频后的第一次段落点击也有目标时间。
- 正式 PC／APP 共用的 `audioTimeline` 对 Edge 的 `edge_sentence` 时间直接定位。先前把服务器时间按解码器报告的总时长重新缩放，末尾静音或时长估计差异会改变段落起点。回归样本独立给定第 3 段从 4 秒开始、整段媒体 6 秒，旧时间轴得到 4.8 秒，新时间轴保持 4 秒。
- 跨请求合成使用当前 PC 所装 edge-tts 的 CBR 字节计时规则：`累计 MP3 字节数 × 8 × 10,000,000 ÷ 48,000`，替代 MediaMetadataRetriever 对各片段时长的估计。逐句映射、保存文件命名与 ArticleStore 提交保持原有流程。
- 原生播放失败也使用已经确认的底部居中 Toast，避免使用原 APK 协同分支中不适用于独立 APP 的“请先同步”提示。

Media3 的定位能力参见 [Mp3Extractor](https://developer.android.com/reference/androidx/media3/extractor/mp3/Mp3Extractor)；前端原始对照为 `apk-original/static/app.js` 的既有播放分支。

## 验证记录

- Android 15／API 35 模拟器 `emulator-5554`，AVD `fujimi-settings-api35`，设备 `sdk_gphone64_x86_64`：15 项设备测试通过。
- 新增设备测试使用临时文库和 15 秒合成 MP3，三段分别为 330／660／990 Hz。在 10.3、0.3、5.3、10.3、0.3 秒往返跳转后，经 TeeAudioProcessor 检查真实解码 PCM，均得到对应段落频率。还检查暂停、1.5 倍速、文章路径授权和音频字节不变。证据：`build/qa/android-1.0.8/decoded-pcm.log`、`device-tests.log`。
- 正式 WebView 使用 `adb input tap`：圭太整篇 MP3 257.232 秒，首次生成后播放；禁止再次合成后重新打开本地音频；6 次段落往返跳转后持续播放并正确高亮；暂停、恢复、倍速及失败 Toast 通过。正文和音频 SHA-256 不变，临时文章在结束后清理。证据：`build/qa/android-saved-audio/results.json`。
- 核心测试报告 71 项无失败。正式页面 375／390 px 手机与 1440 px 桌面检查通过；Edge 真实时间不受末尾静音缩放的回归检查覆盖手机与桌面播放路径。三份正式 JavaScript 语法检查通过。
- Tokyo 执行当前仓库实际存在的完整 Python unittest discover：2 项通过。历史完整测试文件当前不在此 checkout，不能把历史测试数量作为本次结果。
- Release 构建、签名、包名、版本与打包前端资源一致性检查通过。签名 SHA-256 与之前版本相同。

未连接 vivo X200s，本次不能声称已通过该手机真机验收。实际 PCM 检查使用可独立识别的合成段落；圭太联网样本验证真实生成、保存与播放操作，未使用语音识别核对每句文字。

## 安装包与数据

文件：`dist/FujimiShinbunBunkoAndroid/FujimiShinbunBunkoAndroid-1.0.8-release.apk`，70,024,387 字节。

APK SHA-256：`5940584f1218f95f4ab529e4d03e4a98f87dc781be7c1c0c7342db5a34567cf9`

签名证书 SHA-256：`5fd16c5eeb88d2f10b31f07fd0bb6386cdc353cc1ff904c4d296a8ced492e16b`

文库继续位于 `/storage/emulated/0/富士見新聞文庫/data/`。本次没有迁移或改写用户文库，无新增用户数据备份；测试使用临时目录。已有音频直接由原生播放器读取。安装前如需自行备份，可复制这个完整 `data/` 目录。
