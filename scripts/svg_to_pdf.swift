import AppKit
import CoreGraphics
import Foundation

if CommandLine.arguments.count != 3 {
    fputs("usage: svg_to_pdf input.svg output.pdf\n", stderr)
    exit(2)
}

let input = CommandLine.arguments[1]
let output = CommandLine.arguments[2]

guard let image = NSImage(contentsOfFile: input) else {
    fputs("Unable to load SVG: \(input)\n", stderr)
    exit(1)
}

let size = image.size
var mediaBox = CGRect(x: 0, y: 0, width: size.width, height: size.height)
guard let context = CGContext(URL(fileURLWithPath: output) as CFURL, mediaBox: &mediaBox, nil) else {
    fputs("Unable to create PDF: \(output)\n", stderr)
    exit(1)
}

context.beginPDFPage(nil)
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: false)
image.draw(in: CGRect(origin: .zero, size: size))
NSGraphicsContext.restoreGraphicsState()
context.endPDFPage()
context.closePDF()
