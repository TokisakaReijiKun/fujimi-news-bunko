# Android 1.0.13：阅读字号与音频控制

## 参考 APK 的证据

用户提供 `D:/QQ/Documents/1512906019/FileRecv/Moji阅读.apk.1`：MOJi 阅读 3.4.1，包名 `com.mojidict.read`，版本号 341，SHA-256 为 `d88f0817433f772f4c00b7a71332c2533eeb47cf8debaa96f1536d78f96f6c3c`。

本次针对播放器和阅读排版做静态逆向：REA 校验归档与资源清单，Android SDK `aapt` 解码资源表和二进制 XML，直接检查 APK 内置 H5 的 CSS/JavaScript。REA 归档证据为 `ev_124b3275f8f071b623dc7a00b4baf23c088f372ae9e084c371c9eb9e36345303`。JADX 组件未配置，没有进行完整 DEX 反编译，也没有运行参考 APK。

- `layout_audio_player_manager`（`res/UmU.xml`）：当前时间、进度条、总时间横排；下一行中央为前一项、播放、后一项，右侧设置与速度角标。原生时间文字为 14dp、轨道 4dp、中央播放圆形 40dp。前后按钮的具体运行语义不能单凭 XML 确定；本项目明确实现为上一段/下一段。
- `assets/h5hybrid/assets/MOJiArticleDetail-86a0a246.css`：正文 `calc(16px * var(--font-size))`、行高 2；译文字号 1em、行高 1.75em；假名 .58em。
- `MOJiArticleDetail-121467f1.js`：`fontSize` 入参缺省 1，传入 `MOJiArticleDetailSetFontSize`。原生保存的用户字号选项可能覆盖这一倍率，因此 16px 是内置页面基准，未宣称是每台设备的运行字号。

完整资源映射与解码结果保留在 `build/research/moji/native-layout/`。实现沿用本项目墨绿配色和现有字体，没有引入参考软件的业务接口、字体文件或图标资源。

## 实现

- 新闻与书籍复用同一份播放器模板：第一行是时间与进度，第二行是居中的上一段、播放/暂停、下一段和右侧倍速；图标采用 SVG。播放按钮保留 40px 视觉圆形，按钮和拖动区域提供 48px 触摸高度。
- 前后按钮接入现有真实段落定位。已保存音频用时间轴，Android Media3 用原生播放位置，即时朗读用文本分段；首末段按钮禁用。保留冷启动跳播、段落高亮、播放/暂停、拖动、倍速保存与错误提示。
- 倍速菜单支持方向键、Home/End、Escape，关闭后返回触发按钮焦点；保持 Android 返回操作和深色样式。
- 清理重叠的旧播放器规则，集中维护一套布局。底部正文留白和提示位置随播放器高度调整。
- 正文与译文共享 `1rem`（默认 16px），日文行高 2、中文行高 1.75、假名 .58em。新闻全文译文、书籍全部语言模式、新旧 EPUB 解析结果以及横纵排使用同一基准。系统和根字号放大继续有效。
- 保留新闻来源的小标题、EPUB 内部标题及相对字号、强调、上下标、注音结构和锚点。

## 验收与数据范围

浏览器测试使用正式页面和合成内容：

- `verify_reader_type_player.cjs`：375/390/1440px，6 组明暗模式、144 项字号样本和 18 种播放组合通过。HTMLAudio 使用可解码的合成 WAV；Media3 和系统朗读接口使用 mock。
- 上一项同时覆盖前后段、首末禁用、暂停/恢复、进度拖动、1.5 倍持久化、菜单键盘与焦点；回归检查朗读换行间隙及原生时长未返回时的连续跳段。
- `verify_android_audio_ui.cjs` 3 组、`verify_audio_paragraph_boundary.cjs` 6 组、`verify_voice_sync_frontend.cjs` 通过。
- 常规页面检查：8 组、104 张截图，0 失败。保留横屏、深色、大字和无障碍检查。
- JavaScript 语法与 `git diff --check` 通过。Debug/Release 构建成功，核心测试报告为 93 项通过。Release v2 签名有效，六个正式页面资源与源码 SHA-256 一致。
- 隔离 Android API 35 模拟器：通过实际触摸验证新闻与书籍 Media3 的播放、上一/下一段、暂停/恢复和倍速。375px、系统字体 200%、系统深色时，两端正文和译文均为 32px（16px 基准放大），假名 18.56px，无横向溢出；按钮触区至少 48px。播放器外高 130px（含边框），底部避让 24px 系统栏并保留 12px 间距。验收安装的是当前 Debug APK，未依赖注入样式。未连接实体手机。

报告与截图在 `build/qa/reader-type-player/`。没有改动后端 API、文库文件或存储格式，无需迁移或备份用户数据。

真实 Android 验收报告为 `build/qa/android-player-refresh/findings.md`。模拟器临时数据已清理，字号/主题已恢复，模拟器与 adb 转发已关闭。本机 `build/qa/android-player-refresh/fixture-data/` 的递归清理被自动审批拒绝（仅返回 `blocked by policy`），因此保留这份合成测试素材；它不属于用户文库或程序备份。

产物：`dist/FujimiShinbunBunkoAndroid/FujimiShinbunBunkoAndroid-release.apk`，版本 1.0.13 / versionCode 14。

APK SHA-256：`7a01eb4caa3e725c7d5cb261e276f4e8e0f9f75e14e5c4b90fab2d74c561d561`。
