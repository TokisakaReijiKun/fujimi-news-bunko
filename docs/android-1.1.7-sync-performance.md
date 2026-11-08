# 1.1.7：按路径与大小增量同步

配对和内容合并沿用已有实现，传输改为先比较两端清单。清单记录文件相对路径与大小，不生成内容 fingerprint；未变化实体直接跳过，有变化时仅传缺失／不同大小的文件及控制元数据。同步包不再生成或验证 SHA 请求头、整包 SHA 或逐文件 SHA。入库也显式跳过对已有内容的重复哈希；新保存内容所需的存储元数据照常生成，普通阅读检查不变。

书籍章节的译文、假名和音频版本使用存在标记判断补齐；不因 PC 缩进 JSON 与 Android 紧凑 JSON 的字节大小不同而永久重复传包。增加声线版本时按路径补齐，保留本机主声线、阅读进度和已有内容。同路径同大小的文件按用户要求视为相同，不识别等长内容修改。

API 清单继续 version1，新增 `file_comparison: path-size-v1`、`files` 和书籍 `chapter_features`。POST `/api/sync/v2/pull` 接收目标 `known_files`；version2 ZIP 包用完整路径大小清单和 `included` 指明实际传输文件，省略文件从本机同实体复用。保留路径、登记、实际长度及格式边界；旧 version1 样本可导入，但不再比较其 SHA。手机与 PC 需要配套更新。

验证：最新 Python 全量 85 项、Android 核心 117 项通过；两个设备 HTTP 测试确认无 SHA 头下载与单次流式上传。API35 隔离模拟器通过正式 WebView 和原生同步接口完成连续四轮：

| 场景 | 内容包 | 内容传输量 | 实测耗时 |
| --- | --- | --- | --- |
| 首次接收 8 MiB 音频文章 | 下载 1 包 | 8,391,065 字节 | 1.323 秒 |
| 内容不变再次同步 | 0 包 | 0 字节 | 0.437 秒 |
| 新增 1 MiB 音频 | 下载 1 包 | 1,050,641 字节 | 1.301 秒 |
| 补齐后再次同步 | 0 包 | 0 字节 | 0.455 秒 |

这是本机隔离链路测试，未测量用户手机的 Tailscale 实际带宽。模拟器 `10.0.2.2` 转发路径在大包末尾提前断开；相同正式客户端通过 ADB reverse 的私网地址完成完整传输，没有放宽应用的地址或长度检查。测试中的旧故障样本 `QA-Unrelated-Damaged-Article` 已确认并从隔离模拟器删除，未接触用户文库。模拟器、反向映射和临时服务均已关闭。

Android 版本 1.1.7/code30，沿用既有签名与包名；26 项界面／词典资源与 1.1.6 完全一致。PC EXE 仅更新 `article_store`、`book_store`、`device_sync`、`example_store`、`library_sync`、`tts_service` 六个后端模块，其余 13,233 个模块及 10 个入口脚本的执行代码保留。未更新 PC 界面资源、复制模型、迁移或手工备份用户数据。

安装包：`dist/FujimiShinbunBunkoAndroid/FujimiShinbunBunkoAndroid-1.1.7-release.apk`。证据：`build/qa/sync-fast/performance.json`、`android-completed.png`、两端包核对 JSON；日志：`logs/sync-fast-*.log`。
