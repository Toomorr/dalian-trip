// 列出指定进程的窗口（标题、位置、是否可见），用于定位 Selenium 打开的 Firefox 窗口。
// 用法：swift window_list.swift firefox

import CoreGraphics
import Foundation

let target = CommandLine.arguments.count > 1 ? CommandLine.arguments[1].lowercased() : "firefox"
let opts: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
guard let list = CGWindowListCopyWindowInfo(opts, kCGNullWindowID) as? [[String: Any]] else {
    exit(1)
}
var out: [[String: Any]] = []
for w in list {
    guard let owner = w[kCGWindowOwnerName as String] as? String,
          owner.lowercased().contains(target) else { continue }
    let bounds = w[kCGWindowBounds as String] as? [String: Any] ?? [:]
    let name = w[kCGWindowName as String] as? String ?? ""
    out.append([
        "number": w[kCGWindowNumber as String] as? Int ?? 0,
        "name": name,
        "x": bounds["X"] as? Double ?? 0,
        "y": bounds["Y"] as? Double ?? 0,
        "w": bounds["Width"] as? Double ?? 0,
        "h": bounds["Height"] as? Double ?? 0,
        "layer": w[kCGWindowLayer as String] as? Int ?? 0,
        "onscreen": w[kCGWindowIsOnscreen as String] as? Bool ?? false,
    ])
}
if let data = try? JSONSerialization.data(withJSONObject: out, options: [.prettyPrinted]),
   let s = String(data: data, encoding: .utf8) {
    print(s)
}
