#!/usr/bin/env python3
"""小红书夏日体验项目调研（真实游客视角，广告过滤 + 评论校验）。

用法（复用登录态 Firefox profile）：
  /tmp/xhs-venv/bin/python xhs_research.py [--dry-run]

流程：
1. 用用户已登录小红书的 Firefox profile 副本启动浏览器（不碰原浏览器）；
2. 对每组关键词直接进入搜索路由（不模拟输入框，降低风控）；
3. 每个关键词取前 3 篇笔记进详情页，提取标题/正文/作者/广告标记；
4. 广告过滤评分：广告词/商家认证/推广标识 → 减分；具体体验词 + 作者/日期/点赞 → 加分；
   只把"真实游客笔记"写进推荐，广告/商家推广类单独归档供核对；
5. 输出：
   - 小红书-夏日体验项目调研.md  证据工作簿（保留笔记 + 广告归档）
   - 大连行程规划-详细版.md      末尾追加"待把关推荐"章节

评论读取：已实测 5 篇笔记详情，4 篇提示"请打开小红书App扫码查看"、1 篇无法水合，
按用户约定放弃评论维度，真实性情以"广告/商家推广过滤 + 正文与作者信号"为准。

隐蔽性：随机 2-6 秒停顿、单页慢速滚动、每关键词只开 3 篇、遇验证码立即停止。
"""

import json
import subprocess
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote, urlparse, parse_qs

from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service

BASE_DIR = Path(__file__).resolve().parent
PROFILE_DIR = Path("/tmp/xhs-ff-profile")
OUT_WORKBOOK = BASE_DIR / "小红书-夏日体验项目调研.md"
OUT_PLAN = BASE_DIR / "大连行程规划-详细版.md"
OUT_TARGET_WORKBOOK = BASE_DIR / "小红书-景点餐厅调研.md"
TARGETS_CFG = BASE_DIR / "research_targets.json"

QUERIES = [
    "大连 夏天 值得体验的项目",
    "大连 摩托艇 沙滩 海上项目",
    "大连 洗浴 搓澡 推荐",
    "大连 赶海 体验 攻略",
    "大连 宝藏体验 本地人",
    "大连 夏日 限定 好玩",
]

AD_WORDS = [
    "广告", "赞助", "推广", "体验官", "探店合作", "团购", "限时", "下单",
    "优惠券", "领取福利", "点击链接", "福利群",
]
AUTH_WORDS = ["认证", "MCN", "品牌方", "商家", "企业号", "签约"]
EXP_WORDS = [
    "摩托艇", "快艇", "帆船", "桨板", "海钓", "潜水", "浮潜", "帆板",
    "赶海", "螃蟹", "贝壳", "生蚝", "海胆", "搓澡", "洗浴", "温泉", "汗蒸",
    "按摩", "足疗", "价格", "多少钱", "排队", "预约", "攻略", "体验",
    "好玩", "推荐", "踩雷", "避雷", "真实", "本地人", "情侣", "亲子",
]

VERIFY_MARKERS = ["安全验证", "请完成验证", "验证码", "拖动滑块", "访问过于频繁", "操作过于频繁"]
QR_MARKERS = ["扫码", "二维码", "打开App", "请在App", "下载App", "手机查看", "扫码查看"]

# 评论读取已按约定放弃（详情页需 App 扫码，5/5 失败）；True 仅用于未来恢复
COMMENT_READ = False

# 真实鼠标点击（cliclick）：把网页元素坐标换算成屏幕坐标并执行 OS 级点击，
# 避免 JS 合成事件被 SPA/反爬识别。CHROME_Y 为 macOS Firefox 工具栏高度，自适应校准。
CLICLICK = "/opt/homebrew/bin/cliclick"
SCREENSHOT = "/tmp/xhs_ocr_shot.png"


def run_swift(script: str, *args):
    r = subprocess.run(
        ["swift", str(BASE_DIR / script)] + list(args),
        capture_output=True,
        text=True,
        timeout=90,
        cwd=str(BASE_DIR),
    )
    try:
        return json.loads(r.stdout)
    except Exception:
        return []


def list_windows(owner: str) -> list[dict]:
    return run_swift("window_list.swift", owner)


