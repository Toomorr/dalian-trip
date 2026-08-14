# 大连 5 日行程 · 交互地图与规划（2026-08-14 → 08-19）

两人大连行程的公开参考仓库：交互地图 + 详细规划 + 本地天气同步。

## 内容

| 文件 | 说明 |
|---|---|
| `index.html` | 交互地图页（Leaflet 本地化，顶部地图占 80% 视口、随滚动缩至 40% 并锁定；桌面/手机双端自适应；每个行程点附小红书搜索外链，手机端为 App 跳转+网页兜底） |
| `大连行程规划-详细版.md` | 五日规划：每日行程、晴天/雨天预案、景点证据库（小红书好评/差评+链接）、餐厅总览填空表、赶海攻略 |
| `大连天气-2小时预报.md` | 中央气象台逐 3 小时预报（沙河口区 101070210，每 5 分钟由 GitHub Actions 自动刷新，每日 8 个时次） |
| `sync_weather.py` | 天气同步脚本（由 `.github/workflows/weather-sync.yml` 每 5 分钟在 GitHub Actions 执行并提交回仓库） |
| `.github/workflows/weather-sync.yml` | GitHub Actions 定时任务：同步沙河口区天气（可手动触发；定时最小粒度 5 分钟） |
| `.github/workflows/weather-heartbeat.yml` | GitHub Actions 心跳任务：单次运行内每 60 秒同步并推送一次，每小时由定时重启（网页用 raw 直连，约 1 分钟可见） |
| `xhs_research.py` | 小红书调研脚本（本地 Firefox+真实鼠标+屏幕 OCR）：体验项目模式 / 景点餐厅模式（`--targets`），支持断点续跑（`--resume`） |
| `research_targets.json` | 景点/餐厅检索目标清单（18 个行程点） |
| `ocr_screen.swift` / `window_list.swift` | macOS Vision OCR 与窗口定位（点击坐标校准用） |
| `lib/` | Leaflet 1.9.4 本地库（页面离线可用） |
| `小红书存档/` | 小红书笔记图文存档（分享短链匿名下载） |

## 线上访问

本仓库通过 GitHub Pages 发布，公网地址见仓库 Settings → Pages。
手机上直接打开该地址即可实时查看地图与行程（底图瓦片需联网）。

## 天气更新流程（GitHub Actions）

1. `weather-heartbeat.yml` 单次运行内每 60 秒运行一次 `sync_weather.py` 并提交推送（约 55 分钟后由每小时定时重启）；`weather-sync.yml` 为 5 分钟粒度的备用/手动触发；
2. 网页总览每 60 秒直接拉取 raw.githubusercontent 的最新 md（带时间戳防缓存），并显示 Actions 最近运行时间（公开 API，每 2 分钟刷新）；
3. 注意：GitHub Actions 定时任务不保证准点（可能延迟数分钟），心跳方案在运行期间可稳定做到约每分钟一次更新；GitHub Pages 每小时最多构建 10 次，但页面走 raw 直连不受此限制；
4. 也可在 GitHub 仓库 Actions 页面手动触发两个工作流；
5. 页面总览会显示最新更新时间；如需本地手动刷一次，可执行：

```bash
python3 sync_weather.py
```

> 数据源：中国天气网/中央气象台（weather.com.cn，大连·沙河口区 101070210，对应酒店西安路/联合路一带）；Open-Meteo 仅作对照附注。

## 小红书调研（本地执行，需授权）

用于检索行程景点/餐厅的小红书真实游客笔记与评论区（广告/商家推广过滤）。需要本机条件：

- Firefox 已登录小红书；profile 复制到 `/tmp/xhs-ff-profile`（`xhs_research.py` docstring 有步骤）
- `geckodriver`、`/tmp/xhs-venv`（selenium）、`cliclick`（真实鼠标）、`swift`（macOS Vision OCR）
- macOS「辅助功能」权限给运行应用（真实点击）；「屏幕录制」权限给 `screencapture`（OCR 截图）

运行：

```bash
/tmp/xhs-venv/bin/python xhs_research.py --targets          # 全量 18 个目标
/tmp/xhs-venv/bin/python xhs_research.py --targets --resume  # 断点续跑（跳过已采集）
/tmp/xhs-venv/bin/python xhs_research.py                      # 体验项目检索
```

输出：`小红书-景点餐厅调研.md`（工作簿）、`小红书-景点餐厅调研.json`（原始数据）、并在详细版文档追加第 10 节。

> ⚠️ 风控提示：连续自动化浏览可能触发小红书风控，单轮后建议冷却 ≥1 小时再补采；遇「验证/访问过于频繁」脚本会自动停止并保留已完成部分。
