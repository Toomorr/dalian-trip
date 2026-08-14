// 屏幕文字 OCR：用 macOS Vision 框架识别截图中的文字并输出屏幕坐标（点）。
// 用法：swift ocr_screen.swift <图片路径>
// 输出：JSON 数组 [{"text":"...","x":..,"y":..,"w":..,"h":..}]，坐标为主屏左上角原点（与 cliclick 一致）。

import AppKit
import Vision
import CoreGraphics
import Foundation

guard CommandLine.arguments.count > 1,
      let img = NSImage(contentsOfFile: CommandLine.arguments[1]),
      let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    FileHandle.standardError.write("无法读取图片\n".data(using: .utf8)!)
    exit(1)
}

// 主屏逻辑尺寸（点）
let displayBounds = CGDisplayBounds(CGMainDisplayID())
let scaleX = CGFloat(cg.width) / displayBounds.width
let scaleY = CGFloat(cg.height) / displayBounds.height

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.usesLanguageCorrection = true

let handler = VNImageRequestHandler(cgImage: cg, options: [:])
do {
    try handler.perform([request])
} catch {
    FileHandle.standardError.write("OCR 失败：\(error)\n".data(using: .utf8)!)
    exit(1)
}

var out: [[String: Any]] = []
for obs in request.results ?? [] {
    guard let candidate = obs.topCandidates(1).first else { continue }
    let b = obs.boundingBox  // 归一化，原点左下
    let cx = (b.midX) * CGFloat(cg.width) / scaleX
    let cy = (1.0 - b.midY) * CGFloat(cg.height) / scaleY
    let w = b.width * CGFloat(cg.width) / scaleX
    let h = b.height * CGFloat(cg.height) / scaleY
    out.append([
        "text": candidate.string,
        "x": cx,
        "y": cy,
        "w": w,
        "h": h,
    ])
}
if let data = try? JSONSerialization.data(withJSONObject: out, options: []),
   let s = String(data: data, encoding: .utf8) {
    print(s)
}
