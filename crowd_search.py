#!/usr/bin/env python3
"""小红书拥堵信息自动检索（尽力而为，由 GitHub Actions 每日定时执行）。

说明：
- 对每个易拥堵景点用多个搜索引擎检索 `site:xiaohongshu.com <关键词> 排队 2026`，
  提取小红书帖子链接/标题写入《大连-拥堵排队检索.md》的"自动发现"区。
- 搜索引擎可能反爬/返回广告，此时如实记录"未获取到新结果"，并保留
  "AI 复核记录"区（由 Codex/人工核实后填写，脚本不会覆盖）。
- 纯标准库实现，无第三方依赖，可在 GitHub Actions 直接运行。
"""

import json
import re
import base64
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus
from urllib.request import Request, build_opener, urlopen

BASE_DIR = Path(__file__).resolve().parent
CFG = BASE_DIR / "crowd_watch.json"
OUT = BASE_DIR / "大连-拥堵排队检索.md"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_OPENER = build_opener()

AI_BEGIN = "<!-- AI-REVIEW-BEGIN -->"
AI_END = "<!-- AI-REVIEW-END -->"


def fetch(url: str, timeout: int = 15) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    with _OPENER.open(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")


def engines(query: str):
    urls = [
        ("bing", "https://www.bing.com/search?q=" + quote_plus(query) + "&count=10"),
        ("cnbing", "https://cn.bing.com/search?q=" + quote_plus(query) + "&mkt=zh-CN"),
        ("ddg", "https://html.duckduckgo.com/html/?q=" + quote_plus(query)),
    ]
    for engine, url in urls:
        try:
            yield engine, fetch(url)
        except Exception:
            continue


def _b64url_decode(s: str) -> str:
    try:
        pad = "=" * (-len(s) % 4)
        return base64.urlsafe_b64decode(s + pad).decode("utf-8", "ignore")
    except Exception:
        return ""


def _bing_target(ck_url: str) -> str:
    """把 Bing /ck/a 跳转链接还原成目标 URL（u= 参数为 base64url）。"""
    m = re.search(r"[?&]u=([A-Za-z0-9_-]+)", ck_url)
    return _b64url_decode(m.group(1)) if m else ""


def _is_xhs(url: str) -> bool:
    return "xiaohongshu.com" in url


def parse_results(html: str) -> list[tuple[str, str]]:
    """只提取真正指向 xiaohongshu.com 的 (url, title)。

    - Bing：<h2><a href="/ck/a?...&u=base64url(目标URL)">标题</a></h2>，
      解码 u= 并校验域名；也直接抓取正文里出现的 xiaohongshu 链接。
    - DuckDuckGo：class="result__a" href 为真实链接。
    """
    out = []
    # DuckDuckGo
    for m in re.finditer(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S
    ):
        url, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if _is_xhs(url):
            out.append((url, title))
    # Bing：解码 /ck/a 目标；同时匹配正文中直接出现的小红书链接
    for m in re.finditer(
        r'<h2[^>]*><a[^>]*href="([^"]+)"[^>]*>(.*?)</a></h2>', html, re.S
    ):
        href, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        target = _bing_target(href)
        if _is_xhs(target):
            out.append((target, title))
    for m in re.finditer(
        r'https://www\.xiaohongshu\.com/(?:discovery/item|explore)/[A-Za-z0-9]+',
        html,
    ):
        out.append((m.group(0), ""))
    # 去重
    seen = set()
    res = []
    for url, title in out:
        url = url.replace("&amp;", "&")
        if url in seen:
            continue
        seen.add(url)
        res.append((url, title))
    return res


def extract_ai_section(old: str) -> str:
    if not old:
        return (
            "### AI 复核记录（Codex/人工填写，脚本保留此区）\n\n"
            "- 最近一次 AI 复核：待执行\n"
        )
    m = re.search(re.escape(AI_BEGIN) + r"([\s\S]*?)" + re.escape(AI_END), old)
    return (m.group(1) if m else "").strip()


def build_report(now: datetime, results: dict, old: str) -> str:
    ai_section = extract_ai_section(old)
    lines = [
        "# 大连·拥堵排队检索工作簿（小红书 / 公开信息）",
        "",
        f"- 最近自动检索：{now:%Y-%m-%d %H:%M}（GitHub Actions 每日 07:00 / 17:00）",
        "- 自动检索为尽力而为：搜索引擎可能反爬或返回广告，无新结果时会如实标注。",
        "- **权威结论以下方 AI 复核记录为准**；出行当天建议在 App 内再搜「景点名+排队」确认。",
        "",
        AI_BEGIN,
        "",
        ai_section,
        "",
        AI_END,
        "",
        "## 自动发现（本次引擎结果）",
        "",
    ]
    for hs in CFG_HOTSPOTS:
        lines.append(f"### {hs['name']}（{hs['slot']}）")
        lines.append("")
        lines.append("检索词：`" + "` · `".join(hs["keywords"]) + "`")
        lines.append("")
        found = results.get(hs["name"], [])
        if found:
            lines.append("| 链接 | 标题 |")
            lines.append("|---|---|")
            for url, title in found[:8]:
                lines.append(f"| [打开]({url}) | {title or '（无标题）'} |")
        else:
            lines.append("- 本次未获取到新的小红书链接（引擎被拦截或结果为空），需人工/AI 复核。")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    now = datetime.now()
    global CFG_HOTSPOTS
    with CFG.open(encoding="utf-8") as f:
        CFG_HOTSPOTS = json.load(f)["hotspots"]

    results: dict[str, list[tuple[str, str]]] = {}
    for hs in CFG_HOTSPOTS:
        per_hs: list[tuple[str, str]] = []
        for kw in hs["keywords"]:
            q = f"site:xiaohongshu.com {kw} 排队 2026"
            for engine, html in engines(q):
                hits = parse_results(html)
                if hits:
                    per_hs.extend(hits)
                    break
            time.sleep(0.8)
        # 去重
        seen = set()
        dedup = []
        for url, title in per_hs:
            if url in seen:
                continue
            seen.add(url)
            dedup.append((url, title))
        results[hs["name"]] = dedup

    old = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
    OUT.write_text(build_report(now, results, old), encoding="utf-8")
    total = sum(len(v) for v in results.values())
    print(f"OK: {now:%Y-%m-%d %H:%M} 检索到 {total} 条结果")
    return 0


if __name__ == "__main__":
    sys.exit(main())
