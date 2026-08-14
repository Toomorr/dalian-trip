# 小红书图文存档

目标：把行程规划中引用的小红书笔记（图片 + 文字）保存到本地，便于离线核对。

## 当前状态

- 工具：XHS-Downloader（开源，JoeanAmier），已安装于临时环境，脚本入口为 `../save_xhs.py`
- 原始链接（无 token）匿名访问：失败，返回 22KB 空壳页
- 2026-08-13 针对三条代表性笔记做了无登录尝试（见 `results.csv`）：
  移动端页面 / PC 页面 / 网页 API / XHS-Downloader / 互联网档案馆 / 搜狗索引 token
  —— 全部被登录墙或反爬拦截，拿到的是 22KB 空壳页，无正文、无图片
- ✅ 2026-08-13 验证成功：**手机 App 分享短链（xhslink.cn）无需登录即可匿名下载**
  示例：`http://xhslink.cn/o/AdW5Ew8uMnu` → 已保存到
  `Download/大连免费小众海滩攻略/`（5 张图 + 正文 md）

## 已验证的完成方式（无需 Cookie）

在小红书 App 里打开笔记 → 分享 → 复制链接（剪贴板形如
`【标题... http://xhslink.cn/o/XXXX 直达【小红书】...】`），把整段文字发过来即可，
程序自动提取短链并下载图文。短链解析后自带 xsec_token，匿名可访问。

## 计划目录结构

```
小红书存档/
  Download/<笔记ID>/   图片 + 标题.md（每条笔记一个文件夹）
  results.csv          每条链接的下载结果
```

## 如何完成下载

方式 A（推荐，已验证）：在小红书 App 里打开目标笔记 → 分享 → 复制链接
（形如 `http://xhslink.cn/o/XXXX`），把整段剪贴板内容粘到 `urls.txt`，然后运行：
`python save_xhs.py urls.txt --download`

方式 B（批量）：登录 xiaohongshu.com 网页版后，从浏览器开发者工具复制 Cookie，
执行 `XHS_COOKIE="..." python save_xhs.py urls.txt --download`，可处理不带 token 的链接。
