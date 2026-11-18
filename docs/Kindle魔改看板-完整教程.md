# 闲置 Kindle 魔改墨水屏看板 · 完整教程

> 把一台闲置 Kindle（本文以国行 Kindle Paperwhite 3 为例）越狱后改造成常显信息看板。
> 示例场景：每 5 分钟显示 DeepSeek 余额 + Kimi 配额，但架构通用——换个渲染脚本就能显示天气、日历、股票、任何内容。
> 全程实测于 2026-08，macOS + 国行 PW3（固件 5.16.2.1.1），中国大陆网络环境。

## 最终效果与架构

```text
Mac（与 Kindle 同一局域网）
├─ launchd 定时渲染（每 5 分钟）：查数据 → 渲染 1072×1448 PNG
├─ launchd 看门狗（每 1 分钟）：ping 得通 Kindle 才起 HTTP 服务，否则自动关闭
└─ Kindle 端：图书馆里一本「Kindle-Dash」的书，点开即启动看板循环
     → 防休眠 → 每 5 分钟从 Mac 拉图 → eips 全屏刷新
```

- 刷新静默、每帧全刷防残影；误触屏幕 5 分钟内自动恢复
- 查询走账户信息接口，**零 API 费用**
- Mac 离开局域网服务自动关闭，回来自动恢复

---

## 材料清单

| 项 | 说明 |
|---|---|
| Kindle | Paperwhite 3（其他型号见文末适配说明），**固件 ≤ 5.16.2.1.1** |
| 数据线 | ⚠️ 必须是**能传数据**的 micro-USB 线（很多线只能充电！） |
| Mac/PC | 用于越狱操作和当看板的"服务器" |
| 网络 | Kindle 和电脑同一局域网 |
| 文件包 | 本文配套：`wb2_server.py`、`kindle_quota_render.py`、`serve.py`、`dash.sh`、`Kindle-Dash.sh` |

> **先开飞行模式防止自动更新**（固件 > 5.16.2.1.1 会被封堵）。PW3 用户可以放心：它的最终固件就是 5.16.2.1.1，永远不会再更新。

---

## 第一步：越狱（WinterBreak2，约 20 分钟）

> 为什么不用更出名的 WinterBreak？它依赖 Kindle 商店机制，而**国行设备的亚马逊中国书店已关闭，没有商店入口**。WinterBreak2 走体验版浏览器，不需要商店、甚至不需要注册亚马逊账号。

### 1.1 准备

1. **恢复出厂设置**（设置 → 设备选项 → 重置），走完初始设置（登录或跳过注册均可）
2. 下载 WinterBreak2：`https://github.com/KindleModding/WinterBreak2/releases/latest` 的 `wb2.zip`
3. USB 连电脑，把 wb2.zip 解压出的 **`jb.sh`、`patchedUks.sqsh`、`winterbreak2/`** 三个拷到 Kindle 根目录，安全弹出

### 1.2 解决大陆网络问题（关键）

官方流程要在 Kindle 浏览器访问 `https://winterbreak2.now.sh/`，它会 308 跳到 `winterbreak2.vercel.app`——**vercel 在大陆不可达**，而且 Kindle 的上古浏览器连 308 跳转都不会跟。

解法：在自己的电脑上跑一个本地镜像（配套文件 `wb2_server.py`）：

```bash
python3 wb2_server.py   # 监听 :8078，复刻官方页面和 payload 响应
```

原理：这个"越狱页面"的 payload 其实藏在 `Content-Disposition` 响应头的文件名里（一段 XSS 脚本，触发 Kindle 内部的 pillow 对话框机制执行本地 jb.sh），所以本地镜像和官方完全等价。

### 1.3 触发

1. Kindle 连上 WiFi（这次要联网，但只需能访问你的电脑）
2. ⋮ 菜单 → **网页浏览器**，访问 `http://<电脑局域网IP>:8078/`（注意是 http）
3. 点 **Jailbreak** → 会"下载"一个 mobi → 弹出对话框执行越狱 → 屏幕打印越狱日志，看到 `Finished installing jailbreak!` 即成
4. **立刻开飞行模式**

### 1.4 固化（必做，否则重启丢越狱）

1. 下载 Hotfix：`https://github.com/KindleModding/Hotfix/releases/latest/download/Update_hotfix_universal.bin`
2. USB 拷到 Kindle 根目录（确保根目录没有其他 .bin / update.bin.tmp.partial）
3. 设置 → ⋮ → **更新您的 Kindle** → Update（会走"系统更新"流程）
4. 完成后去**图书馆**找到「Run Hotfix」这本"书"，打开运行一次

> 💡 过程中可能弹 "Collecting Debug Info / Raise A BUG" 的崩溃收集窗——这是越狱开启的开发者调试旗标的副作用，**一律选「关闭」**（Raise A BUG 会把日志上传亚马逊）。图书馆里多出 CVM、KPPMainAppV2 之类的"书"也是同一原因，无视即可。

---

## 第二步：部署看板

### 2.1 电脑端（以 macOS 为例）

```bash
# 1. 渲染脚本：查数据 → PNG（示例是模型额度，自行改写 render() 可显示任何内容）
export DEEPSEEK_API_KEY=xxx KIMI_CODING_API_KEY=xxx
python3 kindle_quota_render.py --out ~/.kindle-dash/quota.png

# 2. 起图床服务（防缓存，监听 :8077）
cd ~/.kindle-dash && python3 serve.py

# 3. 定时渲染 + 看门狗（launchd，配置见文末附录）
```