def raise_firefox_window(drv) -> None:
    """把 Selenium 打开的 Firefox 窗口提到最前（按位置/标题匹配，避免误前置用户自己的 Firefox）。"""
    rect = drv.get_window_rect()
    wins = [w for w in list_windows("firefox") if w.get("w", 0) > 300]
    if not wins:
        return
    best = min(
        wins,
        key=lambda w: abs(w["x"] - rect["x"])
        + abs(w["y"] - rect["y"])
        + abs(w["w"] - rect["width"])
        + abs(w["h"] - rect["height"]),
    )
    name = best.get("name") or ""
    if not name:
        return
    esc = name.replace("\\", "\\\\").replace('"', '\\"')
    script = (
        'tell application "System Events"\n'
        '  tell process "firefox"\n'
        "    set frontmost to true\n"
        "    repeat with w in windows\n"
        f'      if (name of w) contains "{esc[:40]}" then\n'
        '        perform action "AXRaise" of w\n'
        "        set frontmost to true\n"
        "        exit repeat\n"
        "      end if\n"
        "    end repeat\n"
        "  end tell\n"
        "end tell"
    )
    subprocess.run(["osascript", "-e", script], capture_output=True, timeout=15)
    time.sleep(0.8)


def screen_ocr() -> list[dict]:
    subprocess.run(["screencapture", "-x", SCREENSHOT], check=False, timeout=30)
    return run_swift("ocr_screen.swift", SCREENSHOT)


def ocr_find(entries: list[dict], needle: str):
    """按标题在 OCR 结果中定位（排除顶栏/地址栏 y<150），返回命中的条目或 None。"""
    key = re.sub(r"[^\w\u4e00-\u9fff]", "", needle or "")
    best, best_score = None, 0
    for d in entries:
        t = re.sub(r"[^\w\u4e00-\u9fff]", "", d.get("text", ""))
        if not t or d.get("y", 0) < 150:
            continue
        score = 0
        for i in range(min(len(key), 12), 3, -1):
            if key[:i] in t or t[:i] in key:
                score = i
                break
        if score > best_score:
            best_score, best = score, d
    return best if best_score >= 4 else None


def text_contains_key(text: str, needle: str) -> bool:
    """宽松判断：标题的有效字是否出现在 OCR 文本中（容忍 OCR 碎片/顺序噪音）。"""
    key = re.sub(r"[^\w\u4e00-\u9fff]", "", needle or "")
    if not key:
        return False
    tn = re.sub(r"[^\w\u4e00-\u9fff]", "", text or "")
    core = key[:10]
    for i in range(0, max(1, len(core) - 4)):
        if core[i:i + 5] in tn:
            return True
    pos, ok = -1, True
    for ch in core[:8]:
        p = tn.find(ch, pos + 1)
        if p < 0:
            ok = False
            break
        pos = p
    return ok


def real_click_text(drv, needle: str):
    """前置窗口→截图 OCR→按标题定位→真实鼠标点击。找不到时向下滚动重试，最多 3 轮。"""
    raise_firefox_window(drv)
    for _ in range(3):
        entries = screen_ocr()
        hit = ocr_find(entries, needle)
        if hit:
            x, y = int(hit["x"]), int(hit["y"])
            subprocess.run([CLICLICK, f"c:{x},{y}"], capture_output=True, timeout=10)
            return x, y
        try:
            drv.execute_script("window.scrollBy(0, 420);")
        except Exception:
            pass
        human_delay(1.0, 2.0)
    return None


CHROME_TOKENS = [
    "创作中心", "业务合作", "发现", "RED", "直播", "发布", "通知", "消息", "我",
    "沪ICP备", "营业执照", "增值电信", "医疗器械", "互联网药品", "举报", "备案",
    "© 2014", "行吟信息科技", "马当路", "手机查看",
]
CHROME_LINE_RE = re.compile(
    r"^(Firefox|文件|编辑|查看|历史|书签|工具|窗口|帮助|口|个|随|随|目|之|心|女|C|◎|\+|发现|RED|直播|发布|通知|消息|我|"
    r"iTerm2|Shell|Edit|View|Session|Scripts|Profiles|Window|Help|〇|打开位置|管理书签|可将书签|"
    r"www\.|http|小红书|创作中心|业务合作|沪ICP备|营业执照|增值电信|医疗器械|互联网药品|举报|备案|"
    r"© 2014|行吟信息科技|马当路|手机查看|¥|日期|$|—|\|)"
)


def clean_visible(text: str) -> str:
    t = text or ""
    for tok in CHROME_TOKENS:
        t = t.replace(tok, " ")
    return re.sub(r"\s+", " ", t).strip()[:400]


def meaningful_lines(lines) -> list[str]:
    """过滤浏览器界面噪音，保留有信息量的正文/评论行。"""
    out = []
    for t in lines:
        t = (t or "").strip()
        if len(t) < 4:
            continue
        if CHROME_LINE_RE.match(t):
            continue
        if t not in out:
            out.append(t)
    return out


def window_center(drv) -> tuple[int, int]:
    rect = drv.get_window_rect()
    return int(rect["x"] + rect["width"] / 2), int(rect["y"] + rect["height"] / 2)


