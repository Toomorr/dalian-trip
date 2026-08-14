#!/usr/bin/env python3
"""保存小红书笔记图文到本地（基于 XHS-Downloader 开源项目）。

用法：
  python save_xhs.py urls.txt [--download] [--out 小红书存档]

urls.txt 每行一个小红书链接，支持：
  - https://www.xiaohongshu.com/explore/<id>?xsec_token=...
  - https://www.xiaohongshu.com/discovery/item/<id>?xsec_token=...
  - https://xhslink.com/...（短链）

登录态（二选一）：
  1. 不带 Cookie：适用于带 xsec_token 的分享链接（可匿名访问）
  2. 带 Cookie：export XHS_COOKIE="你的小红书网页 Cookie"，可处理不带 token 的链接

输出：每个作品一个文件夹（图片 + 标题/正文 .md），成功/失败记录在 results.csv
"""

import asyncio
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, "/private/tmp/xhs-dl-src")
from source import XHS


async def main(urls_path: str, download: bool, out: str) -> None:
    urls = [
        line.strip()
        for line in Path(urls_path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cookie = os.environ.get("XHS_COOKIE", "")
    results = []

    async with XHS(
        work_path=str(out_dir),
        folder_name="Download",
        name_format="作品标题",
        cookie=cookie,
        timeout=10,
        max_retry=2,
        image_download=True,
        video_download=True,
        download_record=False,
        note_format="md",
        folder_mode=True,
    ) as xhs:
        for url in urls:
            try:
                data = await xhs.extract(url, download=download)
                ok = bool(data) and data != [{}]
                results.append((url, "OK" if ok else "FAIL", ""))
                print(("✓" if ok else "✗"), url)
            except Exception as exc:  # noqa: BLE001
                results.append((url, "ERROR", str(exc)[:200]))
                print("!", url, "->", exc)

    with (out_dir / "results.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["url", "status", "error"])
        w.writerows(results)
    print(f"\n完成：{len(urls)} 条链接，输出目录 {out_dir}")


if __name__ == "__main__":
    urls_file = sys.argv[1]
    download = "--download" in sys.argv
    out = "小红书存档"
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
    asyncio.run(main(urls_file, download, out))