配套 launchd 配置实现两个自动化：
- 每 5 分钟渲染一次（**ping 不通 Kindle 就跳过**）
- 每分钟看门狗：**ping 得通 Kindle 才拉起 8077 服务，不通就关掉**——电脑离开局域网自动停摆

### 2.2 Kindle 端

越狱 + Hotfix 之后，系统支持一种 **scriptlet 机制**：`documents/` 里的 `.sh` 文件会像书一样出现在图书馆，点开即以 root 执行（Run Hotfix 就是这个原理）。我们用它做启动器，**不需要 KUAL**。

1. USB 拷入两个文件：
   - `Kindle-Dash.sh` → `documents/`（启动器，图书馆里显示为「Kindle-Dash」）
   - `dash.sh` → `kindle-dash/`（看板循环；**记得先把里面的 `SERVER=` 改成你电脑的局域网 IP**）
2. 弹出，收工

### 2.3 启动 / 关闭

- **启动**：图书馆 → 点开「Kindle-Dash」→ 约 1 分钟内屏幕每 10 秒闪一次（抢屏阶段，压住系统界面的延迟重绘）→ 看板稳定显示
- **关闭**：重启 Kindle（墨水屏会残留最后一帧画面，不是故障，下次启动看板全刷即清）

---

## 踩坑 FAQ（全是实测血泪）

**Q：插 USB 电脑完全看不到 Kindle？**
A：99% 是线只能充电不能传数据，换线。Kindle 不需要任何设置，连接成功会自动进入 U 盘模式。

**Q：「更新您的 Kindle」是灰色的？**
A：三种可能：根目录没有合法 .bin；电量过低（<25% 禁用更新）；包被系统判定无效后自动删了（重拷一次再立刻刷）。

**Q：图书馆里多出很多奇怪的"书"（CVM / KPPMainAppV2 / 各种 crash 文件）？**
A：越狱调试旗标把内部应用和崩溃转储暴露出来了。连接 USB 删掉 `documents/` 里 `*_crash_*` 的文件即可，无害。

**Q：看板启动后卡死、弹"是否上报 Bug"？**
A：你在脚本里 `stop framework` 了。框架一停，系统进程崩溃 + 调试弹窗无人处理 = 卡死。**只 `stop powerd`**，框架保持运行。

**Q：看板在跑，但 Kindle 插 USB 进不了 U 盘模式？**
A：循环脚本/日志占用了 U 盘分区（/mnt/us）。把循环脚本拷到 `/tmp` 运行、日志写 `/tmp`（配套的 Kindle-Dash.sh 已处理）。

**Q：点屏幕顶部，菜单盖住看板不恢复？**
A：用 `eips -f`（全刷）而不是局部刷新，且循环要在后台独立运行（setsid），不依赖"书"的前台状态。

**Q：重启后看板还在屏上？**
A：墨水屏断电保持画面，是特性不是 bug。系统正常运行后会被覆盖。

**Q：KUAL 装了但扩展点了没反应？**
A：实测 PW3 + 5.16.2.1.1 上 KUAL 菜单能显示扩展但 action 不执行（原因未查明）。scriptlet 册子机制更可靠，本教程不依赖 KUAL。

---

## 适配其他 Kindle 型号

- **固件 ≤ 5.16.2.1.1 的非国行机**：可用原版 WinterBreak（商店方案），或直接 WinterBreak2
- **固件 5.16.4 – 5.18.0.2**：用 WinterBreak；**5.18.1+**：用 AdBreak
- **更老设备**（PW2/KT2/KV 等，固件 5.10.3–5.13.3）：KindleBreak
- 权威指南：`https://kindlemodding.org`
- 屏幕分辨率不同的话，改渲染脚本里的 `W, H`（PW3 = 1072×1448，PW4/PW5 = 1072×1448，Kindle 基础款多为 600×800/758×1024）

## 附录：launchd 配置（macOS）

`~/Library/LaunchAgents/com.proma.kindle-quota-render.plist`（每 5 分钟渲染，Kindle 不在网则跳过）：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.proma.kindle-quota-render</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string><string>-c</string>
    <string>ping -c 1 -t 2 KINDLE_IP >/dev/null 2>&1 || exit 0;
      exec /path/to/python3 /path/to/kindle_quota_render.py --out ~/.kindle-dash/quota.png</string>
  </array>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
</dict></plist>
```

`~/Library/LaunchAgents/com.proma.kindle-dash-watchdog.plist`（每分钟看门狗）：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.proma.kindle-dash-watchdog</string>
  <key>ProgramArguments</key>
  <array><string>/bin/sh</string><string>/Users/YOU/.kindle-dash/watchdog.sh</string></array>
  <key>StartInterval</key><integer>60</integer>
  <key>RunAtLoad</key><true/>
</dict></plist>
```

`~/.kindle-dash/watchdog.sh`：

```sh
#!/bin/sh
if ping -c 1 -t 2 KINDLE_IP >/dev/null 2>&1; then
    pgrep -f "kindle-dash/serve.py" >/dev/null 2>&1 && exit 0
    cd ~/.kindle-dash && nohup python3 serve.py >/dev/null 2>&1 &
else
    pkill -f "kindle-dash/serve.py" 2>/dev/null
fi
```

加载：`launchctl load ~/Library/LaunchAgents/com.proma.kindle-*.plist`

> 建议把 Kindle 的 IP 在路由器里绑定固定（DHCP 静态租约），否则 IP 变了要同步改脚本。
