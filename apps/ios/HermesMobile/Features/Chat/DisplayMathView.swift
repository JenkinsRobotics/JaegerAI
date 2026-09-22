import SwiftMath
import SwiftUI
import UIKit

/// Renders block/display LaTeX (`$$…$$`, `\[…\]`) with the SwiftMath TeX
/// layout engine when the expression parses, and falls back to the Unicode
/// approximation (`MarkdownMathFormatter`) for anything SwiftMath can't parse.
///
/// Tolerant by design: an unparseable or partial expression degrades to the
/// previous Unicode rendering instead of crashing or showing SwiftMath's
/// inline red error. The Unicode approximation is also used as the VoiceOver
/// label on both paths, so the drawn math stays accessible.
struct DisplayMathView: View {
    let latex: String

    @Environment(\.colorScheme) private var colorScheme
    @ScaledMetric(relativeTo: .body) private var mathFontSize: CGFloat = 18

    var body: some View {
        Group {
            if MathLaTeX.isRenderable(latex) {
                ScrollView(.horizontal, showsIndicators: false) {
                    SwiftMathLabelView(
                        latex: latex,
                        fontSize: mathFontSize,
                        colorScheme: colorScheme
                    )
                    .padding(.vertical, 8)
                }
            } else {
                fallback
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(approximation)
        .padding(.vertical, 2)
        // Math/LaTeX is read left-to-right regardless of the chat direction (#259);
        // mirroring it would reverse equations inside an RTL message.
        .forcedLeftToRight()
    }

    /// The pre-SwiftMath Unicode/serif rendering, kept verbatim as the graceful
    /// fallback for expressions SwiftMath cannot parse.
    private var fallback: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            Text(approximation)
                .font(.system(.body, design: .serif))
                .lineSpacing(4)
                .fixedSize(horizontal: true, vertical: true)
                .padding(.vertical, 8)
                .textSelection(.enabled)
        }
    }

    private var approximation: String {
        MarkdownMathFormatter.renderedText(for: latex)
    }
}

enum MathLaTeX {
    /// Renderability is a pure, deterministic function of the trimmed LaTeX
    /// string, so we memoize it. `DisplayMathView`/`MathFenceOrCodeBlock`
    /// re-check on every layout pass, and markdown-ui rebuilds code blocks on
    /// each streaming chunk — without this cache the same expression is parsed
    /// many times over. `NSCache` is thread-safe and self-evicts under memory
    /// pressure.
    nonisolated(unsafe) private static let renderableCache = NSCache<NSString, NSNumber>()

    /// True when SwiftMath can parse `latex` into a math list without error.
    /// Used to choose the SwiftMath path vs. the Unicode fallback before the
    /// `MTMathUILabel` is ever mounted, so failures never reach the screen.
    static func isRenderable(_ latex: String) -> Bool {
        let trimmed = latex.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }

        let key = trimmed as NSString
        if let cached = renderableCache.object(forKey: key) {
            return cached.boolValue
        }

        var error: NSError?
        let mathList = MTMathListBuilder.build(fromString: trimmed, error: &error)
        let renderable = error == nil && mathList != nil
        renderableCache.setObject(NSNumber(value: renderable), forKey: key)
        return renderable
    }
}

/// Fenced-code languages that should render as display math rather than source
/// code (e.g. ```math, ```latex, ```tex). Models sometimes wrap a standalone
/// equation in a math fence instead of `$$…$$`; those reach the renderer as a
/// code block, so we re-route the math ones (parity-plus over Hermes WebUI,
/// which shows these as code).
enum MathFenceLanguage {
    static let languages: Set<String> = ["math", "latex", "tex"]

    /// True when a fenced code block's info string names a math language.
    static func matches(_ language: String?) -> Bool {
        guard let normalized = MarkdownHighlightPolicy.normalizedLanguage(from: language) else {
            return false
        }
        return languages.contains(normalized)
    }
}

/// Wraps SwiftMath's `MTMathUILabel` (a UIKit view) for use in SwiftUI.
/// Sized to its intrinsic content so long equations scroll horizontally in the
/// surrounding `ScrollView` instead of clipping.
private struct SwiftMathLabelView: UIViewRepresentable {
    let latex: String
    let fontSize: CGFloat
    let colorScheme: ColorScheme

    func makeUIView(context: Context) -> MTMathUILabel {
        let label = MTMathUILabel()
        label.labelMode = .display
        label.textAlignment = .left
        // We pick the fallback view for unparseable input, so the inline red
        // error should never appear.
        label.displayErrorInline = false
        label.contentInsets = .zero
        configure(label)
        return label
    }

    func updateUIView(_ uiView: MTMathUILabel, context: Context) {
        configure(uiView)
    }

    func sizeThatFits(
        _ proposal: ProposedViewSize,
        uiView: MTMathUILabel,
        context: Context
    ) -> CGSize? {
        uiView.intrinsicContentSize
    }

    /// Applies the current inputs, skipping no-op writes so repeated SwiftUI
    /// updates (e.g. during streaming) don't force needless re-typesetting.
    private func configure(_ label: MTMathUILabel) {
        if label.fontSize != fontSize {
            label.fontSize = fontSize
        }

        let textColor = Self.resolvedTextColor(for: colorScheme)
        if label.textColor != textColor {
            label.textColor = textColor
        }

        if label.latex != latex {
            label.latex = latex
        }
    }

    /// Resolves the dynamic label color against the SwiftUI color scheme so the
    /// Core Graphics-drawn math matches the surrounding text in light and dark.
    private static func resolvedTextColor(for colorScheme: ColorScheme) -> MTColor {
        let style: UIUserInterfaceStyle = colorScheme == .dark ? .dark : .light
        return UIColor.label.resolvedColor(with: UITraitCollection(userInterfaceStyle: style))
    }
}
