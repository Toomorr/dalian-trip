# 大连 5 日行程 · 交互地图与规划（2026-08-14 → 08-19）

两人大连行程的公开参考仓库：交互地图 + 详细规划 + 本地天气同步。

## 内容

| 文件 | 说明 |
|---|---|
| `index.html` | 交互地图页（Leaflet 本地化，顶部地图占 80% 视口、随滚动缩至 40% 并锁定；桌面/手机双端自适应；每个行程点附小红书搜索外链，手机端为 App 跳转+网页兜底） |
| `大连行程规划-详细版.md` | 五日规划：每日行程、晴天/雨天预案、景点证据库（小红书好评/差评+链接）、餐厅总览填空表、赶海攻略 |
| `大连天气-2小时预报.md` | 中央气象台逐 3 小时预报（沙河口区 101070210，每小时由 GitHub Actions 自动刷新，每日 8 个时次） |
| `sync_weather.py` | 天气同步脚本（由 `.github/workflows/weather-sync.yml` 每小时在 GitHub Actions 执行并提交回仓库） |
| `.github/workflows/weather-sync.yml` | GitHub Actions 定时任务：每小时同步沙河口区天气并推送（可手动触发） |
| `lib/` | Leaflet 1.9.4 本地库（页面离线可用） |
| `小红书存档/` | 小红书笔记图文存档（分享短链匿名下载） |

## 线上访问

本仓库通过 GitHub Pages 发布，公网地址见仓库 Settings → Pages。
手机上直接打开该地址即可实时查看地图与行程（底图瓦片需联网）。

## 天气更新流程（GitHub Actions）

1. 仓库内 `.github/workflows/weather-sync.yml` 每小时自动运行 `sync_weather.py`，刷新 `大连天气-2小时预报.md` 与 `大连天气-同步日志.md` 并提交推送；
2. 也可在 GitHub 仓库 Actions 页面手动触发 `workflow_dispatch`；
3. 页面总览会显示最新更新时间；如需本地手动刷一次，可执行：

```bash
python3 sync_weather.py
```

> 数据源：中国天气网/中央气象台（weather.com.cn，大连·沙河口区 101070210，对应酒店西安路/联合路一带）；Open-Meteo 仅作对照附注。