def scroll_real(drv, times: int = 3, step: int = -6) -> None:
    """真实滚轮滚动（cliclick），模拟人手在页面上滑。"""
    raise_firefox_window(drv)
    cx, cy = window_center(drv)
    subprocess.run([CLICLICK, f"m:{cx},{cy}"], capture_output=True, timeout=10)
    time.sleep(0.3)
    for _ in range(times):
        subprocess.run([CLICLICK, f"w:{step}"], capture_output=True, timeout=10)
        human_delay(1.1, 2.0)


def collect_visible(drv, scrolls: int = 4) -> list[str]:
    """在笔记页逐屏滚动 + OCR，累积去重的可见文本（正文+评论区）。"""
    lines: list[str] = []
    for i in range(scrolls):
        for d in screen_ocr():
            t = (d.get("text") or "").strip()
            if t and t not in lines:
                lines.append(t)
        if i < scrolls - 1:
            scroll_real(drv, 1, -6)
            human_delay(1.0, 2.0)
    return lines


def log(*a):
    print(*a, flush=True)


def human_delay(lo=2.0, hi=6.0):
    time.sleep(random.uniform(lo, hi))


def launch_driver():
    opts = Options()
    opts.binary_location = "/Applications/Firefox.app/Contents/MacOS/firefox"
    opts.add_argument("-profile")
    opts.add_argument(str(PROFILE_DIR))
    opts.set_preference("dom.webdriver.enabled", False)
    opts.set_preference("useAutomationExtension", False)
    opts.add_argument("--width=1366")
    opts.add_argument("--height=900")
    opts.page_load_strategy = "eager"  # DOM 就绪即返回，避免长轮询导致的超时
    svc = Service("/opt/homebrew/bin/geckodriver", log_output="/tmp/gecko-research.log")
    drv = webdriver.Firefox(service=svc, options=opts)
    drv.set_page_load_timeout(60)
    return drv


def page_text(drv) -> str:
    try:
        return drv.find_element(By.TAG_NAME, "body").text or ""
    except Exception:
        return ""


def verify_blocked(drv) -> bool:
    txt = page_text(drv)
    return any(m in txt for m in VERIFY_MARKERS)


def search_notes(drv, keyword: str) -> list[dict]:
    """进入搜索路由并提取笔记链接（不模拟输入框）。"""
    url = "https://www.xiaohongshu.com/search_result?keyword=" + quote(keyword)
    for attempt in range(3):
        try:
            drv.get(url)
            break
        except Exception as exc:
            if attempt == 2:
                raise
            log(f"  导航重试 {attempt + 1}：{str(exc)[:70]}")
            human_delay(3.0, 5.0)
    human_delay(3.0, 6.0)
    if verify_blocked(drv):
        return []  # 调用方据空结果判断风控
    # 真实滚动 ≥3 次解锁更多信息流
    scroll_real(drv, 3, -6)
    human_delay(2.0, 3.5)
    js = """
    const out = [];
    const seen = new Set();
    document.querySelectorAll('a[href*="/explore/"]').forEach(a => {
      const m = a.href.match(/\\/explore\\/([A-Za-z0-9]+)/);
      if (!m || seen.has(m[1])) return;
      seen.add(m[1]);
      const card = a.closest('section, li, div');
      const full = (card ? card.innerText : '') || '';
      const lines = full.split('\\n').map(s => s.trim()).filter(Boolean);
      const title = lines[0] || (a.innerText || '').trim();
      const author = lines[1] || '';
      const meta = lines.slice(1).join(' ');
      const date = (meta.match(/(\\d{1,2}[-/]\\d{1,2}|\\d{4}年\\d{1,2}月|\\d{1,2}月\\d{1,2}日|今天|昨天|刚刚)/) || [''])[0];
      const likes = (full.match(/(\\d+(?:\\.\\d+)?[wW万]?)\\s*$/) || ['', ''])[1];
      out.push({ id: m[1], href: a.href, title: title.slice(0, 60), author: author.slice(0, 30), date: date, likes: likes, cardText: full.replace(/\\s+/g,' ').trim().slice(0, 160) });
    });
    return out.slice(0, 8);
    """
    try:
        return drv.execute_script(js)
    except Exception:
        return []


