#!/bin/sh
# 看板循环 v6：轮播 + 触摸翻页（顶部豁免）+ 电源键锁屏即退出
#
# 图床地址不在脚本里硬编码：从 /mnt/us/kindle-dash/config.sh 读取。
# 部署时写一行即可（IP 换成运行图床那台 Mac 的局域网地址）：
#   DASH_SERVER="http://192.168.1.23:8077/quota.png"
[ -f /mnt/us/kindle-dash/config.sh ] && . /mnt/us/kindle-dash/config.sh
if [ -z "${DASH_SERVER:-}" ]; then
    echo "$(date) 缺少 DASH_SERVER，见 /mnt/us/kindle-dash/config.sh"
    exit 1
fi
SERVER="$DASH_SERVER"
IMG=/tmp/quota.png
INTERVAL=300
TOUCH_TOP_ZONE=250
FLAG=/tmp/dash_touchflag
STOPF=/tmp/dash_stop
PW_DEV=/dev/input/event0
NIGHT_START=2100   # 21:00 起放睡
NIGHT_END=900      # 09:00 RTC 唤醒

T=$(grep -iA3 "zforce\|touch\|cyttsp\|ft5x06\|goodix\|elan" /proc/bus/input/devices 2>/dev/null | grep -o "event[0-9]*" | head -1)
TOUCHDEV="/dev/input/${T:-event1}"
echo "$(date) start: touch=$TOUCHDEV pwr=$PW_DEV interval=${INTERVAL}s"

draw() {
    BL=$(lipc-get-prop com.lab126.powerd battLevel 2>/dev/null)
    [ -n "$BL" ] && echo "$(date +%F_%H:%M) batt=$BL" >> /tmp/battery.log
    # 主图画到 y=100 以下：顶部 100px 留给 Kindle 原生状态栏（左上角时间）。
    # 从不覆盖那块区域，时间就会一直显示（墨水屏不刷新即保持）。
    if wget -q -T 15 -O "$IMG.new" "$SERVER" && [ -s "$IMG.new" ]; then
        mv "$IMG.new" "$IMG"
        eips -w gc16 -g "$IMG" -x 0 -y 100 >/dev/null 2>&1
    else
        rm -f "$IMG.new"
    fi
}

rm -f "$FLAG" "$STOPF"

# 触摸监听：中间区域抬起 → 翻页
( /mnt/us/usbnet/bin/evtest "$TOUCHDEV" 2>/dev/null | while read -r line; do
    case "$line" in
        *"ABS_MT_POSITION_Y"*"value"*) Y="${line##*value }" ;;
        *"ABS_Y"*"value"*) [ -z "$Y" ] && Y="${line##*value }" ;;
        *"BTN_TOUCH"*"value 0"*)
            if [ -n "$Y" ] && [ "$Y" -gt "$TOUCH_TOP_ZONE" ] 2>/dev/null; then : > "$FLAG"; fi
            Y="" ;;
    esac
done ) &

# 电源键监听：按下 → 停止旗标
( /mnt/us/usbnet/bin/evtest "$PW_DEV" 2>/dev/null | while read -r line; do
    case "$line" in
        *"KEY_POWER"*"value 1"*) : > "$STOPF" ;;
    esac
done ) &

# 退出并配合锁屏
cleanup_exit() {
    lipc-set-prop com.lab126.powerd preventScreenSaver 0 2>/dev/null
    pkill evtest 2>/dev/null
    echo "$(date +%H:%M:%S) 看板退出：$1"
    exit 0
}

wait_next() {
    i=0
    while [ $i -lt $INTERVAL ]; do
        if [ -f "$STOPF" ]; then
            # 电源键被按：先恢复正常电源管理，若系统没自己睡就帮它睡
            lipc-set-prop com.lab126.powerd preventScreenSaver 0 2>/dev/null
            sleep 2
            st=$(lipc-get-prop com.lab126.powerd state 2>/dev/null)
            [ "$st" = "active" ] && lipc-set-prop com.lab126.powerd powerButton 1 2>/dev/null
            cleanup_exit "电源键锁屏"
        fi
        [ -f "$FLAG" ] && { rm -f "$FLAG"; echo "$(date +%H:%M:%S) 触摸翻页"; return; }
        if [ $((i % 5)) -eq 4 ]; then
            st=$(lipc-get-prop com.lab126.powerd state 2>/dev/null)
            [ -n "$st" ] && [ "$st" != "active" ] && cleanup_exit "系统进入 $st"
        fi
        sleep 1; i=$((i+1))
    done
}

i=0
while [ $i -lt 6 ]; do
    [ -f "$STOPF" ] && cleanup_exit "电源键锁屏"
    draw
    i=$((i+1))
    sleep 10
done

night_sleep() {
    cur=$(date +%s)
    hh=$(date +%H | sed 's/^0*//'); mm=$(date +%M | sed 's/^0*//')
    [ -z "$hh" ] && hh=0; [ -z "$mm" ] && mm=0
    secs_today=$(( hh*3600 + mm*60 ))
    target=$(( 9*3600 ))
    if [ $secs_today -lt $target ]; then
        wake=$(( cur + target - secs_today ))
    else
        wake=$(( cur + 86400 - secs_today + target ))
    fi
    if [ -w /sys/class/rtc/rtc0/wakealarm ]; then
        echo 0 > /sys/class/rtc/rtc0/wakealarm 2>/dev/null
        echo "$wake" > /sys/class/rtc/rtc0/wakealarm 2>/dev/null
        echo "$(date +%F_%H:%M) 夜间放睡 → 09:00 RTC 唤醒 batt=$(lipc-get-prop com.lab126.powerd battLevel 2>/dev/null)" >> /tmp/battery.log
        lipc-set-prop com.lab126.powerd preventScreenSaver 0 2>/dev/null
        sleep 1
        lipc-set-prop com.lab126.powerd powerButton 1 2>/dev/null
        # 挂起期间进程冻结；唤醒（或没睡成）后每分钟查一次时间
        while true; do
            sleep 60
            HM=$(date +%H%M | sed 's/^0*//'); [ -z "$HM" ] && HM=0
            [ "$HM" -ge "$NIGHT_END" ] && [ "$HM" -lt "$NIGHT_START" ] && break
        done
        lipc-set-prop com.lab126.powerd preventScreenSaver 1 2>/dev/null
        echo "$(date +%F_%H:%M) 唤醒，看板恢复 batt=$(lipc-get-prop com.lab126.powerd battLevel 2>/dev/null)" >> /tmp/battery.log
    else
        sleep 600   # RTC 不可用：退化为 10 分钟后再查
    fi
}

while true; do
    HM=$(date +%H%M | sed 's/^0*//'); [ -z "$HM" ] && HM=0
    if [ "$HM" -ge "$NIGHT_START" ] || [ "$HM" -lt "$NIGHT_END" ]; then
        night_sleep
    fi
    draw
    wait_next
done
