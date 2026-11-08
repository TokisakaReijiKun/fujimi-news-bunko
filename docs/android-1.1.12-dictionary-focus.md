# 1.1.12：去掉辞书输入区内层聚焦方框

仅调整手机辞书首页搜索框：移除文字输入区域继承的 3px 聚焦轮廓；聚焦时改用现有圆角搜索框的单层边线变色保留焦点提示。搜索框尺寸、搜索图标、提交按钮及历史记录保持原样。

375／390px 隔离页面检查通过，确认内层 outline 和 box-shadow 为 none，历史记录可打开、删除，输入框位置尺寸不变，无横向溢出或 JavaScript 错误。1440px PC 辞书聚焦样式及布局与 1.1.11 对照一致。没有连接手机或实际文库。

Release 构建、版本 code35／1.1.12 及同证书签名检查通过。core 测试任务使用现有通过结果（UP-TO-DATE），未重复运行。以正式 1.1.11 APK 为基线，仅替换 mobile-reader.css 和 index.html 的手机样式缓存版本；26 项界面／词典资源与已检查的打包输入一致，原生 DEX 和词典逐字节不变。未更新 PC 客户端、改写文库、迁移或创建备份。

安装包：`dist/FujimiShinbunBunkoAndroid/FujimiShinbunBunkoAndroid-1.1.12-release.apk`，可覆盖安装。73,670,470 字节，SHA-256 `1cc096105478899e97a1ea194cb8ceb255f7a701acaf8a6b8ab1db0769916e1a`。检查证据位于 `build/qa/mobile-app-1.1.12/`。