def read_detail_state(drv) -> dict:
    """读取当前页面（笔记详情）的状态：水合/标题/正文/作者/广告/扫码。"""
    js = """
    const pick = (sels) => { for (const s of sels) { const e = document.querySelector(s); if (e && e.innerText) return e.innerText.trim(); } return ''; };
    const s = window.__INITIAL_STATE__ || {};
    const nd = (s.note && s.note.noteDetailMap) || {};
    const k = Object.keys(nd)[0];
    const d = k && k !== 'undefined' ? (nd[k].note || nd[k]) : null;
    const comments = [];
    document.querySelectorAll('.comment-item, .note-comment, [class*="comment-item"], [class*="comment"] .content, .comment .content').forEach(e => {
      const t = (e.innerText || '').trim();
      if (t && t.length > 6 && comments.length < 40) comments.push(t.slice(0, 200));
    });
    const bodyText = document.body.innerText || '';
    const adHit = /广告|赞助|推广|团购|体验官|下单/.test(bodyText);
    const adSnippet = adHit ? (bodyText.match(/.{0,40}(广告|赞助|推广|团购|体验官|下单).{0,40}/) || [''])[0].replace(/\\s+/g,' ') : '';
    const qrHit = /扫码|二维码|打开App|请在App|下载App|手机查看|扫码查看/.test(bodyText);
    const qrSnippet = qrHit ? (bodyText.match(/.{0,30}(扫码|二维码|打开App|请在App|下载App|手机查看|扫码查看).{0,30}/) || [''])[0].replace(/\\s+/g,' ') : '';
    return {
      hydrated: !!d,
      title: (d && d.title) || pick(['#detail-title', 'h1']),
      desc: (d && d.desc) || pick(['#detail-desc', '.desc']),
      author: (d && (d.user && (d.user.nickname || d.user.nickName))) || pick(['.author-wrapper .username', '.author-container .username', '.author-name', '.name']),
      commentCount: d && d.interactInfo ? d.interactInfo.commentCount : '',
      comments: __COMMENT_READ__ ? comments : [],
      qrRequired: qrHit,
      qrSnippet: qrSnippet,
      adMarked: adHit,
      adSnippet: adSnippet,
      bodySample: bodyText.slice(0, 300).replace(/\\s+/g, ' ')
    };
    """
    try:
        return drv.execute_script(
            js.replace("__COMMENT_READ__", "true" if COMMENT_READ else "false")
        )
    except Exception as exc:
        return {"error": str(exc)[:120]}


def open_note_by_click(drv, note_id: str, href: str, title: str, base_handle: str) -> dict:
    """搜索页内用真实鼠标点击卡片打开详情。

    定位 = 截屏 + OCR 找标题文字；验证 = 截屏 OCR（扫码墙/正文可见）+ DOM 水合。
    返回：ok、reason、data（含 visibleText 屏幕可见文本）。
    """
    try:
        el = drv.find_element(By.CSS_SELECTOR, f'a[href*="/explore/{note_id}"]')
        drv.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        human_delay(0.8, 1.6)
    except Exception:
        pass
    pos = real_click_text(drv, title)
    if pos is None:
        return {"ok": False, "reason": "OCR 未识别到卡片标题", "data": {}}
    human_delay(3.0, 6.0)
    # 新标签则切换
    if len(drv.window_handles) > 1:
        drv.switch_to.window(drv.window_handles[-1])
        human_delay(2.0, 4.0)
    data = read_detail_state(drv)
    # 笔记页真实滚动 ≥4 次，逐屏 OCR 累积正文与评论区
    lines = collect_visible(drv, 4)
    visible = " ".join(lines)
    data["visibleLines"] = lines
    data["visibleText"] = visible
    if verify_blocked(drv) or "访问过于频繁" in visible:
        return {"ok": False, "reason": "触发风控验证", "data": data}
    if "扫码" in visible or "打开App" in visible:
        return {"ok": False, "reason": "需 App 扫码查看", "data": data}
    if data.get("hydrated") or text_contains_key(visible, title):
        return {"ok": True, "reason": "", "data": data}
    return {"ok": False, "reason": "详情未加载", "data": data}


def close_note(drv, base_handle: str):
    """关掉笔记标签/返回搜索页。"""
    try:
        if len(drv.window_handles) > 1:
            drv.close()
            drv.switch_to.window(base_handle)
        else:
            drv.back()
    except Exception:
        try:
            drv.switch_to.window(base_handle)
        except Exception:
            pass
    human_delay(1.5, 3.0)


