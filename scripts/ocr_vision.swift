import Foundation
import Vision
import AppKit

struct OCRResult: Codable {
    let file: String
    let text: String
    let error: String?
}

func recognize(path: String) -> OCRResult {
    guard let image = NSImage(contentsOfFile: path),
          let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        return OCRResult(file: path, text: "", error: "failed_to_load_image")
    }

    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = false
    request.recognitionLanguages = ["zh-Hans", "en-US"]

    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
    do {
        try handler.perform([request])
        let lines = (request.results ?? []).compactMap { observation in
            observation.topCandidates(1).first?.string
        }
        return OCRResult(file: path, text: lines.joined(separator: "\n"), error: nil)
    } catch {
        return OCRResult(file: path, text: "", error: String(describing: error))
    }
}

let encoder = JSONEncoder()
encoder.outputFormatting = [.withoutEscapingSlashes]

for path in CommandLine.arguments.dropFirst() {
    let result = recognize(path: path)
    if let data = try? encoder.encode(result),
       let line = String(data: data, encoding: .utf8) {
        print(line)
    }
}
