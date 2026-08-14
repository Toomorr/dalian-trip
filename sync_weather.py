#!/usr/bin/env python3
"""大连·沙河口区天气预报同步脚本（由 GitHub Actions 每小时触发）。

主数据源：中国天气网 weather.com.cn（中央气象台/中国气象局官方公众服务），
沙河口区代码 101070210（对应酒店所在地：西安路/联合路一带），
公开接口最细粒度为"逐 3 小时"（每天 8 个时次）。

可选对照：Open-Meteo（ECMWF/ICON 国际模型，逐 2 小时步长）——
默认开启并在文档中用"附注"独立呈现，标注非官方；可在下方开关关闭。

输出：
- 大连天气-2小时预报.md   每次运行整体覆盖（主表为中央气象台逐3小时）
- 大连天气-同步日志.md     追加每次运行记录（时间/状态/24h 摘要）

触发方式：.github/workflows/weather-sync.yml 的 schedule 每 5 分钟执行一次，
由 GitHub Actions 提交回仓库；本机不依赖 launchd/crontab。
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener, urlopen

BASE_DIR = Path(__file__).resolve().parent
OUT_MD = BASE_DIR / "大连天气-2小时预报.md"
LOG_MD = BASE_DIR / "大连天气-同步日志.md"

# 中国天气网（中央气象台）大连·沙河口区代码（酒店所在区，101070210）
CMA_CITY_ID = "101070210"
CITY_NAME = "大连·沙河口区（西安路/联合路酒店）"
# 是否附带国际模型（Open-Meteo）对照：True=附注显示差异；False=只保留中央气象台
INCLUDE_COMPARISON = True

LAT, LON = 38.9140, 121.6147
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
# 代理仅当环境变量显式设置时启用（本机可经 HTTP_PROXY 走本地代理；
# GitHub Actions 无此变量，直连官方接口）
_PROXY = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
_OPENER = (
    build_opener(ProxyHandler({"http": _PROXY, "https": _PROXY}))
    if _PROXY
    else build_opener()
)

TRIP_DAYS = {
    "2026-08-14": "D0 抵达夜（22:14 到大连北）",
    "2026-08-15": "D1 南海岸线（晴/雨双案）",
    "2026-08-16": "D2 日出+休整+小平岛海钓",
    "2026-08-17": "D3 东海岸+赶海",
    "2026-08-18": "D4 东港+早市+索道+逛街",
    "2026-08-19": "D5 南山路+返程（13:58 大连北）",
}


def http_get(url: str, referer: str | None = None, timeout: int = 20) -> str:
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    req = Request(url, headers=headers)
    with _OPENER.open(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def extract_js_object(text: str, marker: str) -> dict:
    """从 `var xxx={...}` 中按花括号配平提取 JSON 对象。"""
    start = text.find("{", text.find(marker))
    if start < 0:
        raise RuntimeError(f"{marker} 未找到")
    depth = 0
    in_str = False
    esc = False
    for j in range(start, len(text)):
        c = text[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : j + 1])
    raise RuntimeError(f"{marker} JSON 不完整")


def fetch_cma() -> tuple[dict, dict]:
    """返回 (hour3data, 实况 dataSK)。"""
    html = http_get(
        f"https://www.weather.com.cn/weather1d/{CMA_CITY_ID}.shtml",
        referer="http://www.weather.com.cn/",
    )
    hour3 = extract_js_object(html, "var hour3data=")

    js = http_get(
        f"http://d1.weather.com.cn/weather_index/{CMA_CITY_ID}.html"
        f"?_={int(time.time() * 1000)}",
        referer="http://www.weather.com.cn/",
    )
    try:
        sk = extract_js_object(js, "var dataSK=")
    except RuntimeError:
        sk = {}
    return hour3, sk


def fetch_openmeteo() -> dict:
    params = {
        "latitude": LAT,
        "longitude": LON,
        "hourly": (
            "temperature_2m,apparent_temperature,precipitation_probability,"
            "precipitation,weather_code,wind_speed_10m"
        ),
        "timezone": "Asia/Shanghai",
        "forecast_days": 7,
        "past_days": 1,
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urlencode(params)
    req = Request(url, headers={"User-Agent": "dalian-trip-weather-sync/1.0"})
    with _OPENER.open(req, timeout=25) as resp:
        return json.load(resp)


def parse_cma_entries(hour3: dict) -> dict[str, list[tuple[int, str, float, str, str]]]:
    """解析 hour3data['7d']，按日期分组。
    每条：'14日08时,d01,多云,26℃,东北风,4-5级,2'
    """
    now = datetime.now()
    month = now.month
    out: dict[str, list] = {}
    for block in hour3.get("7d", []):
        for item in block:
            parts = item.split(",")
            if len(parts) < 6:
                continue
            md = re.match(r"(\d+)日(\d+)时", parts[0])
            if not md:
                continue
            day, hour = int(md.group(1)), int(md.group(2))
            m = month if day >= now.day else month + 1
            date = f"{now.year:04d}-{m:02d}-{day:02d}"
            desc = parts[2]
            temp = float(re.sub(r"[^0-9.\-]", "", parts[3]))
            out.setdefault(date, []).append(
                (hour, desc, temp, parts[4], parts[5])
            )
    return out


def is_rain(desc: str) -> bool:
    return any(k in desc for k in ("雨", "雪", "雷", "冰雹"))


def build_md(
    hour3: dict,
    sk: dict,
    om: dict | None,
    now: datetime,
) -> str:
    lines = []
    lines.append("# 大连（沙河口区）天气预报 · 中国天气网 / 中央气象台")
    lines.append("")
    lines.append(
        f"- 更新时间：{now:%Y-%m-%d %H:%M}"
        "（GitHub Actions 每 5 分钟自动同步）"
    )
    lines.append(
        "- 数据来源：中国天气网 weather.com.cn"
        "（中央气象台 / 中国气象局官方公众服务），"
        f"大连·沙河口区代码 {CMA_CITY_ID}（对应酒店：西安路/联合路一带）"
    )
    lines.append(
        "- 粒度说明：官方公开接口最细为**逐 3 小时**"
        "（每天约 8 个时次：02/05/08/11/14/17/20/23 时）；"
        "中央气象台不提供 2 小时间隔的公开点预报，故主表按 3 小时展示"
    )
    if sk:
        lines.append(
            f"- 当前实况：{sk.get('weather', '—')} "
            f"{sk.get('temp', '—')}℃，{sk.get('WD', '—')}{sk.get('WS', '')}，"
            f"湿度 {sk.get('SD', '—')}，AQI {sk.get('aqi', '—')}"
            f"（{sk.get('time', '')}）"
        )
    lines.append("")

    by_day = parse_cma_entries(hour3)

    lines.append("## 行程对照（以中央气象台为准）")
    lines.append("")
    lines.append("| 日期 | 行程 | 当天预报概要 |")
    lines.append("|---|---|---|")
    for date in sorted(by_day):
        entries = by_day[date]
        rains = [h for h, d, _t, _wd, _ws in entries if is_rain(d)]
        temps = [t for _h, _d, t, _wd, _ws in entries]
        summary = (
            f"降雨时段：{'/'.join(f'{h:02d}时' for h in rains)}"
            if rains
            else "无明显降雨"
        )
        t_range = f"{min(temps):.0f}~{max(temps):.0f}℃"
        label = TRIP_DAYS.get(date, date)
        lines.append(f"| {date} | {label} | {summary}，{t_range} |")
    lines.append("")

    lines.append("## 未来 7 天逐 3 小时预报（中央气象台）")
    lines.append("")
    for date in sorted(by_day):
        label = TRIP_DAYS.get(date, "")
        head = f"### {date}"
        if label:
            head += " · " + label.split("（")[0]
        lines.append(head)
        lines.append("")
        lines.append("| 时间 | 天气 | 温度 | 风向 | 风力 |")
        lines.append("|---|---|---|---|---|")
        for hour, desc, temp, wd, ws in sorted(by_day[date]):
            mark = " 🌧" if is_rain(desc) else ""
            lines.append(
                f"| {hour:02d}:00 | {desc}{mark} | {temp:.0f}℃ | {wd} | {ws} |"
            )
        lines.append("")

    if INCLUDE_COMPARISON and om:
        lines.append("## 附注：国际模型对照（Open-Meteo，非官方，仅供参考）")
        lines.append("")
        lines.append(
            "> 中央气象台与中国天气网为官方数据；Open-Meteo 为 ECMWF/ICON "
            "国际模型。两者存在差异属正常，**以中央气象台为准**。"
            "若不需要对照，将脚本顶部 `INCLUDE_COMPARISON` 改为 False。"
        )
        lines.append("")
        lines.append("| 日期 | 中央气象台概要 | Open-Meteo 概要 |")
        lines.append("|---|---|---|")
        om_h = om["hourly"]
        om_by_day: dict[str, list] = {}
        for i, t in enumerate(om_h["time"]):
            om_by_day.setdefault(t[:10], []).append(i)
        for date in sorted(by_day):
            cma_entries = by_day[date]
            cma_rain = any(is_rain(d) for _h, d, _t, _wd, _ws in cma_entries)
            cma_temps = [t for _h, _d, t, _wd, _ws in cma_entries]
            cma_s = ("有雨时段" if cma_rain else "无明显降雨") + (
                f"，{min(cma_temps):.0f}~{max(cma_temps):.0f}℃"
            )
            if date in om_by_day:
                idxs = om_by_day[date]
                om_rain = any(
                    om_h["weather_code"][i] in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
                    for i in idxs
                )
                om_temps = [om_h["temperature_2m"][i] for i in idxs]
                om_s = ("有雨时段" if om_rain else "无明显降雨") + (
                    f"，{min(om_temps):.0f}~{max(om_temps):.0f}℃"
                )
            else:
                om_s = "—"
            lines.append(f"| {date} | {cma_s} | {om_s} |")
        lines.append("")

    lines.append("---")
    lines.append(
        "> 使用提示：行程以《大连行程规划-详细版.md》为准；"
        "8/15（D1 南海岸）雨天执行预案 B（室内），8/16（D2）海钓取消执行室内预案，"
        "8/17（D3）赶海需干潮 19:00 前窗口。本文件每小时刷新，出发前看最新一次即可。"
    )
    return "\n".join(lines)


def summarize_24h(by_day: dict) -> str:
    now = datetime.now()
    date = now.strftime("%Y-%m-%d")
    entries = by_day.get(date, [])
    if not entries:
        return "24h 摘要：暂无当日数据"
    rains = [h for h, d, _t, _wd, _ws in entries if is_rain(d)]
    temps = [t for _h, _d, t, _wd, _ws in entries]
    return (
        f"当日({date})：降雨 {'/'.join(f'{h:02d}时' for h in rains)}"
        if rains
        else f"当日({date})：无明显降雨"
    ) + f"，温度 {min(temps):.0f}~{max(temps):.0f}℃"


def main() -> int:
    now = datetime.now()
    try:
        hour3, sk = fetch_cma()
        om = fetch_openmeteo() if INCLUDE_COMPARISON else None
    except Exception as exc:  # noqa: BLE001
        with LOG_MD.open("a", encoding="utf-8") as f:
            f.write(f"| {now:%Y-%m-%d %H:%M} | FAIL | {type(exc).__name__}: {exc} |\n")
        return 1

    OUT_MD.write_text(build_md(hour3, sk, om, now), encoding="utf-8")
    summary = summarize_24h(parse_cma_entries(hour3))
    with LOG_MD.open("a", encoding="utf-8") as f:
        f.write(f"| {now:%Y-%m-%d %H:%M} | OK | {summary} |\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