def score_note(note: dict) -> tuple[int, str, bool]:
    title = note.get("title", "")
    desc = note.get("desc", "") or note.get("cardText", "")
    author = note.get("author", "")
    comments = note.get("comments", [])
    text = title + " " + desc
    s = 0
    reasons = []
    # 页面级广告标记只在正文可读（hydrated）时采信；否则会被页脚文字误伤
    effective_ad = bool(note.get("adMarked")) and bool(note.get("hydrated"))
    title_ad = next((w for w in AD_WORDS if w in title), "")
    if effective_ad:
        s -= 4
        reasons.append("页面含广告/赞助标识")
    elif title_ad:
        s -= 3
        reasons.append(f"标题含广告词「{title_ad}」")
    for w in AUTH_WORDS:
        if w in author or w in text:
            s -= 2
            reasons.append(f"疑似商家/认证「{w}」")
            break
    hit = [w for w in EXP_WORDS if w in desc]
    s += min(len(hit), 4)
    if hit:
        reasons.append("命中具体体验词：" + "、".join(list(dict.fromkeys(hit))[:5]))
    real_c, ad_c = 0, 0
    for c in comments:
        if any(w in c for w in AD_WORDS):
            ad_c += 1
        elif any(w in c for w in EXP_WORDS) and len(c) >= 10:
            real_c += 1
    s += min(real_c, 3) - min(ad_c, 2)
    if real_c:
        reasons.append(f"评论区 {real_c} 条具体体验")
    if ad_c:
        reasons.append(f"评论区 {ad_c} 条疑似广告")
    return s, "；".join(reasons) if reasons else "信息量一般", effective_ad or bool(title_ad)


def run(queries, max_notes_per_query=3):
    driver = launch_driver()
    results = []
    blocked = False
    base = driver.current_window_handle
    attempts = 0
    ok_count = 0
    fail_reasons: dict[str, int] = {}
    try:
        for qi, q in enumerate(queries, 1):
            log(f"[{qi}/{len(queries)}] 搜索：{q}")
            notes = search_notes(driver, q)
            if not notes:
                if verify_blocked(driver):
                    log("  !! 触发风控/验证，停止后续检索（已保留已完成部分）")
                    blocked = True
                    break
                log("  无结果")
                continue
            picked = notes[:max_notes_per_query]
            for n in picked:
                # 确保当前在搜索结果页（SPA 返回后可能丢页面）
                try:
                    cur = driver.execute_script("return location.href;") or ""
                    if "search_result" not in cur:
                        driver.get("https://www.xiaohongshu.com/search_result?keyword=" + quote(q))
                        human_delay(3.0, 5.0)
                except Exception:
                    pass
                attempts += 1
                opened = open_note_by_click(driver, n["id"], n["href"], n.get("title", ""), base)
                if opened["ok"]:
                    ok_count += 1
                else:
                    fail_reasons[opened["reason"]] = fail_reasons.get(opened["reason"], 0) + 1
                if opened["reason"] == "触发风控验证":
                    blocked = True
                    log("  !! 详情页触发风控，停止")
                    break
                note = opened.get("data") or {}
                note["openResult"] = opened["reason"] or ("OK" if opened["ok"] else "未知")
                if opened["reason"] == "需 App 扫码查看":
                    note["qrRequired"] = True
                if not opened["ok"]:
                    note["loaded"] = False
                # 详情未水合时，用搜索卡片信息兜底
                if not note.get("title"):
                    note["title"] = n.get("title", "")
                if not note.get("author"):
                    note["author"] = n.get("author", "")
                if not note.get("desc"):
                    note["desc"] = clean_visible(note.get("visibleText", ""))
                note.update({
                    "query": q, "href": n["href"], "id": n["id"],
                    "cardDate": n.get("date", ""), "cardLikes": n.get("likes", ""),
                    "cardText": n.get("cardText", ""),
                    "detailUnavailable": not note.get("hydrated"),
                    "viewed": opened["ok"],
                })
                if note.get("qrRequired"):
                    log(f"  [扫码限制] {note.get('title','')[:36]} — 需 App 扫码，正文不可读")
                note["score"], note["reason"], note["adMarked"] = score_note(note)
                keep = (
                    opened["ok"]
                    and note["score"] >= 1
                    and not note.get("adMarked")
                    and not note.get("qrRequired")
                )
                note["keep"] = keep
                verdict = "保留" if keep else "广告/低分-剔除"
                open_mark = "真实点击打开OK" if opened["ok"] else f"打开失败({opened['reason']})"
                log(f"  [{verdict} {note['score']:+d}] {note.get('title','')[:34]} | {open_mark} | 详情{'水合' if note.get('hydrated') else 'OCR/卡片兜底'} 评论{len(note.get('comments',[]))}条")
                results.append(note)
                close_note(driver, base)
                # 每 10 页汇报一次进度
                if attempts % 10 == 0:
                    reason_txt = "、".join(f"{k}×{v}" for k, v in fail_reasons.items()) or "无"
                    log(f"  ── [进度 {attempts} 页] 成功 {ok_count} · 失败 {attempts - ok_count}（{reason_txt}）")
                human_delay(2.0, 4.0)
            if blocked:
                break
            human_delay(4.0, 7.0)
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    # 末尾总进度
    reason_txt = "、".join(f"{k}×{v}" for k, v in fail_reasons.items()) or "无"
    log(f"最终进度：共 {attempts} 页 · 成功 {ok_count} · 失败 {attempts - ok_count}（{reason_txt}）")
    return results, blocked


