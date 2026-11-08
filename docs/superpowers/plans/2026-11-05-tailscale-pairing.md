# Tailscale 配对联动 Implementation Plan

**Goal:** 用户开启配对即可连接已安装的 Tailscale，并用同一配对流程在两端互连。
**Architecture:** 可注入 CLI 连接器提供经过验证的 Tailscale 状态与地址；DeviceSync 只在该地址开放专用同步服务。Android 沿用既有网络和配对模块，仅扩充合法地址范围。
**Tech Stack:** Python/Flask/PyWebView，原生 HTML/CSS/JavaScript，Android Kotlin。
**Spec:** ../specs/2026-11-05-tailscale-pairing-design.md

## 约束

- 不执行本机网络连接、登录或跨网验收；离线检查与构建。
- 不监听 0.0.0.0，不关闭或重置 Tailscale，不修改账号/DNS/路由偏好。
- 关闭配对仅撤销本应用的监听及凭据。
- 不改用户内容或创建备份；继续复用 PC 安装目录和 APK 签名。

## 步骤

- [x] Android 私网地址策略增补 Tailscale CIDR，二维码与手动输入共用；离线边界与核心回归。
- [x] 新增独立 CLI 连接器：发现、复用 Running、启动/连接、待登录和超时错误；mock 回归。
- [x] PC 同步服务接入连接器与合法远端限制，保留原局域网路径；mock API／配对回归。
- [x] 设置界面显示准备中、Tailscale 地址、待登录与错误，保持六位码和现有布局；离线边界检查。
- [x] 离线 Python 回归、语法检查、Android 和 PC 构建，核验签名和资源。
- [x] 在确认任务空闲后原位更新 PC；不启动新实例、不触发 Tailscale；交付 APK 与使用说明。
