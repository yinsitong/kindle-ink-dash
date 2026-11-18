#!/bin/sh
# 启动看板循环（dash.sh）
#
# 顶部状态栏（左上角时间 + WiFi + 电池）由 Kindle 原生绘制，我们不自己画。
# 时间与电池由不同组件驱动，恢复手段不同（下方「状态栏恢复」段有实测对照表）。
#
# 顶部可能出现的三种坏状态：
#   A. 被 eips 贴图盖白      → 顶部一片白，深色像素≈0
#   B. 被屏保/壁纸盖住        → 顶部是灰阶图案，深色像素很多但底色不白，时间和电池看不见
#   C. 正常                 → 白底 + 少量深色文字/图标
#
# 所以判据必须同时看「有没有深色内容」和「底色是不是白的」，
# 只看深色像素数会把 B 误判成正常（实测壁纸覆盖时深色像素 21836，远超阈值）。
#
# 2026-11-18 修复：原版只判「深色像素 < 50」，导致壁纸覆盖时自愈不触发。
# 另外 preventScreenSaver 必须在修状态栏之前设置，否则系统可能先画屏保。
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# ① 最先关掉屏保，避免系统在修复过程中重新盖上来
lipc-set-prop com.lab126.powerd preventScreenSaver 1 2>/dev/null

pkill -f "/tmp/dash\.sh" 2>/dev/null
pkill evtest 2>/dev/null
rm -f /tmp/dash_touchflag /tmp/dash_stop

status powerd 2>/dev/null | grep -q running || start powerd
sleep 1

# /var 是 64MB tmpfs，满了会让 dd/eips 静默失败（画面上看不出原因）。
# 日志超过阈值就截断，并清掉历史抓屏残留。
cleanup_tmp() {
    for f in /tmp/dash_loop.log /tmp/battery.log; do
        [ -f "$f" ] || continue
        [ "$(wc -l < "$f" 2>/dev/null || echo 0)" -gt 300 ] || continue
        tail -200 "$f" > "$f.tmp" 2>/dev/null && mv "$f.tmp" "$f"
    done
    rm -f /var/tmp/*.bin /tmp/debug*.bin 2>/dev/null
    FREE=$(df -k /var 2>/dev/null | awk 'NR==2 {print $4}')
    case "$FREE" in ''|*[!0-9]*) return 0 ;; esac
    # 低于 8MB 时清理更多
    if [ "$FREE" -lt 8192 ]; then
        rm -f /tmp/*.bin /var/tmp/*.png /tmp/*.png.new 2>/dev/null
    fi
}
cleanup_tmp

# 采集顶部 90 行统计：输出 "左侧深色 右侧深色 均值"
#   左半 (x<500)   = 时间
#   右半 (x>=600)  = WiFi + 电池
# displayChrome 只能恢复时间，电池要靠 restart pillow 才画得出来，
# 所以必须分开检测，否则「时间回来了」会误判为完全正常、电池永远缺。
top_stats() {
    dd if=/dev/fb0 bs=1088 count=90 2>/dev/null \
        | od -An -v -tu1 -w1088 2>/dev/null \
        | awk '
            {
                for (i = 1; i <= NF; i++) {
                    n++; s += $i
                    if ($i < 128) {
                        d++
                        if (i <= 500) dl++; else if (i > 600) dr++
                    }
                }
            }
            END { printf "%d %d %d\n", dl + 0, dr + 0, (n > 0 ? s / n : 0) }
        '
}

# 状态栏完整：白底 + 左侧有时间 + 右侧有电池/WiFi
status_ok() {
    stats=$(top_stats)
    dl=$(echo "$stats" | awk '{print $1}')
    dr=$(echo "$stats" | awk '{print $2}')
    avg=$(echo "$stats" | awk '{print $3}')
    for v in "$dl" "$dr" "$avg"; do
        case "$v" in ''|*[!0-9]*) return 1 ;; esac
    done
    # 白底阈值 200：正常状态栏底色 252；壁纸覆盖时实测 113~149
    [ "$dl" -ge 40 ] && [ "$dr" -ge 40 ] && [ "$avg" -ge 200 ]
}

# 状态栏恢复（2026-11-18 逐条实测后的结论）
#
#   时间 ← pillowd 的时钟组件，每分钟自动刷新；被盖白后等一分钟会自己回来
#   电池 ← powerd 广播电量，pillowd 不主动重绘，**没有任何轻量方法能强制它出现**
#
# 实测各手段是否有效（从「顶部全白」状态出发）：
#   lipc-set-prop com.lab126.pillow displayChrome 1 ... ❌ 该固件属性类型不匹配，永远失败
#   initctl restart pillow ....................... ⚠️ 时间要等分钟跳变，电池仍缺
#   initctl restart powerd ....................... ✅ 时间和电池同时恢复（唯一可靠）
#
# 所以：只要状态栏不完整，就刷白顶部 + restart powerd 一条路走到底。
if ! status_ok; then
    # 顶部若被壁纸/屏保/涂色覆盖（底色不白），先刷白
    stats=$(top_stats)
    avg=$(echo "$stats" | awk '{print $3}')
    case "$avg" in ''|*[!0-9]*) avg=0 ;; esac
    if [ "$avg" -lt 200 ]; then
        eips -d l=fc,w=1072,h=100 -x 0 -y 0 >/dev/null 2>&1
        sleep 2
    fi

    # restart powerd：让 powerd 重新广播电量与电源状态，pillowd 随之重绘完整 chrome
    initctl restart powerd 2>/dev/null
    n=0
    while [ "$n" -lt 12 ]; do
        sleep 2
        n=$((n + 1))
        status_ok && break
    done

    # powerd 重启会重置防屏保属性，补回来
    lipc-set-prop com.lab126.powerd preventScreenSaver 1 2>/dev/null
    sleep 2
fi

echo "$(date) 状态栏自愈完成 stats=$(top_stats)" >> /tmp/dash_loop.log

cp /mnt/us/kindle-dash/dash.sh /tmp/dash.sh
cd /
setsid sh /tmp/dash.sh >> /tmp/dash_loop.log 2>&1 &