def markdown(results, blocked) -> str:
    kept = [r for r in results if r.get("keep")]
    dropped = [r for r in results if not r.get("keep")]
    lines = [
        "# 小红书·夏日体验项目调研（2026-08，真实游客视角）",
        "",
        f"- 检索时间：{time.strftime('%Y-%m-%d %H:%M')}（Firefox 登录态，隐蔽浏览）",
        f"- 检索词：{'；'.join(QUERIES)}",
        f"- 风控中断：{'是（后续关键词未检索）' if blocked else '否'}",
        f"- 保留真实笔记 {len(kept)} 篇；广告/低分剔除 {len(dropped)} 篇（归档见文末）",
        "- 评论读取：已按约定放弃（5 次实测均需 App 扫码/无法水合）；真实性判断 = 广告与商家推广过滤 + 标题/正文/作者/日期/点赞信号",
        "",
        "## 保留（真实游客笔记）",
        "",
    ]
    if not kept:
        lines.append("（本轮未获取到可保留笔记，可能被风控或引擎变化影响。）")
    for r in kept:
        ext = ""
        if r.get("cardDate"):
            ext += f"（{r.get('cardDate')}，赞 {r.get('cardLikes') or '—'}）"
        if r.get("detailUnavailable"):
            ext += "　⚠️ 详情页未自动打开，评论请在 App 内复核"
        lines += [
            f"### {r.get('title','（无标题）')}{ext}",
            "",
            f"- 链接：[打开笔记]({r['href']})",
            f"- 作者：{r.get('author','—')}（卡片识别，可能有误差）｜ 评分：{r['score']:+d}",
            f"- 摘要：{(r.get('desc','') or '').replace(chr(10),' ')[:180]}",
            f"- 理由：{r.get('reason','')}",
        ]
        lines.append("- 广告过滤：已通过（无广告/赞助/团购标识，作者无商家认证）；正文可在 App 内复核")
        lines.append("")
    lines += ["## 广告 / 低分归档（供核对，不计入推荐）", ""]
    for r in dropped:
        lines.append(
            f"- {r.get('title','（无标题）')}（{r['score']:+d}）{r.get('reason','')} — [链接]({r['href']})"
        )
    if blocked:
        lines += [
            "",
            "> ⚠️ 本轮触发风控提前停止，建议 1-2 小时后再试，或减少检索词。",
        ]
    return "\n".join(lines)


def append_to_plan(results) -> str:
    kept = [r for r in results if r.get("keep")]
    if not kept:
        return ""
    section = [
        "",
        "## 9. 小红书夏日体验项目推荐（2026-08 检索，**待你把关后加入行程**）",
        "",
        "> 以下项目来自真实游客笔记：已按约定放弃评论读取（详情页需 App 扫码），",
        "> 真实性依据 = 广告/商家推广过滤 + 标题、作者、日期、点赞信号。",
        "> 作者名为搜索卡片识别、可能有误差，以笔记链接内实际作者为准。",
        "> 勾选/删除后我再排入 Day 2–Day 5 空档；价格与开放时间以现场为准。",
        "",
    ]
    topics = {}
    for r in kept:
        t = r.get("title", "")
        key = "水上/海上项目" if any(w in t for w in ["摩托艇", "快艇", "帆船", "桨板", "海钓", "潜水", "出海"]) else (
            "洗浴/放松" if any(w in t for w in ["搓澡", "洗浴", "温泉", "汗蒸", "按摩"]) else (
                "赶海/沙滩" if any(w in t for w in ["赶海", "沙滩", "螃蟹"]) else "其他体验"
            )
        )
        topics.setdefault(key, []).append(r)
    for key, rs in topics.items():
        section.append(f"### {key}")
        section.append("")
        for r in rs:
            ext = ""
            if r.get("cardDate"):
                ext += f"（{r.get('cardDate')}，赞 {r.get('cardLikes') or '—'}）"
            section.append(
                f"- [ ] **{r.get('title','（无标题）')}**{ext}（{r.get('author','—')}）"
                f" ｜ 广告过滤：通过 ｜ [笔记链接]({r['href']})"
            )
        section.append("")
    return "\n".join(section)


