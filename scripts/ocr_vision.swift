import AppKit
import Foundation
import Vision

if CommandLine.arguments.count < 2 {
    fputs("usage: ocr_vision image...\n", stderr)
    exit(2)
}

for path in CommandLine.arguments.dropFirst() {
    autoreleasepool {
        guard let image = NSImage(contentsOfFile: path),
              let tiff = image.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff),
              let cgImage = bitmap.cgImage else {
            print("FILE\t\(path)\tERROR\tcannot_load")
            return
        }

        let request = VNRecognizeTextRequest { request, error in
            if let error = error {
                print("FILE\t\(path)\tERROR\t\(error.localizedDescription)")
                return
            }
            let observations = request.results as? [VNRecognizedTextObservation] ?? []
            let lines = observations.compactMap { $0.topCandidates(1).first?.string }
            print("FILE\t\(path)")
            print(lines.joined(separator: "\n"))
            print("END_FILE\t\(path)")
        }
        request.recognitionLevel = .accurate
        request.recognitionLanguages = ["zh-Hans", "en-US"]
        request.usesLanguageCorrection = true

        let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
        do {
            try handler.perform([request])
        } catch {
            print("FILE\t\(path)\tERROR\t\(error.localizedDescription)")
        }
    }
}
