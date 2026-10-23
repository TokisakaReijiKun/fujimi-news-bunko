# Android 1.0.12 视觉与移动布局验收

版本：`1.0.12` / `versionCode 13`。沿用正式 `static/` 页面、六个 hash 路由与原生桥接，未更换框架。

## 变化

- 纸白、墨绿、浅绿的统一配色；标题、说明、正文与操作按钮使用一致的排版层级。夜间模式同步覆盖设置卡片、输入框、译文菜单、收藏与播放器。
- 默认手机顶栏从 112px 收紧为 92px，页面内边距统一为 16/20px；横屏顶栏为 72px。系统大字体下根据实际 WebView `textZoom` 增高。
- 日刊首篇增加轻量视觉强调；列表按钮与内容分区对齐。系列书与单本书使用相同的横向封面比例，单本书显示已有作者字段。
- 阅读室补充网址与粘贴两条现有操作的说明、可见标签。未增加新的业务操作。
- 修复词典例句朗读按钮越屏、关闭抽屉的阴影泄露，以及大字体下导航区域被品牌区和页脚挤压的问题。抽屉整体滚动，保留焦点管理与 Android 返回键。
- 原生窗口继续 edge-to-edge 绘制。`MainActivity` 将系统栏及刘海边距传给 CSS；不把软键盘高度当成底部安全区。Android 10 使用 stable insets，Android 11+ 使用 system bars / display cutout insets。
- 原生 Activity 根据系统夜间模式选择对应主题，让 WebView 的 `prefers-color-scheme` 与系统栏图标保持一致，修复原先固定浅色主题导致的夜间显示错误。

样式集中在 `static/static.css` 的 `Mobile reading edition` 区段。`--safe-area-*` 同时接受浏览器环境值与原生值，非 Android 页面保留浏览器行为。新增阅读室说明和作者文字只在移动布局显示。

## 验证

- `tests/verify_android_visual_refresh.cjs after`：375、390、812×390、1440px，明暗共 8 组，104 张截图，0 失败；覆盖六页面、阅读室空态、系列与书籍、词典详情、弹窗、抽屉焦点循环、排序保存、125% 根字号与减少动画。
- `tests/verify_android_frontend.cjs`：5 组通过，覆盖 Android 下拉、保存、返回、键盘操作及 Web/桌面原生选择框。
- `tests/verify_android_audio_ui.cjs`：3 组通过，覆盖任务位置、冷启动音频定位、段落边界和提示与播放器的避让。
- 实际 Android API 35 隔离模拟器：系统安全区上/下各 24px；130% 字体检查通过。200% 字体下日刊顶栏为 224px（含安全区），描述完整留在栏内；抽屉六入口可通过真实触摸滚动访问，弹窗与返回操作通过。
- 实际 Android 夜间模式：六个路由均确认 `prefers-color-scheme: dark` 生效；系统状态栏、页面与菜单显示正确，触摸和返回操作通过，0 JavaScript 异常。证据为 `build/qa/android-visual-native/dark-fixed-results.json`，不是浏览器模拟深色结果。
- 三个正式 JavaScript 文件与两个新增验收脚本语法检查、`git diff --check` 通过。Android debug/release 构建成功；核心测试报告为 93 项，0 失败/错误。
- Release APK 的六个正式 HTML/CSS/JS 资源与源码 SHA-256 一致，APK v2 签名验证通过。

浏览器验收使用合成内容和隔离 API；原生验收使用测试模拟器，没有执行真实日刊生成、翻译、同步或朗读生成。本次未迁移或修改用户文库，也未创建用户数据或程序备份。未连接实体手机；Android 10 的分支已编译，未单独运行 Android 10 模拟器。

## 产物

- 安装包：`dist/FujimiShinbunBunkoAndroid/FujimiShinbunBunkoAndroid-release.apk`
- 视觉报告与预览：`build/qa/android-visual-refresh/after/`
- 实际 WebView 截图与报告：`build/qa/android-visual-native/`
- 构建日志：`logs/android-visual-debug-build.log`、`logs/android-visual-release-build.log`
- APK SHA-256：`35570cbe3cc964dfb5b788b42fefc84cafd9ad1f7fa862d1384907012542dce2`

浏览器验收需要 Playwright 和本机 Edge。脚本全部使用正式资源，不以历史布局预览或样式 demo 作为验收入口。