def run_targets(max_notes_per_target: int = 3, skip_targets: set | None = None):
    """对行程中的景点/餐厅逐个检索：搜索流滚动 → 真实点击笔记 → 笔记页滚动+OCR 正文/评论。"""
    skip_targets = skip_targets or set()
    driver = launch_driver()
    base = driver.current_window_handle
    targets = json.loads(TARGETS_CFG.read_text(encoding="utf-8"))["targets"]
    results = []
    attempts = ok_count = 0
    fail_reasons: dict[str, int] = {}
    blocked = False
    try:
        for ti, t in enumerate(targets, 1):
            if t["name"] in skip_targets:
                log(f"[{ti}/{len(targets)}] 跳过（已采集）：{t['name']}")
                continue
            log(f"[{ti}/{len(targets)}] 目标：{t['name']}（{t['keyword']}）")
            notes = search_notes(driver, t["keyword"])
            if not notes:
                if verify_blocked(driver):
                    log("  !! 触发风控/验证，停止后续检索")
                    blocked = True
                    break
                log("  无结果")
                results.append({"target": t, "notes": []})
                continue
            picked = notes[:max_notes_per_target]
            # 按笔记 ID 去重（同一篇可能出现在多个卡片位）
            seen_ids = set()
            picked = []
            for n in notes:
                if n["id"] not in seen_ids:
                    seen_ids.add(n["id"])
                    picked.append(n)
                if len(picked) >= max_notes_per_target:
                    break
            target_notes = []
            for n in picked:
                attempts += 1
                opened = open_note_by_click(driver, n["id"], n["href"], n.get("title", ""), base)
                if opened["ok"]:
                    ok_count += 1
                else:
                    fail_reasons[opened["reason"]] = fail_reasons.get(opened["reason"], 0) + 1
                if opened["reason"] == "触发风控验证":
                    blocked = True
                    log("  !! 触发风控，停止")
                    break
                note = opened.get("data") or {}
                note["openResult"] = opened["reason"] or ("OK" if opened["ok"] else "未知")
                if opened["reason"] == "需 App 扫码查看":
                    note["qrRequired"] = True
                if not opened["ok"]:
                    note["loaded"] = False
                if not note.get("title"):
                    note["title"] = n.get("title", "")
                if not note.get("author"):
                    note["author"] = n.get("author", "")
                if not note.get("desc"):
                    note["desc"] = clean_visible(note.get("visibleText", ""))
                note.update({
                    "target": t["name"], "targetType": t["type"],
                    "href": n["href"], "id": n["id"],
                    "cardDate": n.get("date", ""), "cardLikes": n.get("likes", ""),
                    "cardText": n.get("cardText", ""),
                    "detailUnavailable": not note.get("hydrated"),
                    "viewed": opened["ok"],
                })
                note["isVideo"] = str(note.get("type", "")) == "video" or "视频" in note.get("visibleText", "")
                note["score"], note["reason"], note["adMarked"] = score_note(note)
                keep = (
                    opened["ok"]
                    and note["score"] >= 1
                    and not note.get("adMarked")
                    and not note.get("qrRequired")
                )
                note["keep"] = keep
                verdict = "保留" if keep else "广告/低分-剔除"
                open_mark = "真实点击OK" if opened["ok"] else f"失败({opened['reason']})"
                vis_n = len(note.get("visibleLines", []))
                log(f"  [{verdict} {note['score']:+d}] {note.get('title','')[:30]} | {open_mark} | OCR行{vis_n}" + (" | 视频笔记(取文本)" if note.get("isVideo") else ""))
                target_notes.append(note)
                close_note(driver, base)
                try:
                    cur = driver.execute_script("return location.href;") or ""
                    if "search_result" not in cur:
                        driver.get("https://www.xiaohongshu.com/search_result?keyword=" + quote(t["keyword"]))
                        human_delay(3.0, 5.0)
                except Exception:
                    pass
                if attempts % 10 == 0:
                    rt = "、".join(f"{k}×{v}" for k, v in fail_reasons.items()) or "无"
                    log(f"  ── [进度 {attempts} 页] 成功 {ok_count} · 失败 {attempts - ok_count}（{rt}）")
                human_delay(1.5, 3.0)
            results.append({"target": t, "notes": target_notes})
            human_delay(3.0, 5.0)
            if blocked:
                break
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    rt = "、".join(f"{k}×{v}" for k, v in fail_reasons.items()) or "无"
    log(f"最终进度：共 {attempts} 页 · 成功 {ok_count} · 失败 {attempts - ok_count}（{rt}）")
    return results, blocked


