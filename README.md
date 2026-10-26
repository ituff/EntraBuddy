<div align="center">

# EntraBuddy

**排查 Microsoft Entra ID 身份问题的本地工具（macOS & Windows）**

看清这台机器到底登录了哪些微软账户、被哪些应用持有、注册到了哪个租户。

[![Platform](https://img.shields.io/badge/platform-macOS%2011%2B%20%7C%20Windows%2010%2B-lightgrey)](#)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](#)
[![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)](#)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

<img src="docs/accounts.png" alt="账户总览" width="880" />

</div>

## 它解决什么问题

排查 Entra ID 相关的登录问题时，最费时间的往往不是修复，而是**搞清楚现状**：

- Office 一直弹登录框，可明明已经登录了——到底是哪个账户在生效？
- 这台机器到底注册到哪个租户了？为什么 Intune 推不下来策略？
- 换过公司之后，旧的租户身份是不是还留在本地？
- 用户说是「用公司账号登录的」，但许可证为什么显示是个人订阅？

两个平台把答案分散在同样的几类存储里——OneAuth 身份库、Office 许可缓存、Edge 配置文件、
OneDrive 账户、系统 MDM 状态——但位置和格式完全不同，而且大多没有官方查看工具。

EntraBuddy 把这些信息汇总成一张可读的视图，并且**只读本地文件与注册表、不碰任何凭据**。

## 功能

### 账户清点

区分企业账户（OrgId）与个人账户（MSA），识别国际版与世纪互联（21Vianet）云，展示租户名、租户 ID、对象 ID、CID 与最后活跃时间。

### 应用关联

回答「谁在用它、以什么身份用」。每个账户会标注它在各应用中的角色：

| 角色 | 含义 |
|------|------|
| 当前登录 | 应用正在使用的身份 |
| 许可证 | 授权该应用订阅的账户 |
| 同步账户 | OneDrive 等同步客户端绑定 |
| 浏览器配置 | Edge 配置文件登录态 |
| 身份缓存 | 仅存在于本地缓存，未在使用 |
| 设备策略 | 与 MDM / 端点防护关联 |

这一步经常能直接定位问题：**Office 以工作账户登录、许可证却来自个人订阅**，就是典型的混合身份故障。

### 设备与合规自检

设备身份、Entra ID 注册状态、MDM 注册、传统 AD，外加七项本地可验证的合规信号——

- macOS：FileVault / SIP / 防火墙 / 系统版本 / 端点防护等
- Windows：BitLocker / 防火墙 / 系统版本 / Defender 载入 / SmartScreen 等

严格区分「不合规」与「无法判定」——读不到就明说读不到，不猜。例如 BitLocker 状态在
非管理员下读不到时，会标成「无法判定：需要管理员权限」，而不是误报不合规。

### 变更追踪

每次扫描自动记录快照，对比出新增、消失、变化的账户。排查「昨天还好好的」这类问题时特别有用。

### 备份式清理

残留的身份缓存可以清理，但**先备份再删**：文件复制到本机数据目录
（macOS `~/Library/Application Support/EntraBuddy/backups`，Windows
`%LOCALAPPDATA%\EntraBuddy\backups`）并逐个校验大小，任一失败整体中止。
支持单账户与批量，可一键回滚。

## 快速开始

### 浏览器模式

```bash
# macOS
./run.sh                 # http://127.0.0.1:8765
./run.sh --port 9000
```

```bat
:: Windows
run.cmd
run.cmd --port 9000
```

后端零第三方依赖，只用 Python 标准库。

### 演示模式

```bash
./run.sh --demo          # 或 run.cmd --demo
```

用虚构账户渲染完整界面，所有写操作自动禁用。

### macOS 原生应用（Apple Silicon）

从 [Releases](https://github.com/ituff/EntraBuddy/releases) 下载，或源码构建：

```bash
./desktop/build_app.sh   # 产出 dist/EntraBuddy.app，内置 Python + PyObjC
```

原生窗口（PyObjC + WKWebView），启动时自动拉起本地服务并分配随机端口，退出时自动关闭。

### Windows 桌面模式（可选）

```bat
pip install pywebview
python desktop_win.py    :: pywebview + WebView2 原生窗口
pip install pyinstaller pywebview
desktop\build_app.cmd    :: 产出 dist\EntraBuddy.exe 单文件
```

### 发布（自动构建双平台）

仓库内置 GitHub Actions（`.github/workflows/release.yml`）。推送版本标签即自动在
macOS 与 Windows 两个 runner 上分别构建，并把产物挂到同一个 Release：

```bash
git tag v0.3.0
git push origin v0.3.0
# → EntraBuddy-v0.3.0-macos-arm64.zip（.app）
# → EntraBuddy-v0.3.0-windows-x64.zip（单文件 exe）
```

也可以在 Actions 页面手动触发（workflow_dispatch）做构建演练。注意两种产物都不能
交叉编译：.app 需要打包 macOS 的 Python 运行时，exe 依赖 PyInstaller，必须各自在
对应系统上构建，CI 的双 runner 正是为此。macOS 产物为临时签名（ad-hoc），正式分发
仍需开发者证书签名与公证；Windows exe 未做代码签名，SmartScreen 可能提示。

## 工作原理

两个平台扫描同一套语义的数据，实现层完全不同：

| 数据 | macOS | Windows |
|------|-------|---------|
| OneAuth 身份库 | `~/Library/Group Containers/UBF8T346G9.com.microsoft.oneauth/BlobStore/` | `%LOCALAPPDATA%\Microsoft\OneAuth\blobs\`（同一套库，结构一致） |
| Office 当前身份 | `defaults read com.microsoft.office`（OCPS-LastSuccessfulUserId） | 注册表 `Common\Identity\ConnectedOneAuthAccountId` |
| Office 许可证 | `~/Library/Group Containers/UBF8T346G9.Office/Licenses/` | `%LOCALAPPDATA%\Microsoft\Office\Licenses\`（同一 JSON 格式） |
| Edge | `~/Library/Application Support/Microsoft Edge/` | `%LOCALAPPDATA%\Microsoft\Edge\User Data\`（同一 Chromium 结构） |
| OneDrive | `UBF8T346G9.OneDriveSyncClientSuite.plist` | 注册表 `HKCU\...\OneDrive\Accounts\<slot>` |
| 设备注册 | Company Portal 容器 + 钥匙串证书（启发式） | `dsregcmd /status`（直接给出 AzureAdJoined 结论） |
| MDM | `profiles status` | 注册表 `HKLM\...\Enrollments` |
| 磁盘加密 | `fdesetup`（FileVault） | `manage-bde`（BitLocker） |
| 端点防护 | `mdatp health` | 注册表 Defender ATP `OrgId` |

### 跨平台移植时的关键发现

**OneAuth 是跨平台同一套库。** Windows 上 `%LOCALAPPDATA%\Microsoft\OneAuth\blobs\` 的
blob 命名与 JSON 结构和 macOS 的 `BlobStore` 完全一致（`*_identity_provider`、
`*_graph_organization`、`*_hrd`），解析与 objectId 推断逻辑共用一份代码。

**OrgId 账户的 objectId 推断。** OneAuth 的 blob 前缀对 OrgId 账户是用户的 `objectId`，
不是 `tenantId`，而且没有 UPN → objectId 的映射表。按「租户显示名 ↔ 邮箱域名」归一化匹配
（`Fabrikam Inc` ↔ `fabrikam.com`），时间戳只做平局裁决，并输出置信度。

**MSA 的三种 ID 是同一个值。** OneAuth accountId = Edge `gaia_id`/`user_name` 对应的
cid = OneDrive `cid`（16 位 hex），可以互相交叉验证。

**OneDrive 企业版的 `cid` 实为 objectId（Windows）。** 注册表 `Accounts\Business1` 的
`cid` 值是该账户在租户内的 objectId（GUID）；映射到 `object_id` 而不是 `cid`，避免与
许可证 CID 交叉匹配串线。

**Office 许可证文件格式跨平台一致。** Windows 的许可证文件同样是 UTF-16LE 的
`{"License":"<base64>"}` JSON，令牌解码逻辑共用。

## 安全与隐私

- **不读取凭据。** 令牌缓存是加密的，工具只解析账户元数据，不接触 access token / refresh token
- **不出网。** 服务只监听 `127.0.0.1`，没有任何远程请求
- **写操作有护栏。** 需要自定义请求头（跨站请求无法伪造），清理前强制备份并校验，清单变化则要求重新确认
- **清理范围受限。** 只在 OneAuth 目录内、只匹配该账户的白名单前缀、拒绝符号链接与路径穿越

## 适用与不适用

**适合**

- 排查本机上 Office / Teams / Edge / OneDrive 的账户身份混乱
- 确认设备是否注册到 Entra ID、是否受 MDM 管理
- 清理离职或换租户后残留的身份缓存

**不适合**

- 读取或导出令牌内容（设计上就不做）
- 替代 Intune 的合规判定（那需要 Graph 授权）

## 开发

```
app.py                    HTTP 服务、路由、写操作护栏（共享）
desktop_mac.py            PyObjC + WKWebView 桌面壳
desktop_win.py            pywebview + WebView2 桌面壳
entrabuddy/
  _platform.py            平台识别
  scan.py                 编排：合并来源、建立关联、生成洞察（共享）
  cleanup.py              备份 / 删除 / 回滚（共享）
  snapshots.py            快照与 diff（共享）
  demo.py                 演示数据（结构共享，设备块按平台）
  util.py                 路径 / defaults / 注册表 / 安全读取
  collectors/
    __init__.py           平台分派：office/onedrive/environment/device 按 *_mac/*_win 选择
    oneauth.py            OneAuth 身份库（双平台共享，仅根路径不同）
    edge.py               Edge 配置文件（双平台共享）
    office_mac.py         Office 身份（defaults）与许可证
    office_win.py         Office 身份（注册表）与许可证
    onedrive_mac.py       OneDrive plist
    onedrive_win.py       OneDrive 注册表
    environment_mac.py    已装应用 / MDM / Defender（macOS）
    environment_win.py    已装应用 / MDM / Defender（Windows）
    device_mac.py         设备身份、注册状态、合规信号（macOS）
    device_win.py         dsregcmd、设备身份、合规信号（Windows）
web/                      GUI（原生 JS，无构建步骤，文案随 platform 字段切换）
tests/                    清理流程隔离测试
desktop/build_app.sh      macOS .app 打包
desktop/build_app.cmd     Windows exe 打包
```

平台分派只发生在采集器层：新增平台支持时加一组 `*_xxx.py` 采集器并在
`collectors/__init__.py` 登记即可，编排与 UI 不需要任何 `if`。

```bash
python tests/test_cleanup.py
```

测试在临时目录里跑完整的 计划 → 备份 → 删除 → 恢复，覆盖单账户与批量两条路径，与平台无关。

## 路线图

- [ ] 令牌细节：解析可读 JWT 声明，展示实际过期时间
- [ ] Graph 集成：读取真实的 Intune 合规结论与设备对象
- [ ] 导出：账户与应用关联导出为 CSV / JSON，便于审计留档
- [ ] 分发：macOS 签名公证；Windows 图标与安装包

## 许可

[MIT](LICENSE)

---

<div align="center">
<sub>本项目与 Microsoft 无关联，未获其背书。Microsoft、Entra ID、Microsoft 365 是 Microsoft Corporation 的商标。</sub>
</div>