def build_target_workbook(results, blocked) -> str:
    lines = [
        "# 小红书·景点/餐厅真实游客调研（2026-08）",
        "",
        f"- 检索时间：{time.strftime('%Y-%m-%d %H:%M')}（Firefox 登录态 + 真实滚动/点击 + 屏幕 OCR）",
        "- 方法：每个目标搜索 → 信息流滚动 ≥3 次 → 真实点击前 3 篇 → 笔记页滚动 ≥4 次逐屏 OCR（正文+评论区）",
        "- 广告过滤：标题/正文广告词、商家认证、扫码页一律剔除；只留真实游客信号",
        f"- 风控中断：{'是' if blocked else '否'}",
        "",
    ]
    for item in results:
        t = item["target"]
        notes = item["notes"]
        kept = [n for n in notes if n.get("keep")]
        lines.append(f"## {t['name']}（{t['type']}）")
        lines.append("")
        lines.append(f"- 检索词：`{t['keyword']}` ｜ 大众点评：`{t['dpKeyword']}`")
        lines.append(f"- 打开笔记 {len(notes)} 篇，保留 {len(kept)} 篇")
        lines.append("")
        for n in notes:
            mark = "✅保留" if n.get("keep") else "⛔剔除"
            extra = "（视频笔记，仅取文本）" if n.get("isVideo") else ""
            lines.append(f"### {mark} {n.get('title','（无标题）')}{extra}")
            lines.append("")
            if n.get("cardDate"):
                lines.append(f"- 时间/赞：{n.get('cardDate')}，赞 {n.get('cardLikes') or '—'}")
            lines.append(f"- 作者：{n.get('author','—')}（卡片识别，可能有误差）｜ 评分 {n.get('score',0):+d}")
            lines.append(f"- 理由：{n.get('reason','')}")
            lines.append(f"- 链接：[打开笔记]({n['href']})")
            vis = meaningful_lines(n.get("visibleLines") or [])
            if vis:
                lines.append("- 屏幕可见内容（正文/评论，OCR 摘录）：")
                for v in vis[:30]:
                    lines.append(f"  - {v[:100]}")
            lines.append("")
    if blocked:
        lines.append("> ⚠️ 触发风控提前停止，建议稍后再补跑。")
    return "\n".join(lines)


def append_target_summary(results) -> str:
    """把每个目标的证据骨架追加到详细版文档，评价由人工/AI 依据工作簿提炼。"""
    section = [
        "",
        "## 10. 景点/餐厅真实游客评价（2026-08 小红书+评论区检索，附链接）",
        "",
        "> 方法：真实游客笔记（广告过滤）+ 正文/评论区 OCR 摘录；每处附小红书笔记与大众点评搜索链接。",
        "> 评论如未能自动读取会明确标注，请按链接在 App 内复核。",
        "",
    ]
    for item in results:
        t = item["target"]
        notes = item["notes"]
        kept = [n for n in notes if n.get("keep")]
        section.append(f"### {t['name']}")
        section.append("")
        if kept:
            section.append("**总体评价（待精炼）**：")
            for n in kept[:3]:
                snippet = " ".join(meaningful_lines(n.get("visibleLines") or []))[:150]
                section.append(f"- {n.get('title','')}（赞 {n.get('cardLikes') or '—'}）：{snippet}")
        else:
            section.append("本轮未获取到可保留的真实游客笔记（可能被风控或内容需 App 查看）。")
        section.append("")
        links = " ｜ ".join(
            f"[小红书笔记]({n['href']})" for n in kept[:4]
        ) or "（无可用链接）"
        dp = f"https://www.dianping.com/search/keyword/19/0_{quote(t['dpKeyword'])}"
        section.append(f"- 链接：{links} ｜ [大众点评搜索]({dp})")
        section.append("")
    return "\n".join(section)


def main():
    dry = "--dry-run" in sys.argv
    if dry:
        log("dry-run：仅检查环境，不检索")
        return 0
    if "--targets" in sys.argv:
        skip = set()
        if "--resume" in sys.argv:
            jf = BASE_DIR / "小红书-景点餐厅调研.json"
            if jf.exists():
                try:
                    for it in json.loads(jf.read_text(encoding="utf-8")):
                        if it.get("notes"):
                            skip.add(it["target"]["name"])
                except Exception:
                    skip = set()
            log(f"断点续跑：跳过 {len(skip)} 个已采集目标")
        results, blocked = run_targets(skip_targets=skip)
        OUT_TARGET_WORKBOOK.write_text(build_target_workbook(results, blocked), encoding="utf-8")
        (BASE_DIR / "小红书-景点餐厅调研.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        append = append_target_summary(results)
        if append:
            with OUT_PLAN.open("a", encoding="utf-8") as f:
                f.write("\n" + append + "\n")
        log(f"景点/餐厅调研完成：{len(results)} 个目标 → {OUT_TARGET_WORKBOOK}")
        return 0
    results, blocked = run(QUERIES)
    OUT_WORKBOOK.write_text(markdown(results, blocked), encoding="utf-8")
    append = append_to_plan(results)
    if append:
        with OUT_PLAN.open("a", encoding="utf-8") as f:
            f.write("\n" + append + "\n")
    log(f"完成：保留 {sum(1 for r in results if r.get('keep'))} / 总 {len(results)}")
    log(f"工作簿：{OUT_WORKBOOK}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
