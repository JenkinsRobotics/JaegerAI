import SwiftUI

private struct ChatTimelineAccessorySurfaceModifier: ViewModifier {
    @Environment(\.colorScheme) private var colorScheme

    let fallbackMaterial: Material
    let cornerRadius: CGFloat

    func body(content: Content) -> some View {
        content
            .background(
                Color(.secondarySystemBackground).opacity(colorScheme == .dark ? 0.28 : 0.48),
                in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            )
            .adaptiveGlass(
                .regular,
                isInteractive: false,
                fallbackMaterial: fallbackMaterial,
                in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            )
            .clipShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .stroke(Color(.separator).opacity(colorScheme == .dark ? 0.42 : 0.28), lineWidth: 0.5)
                    .allowsHitTesting(false)
            }
    }
}

private struct ChatTimelineAccessoryInsetSurfaceModifier: ViewModifier {
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    private var backgroundColor: Color {
        if reduceTransparency {
            return Color(.secondarySystemGroupedBackground)
        }

        return Color(.secondarySystemFill).opacity(0.72)
    }

    func body(content: Content) -> some View {
        content
            .background(
                backgroundColor,
                in: RoundedRectangle(cornerRadius: 9, style: .continuous)
            )
            .overlay {
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .stroke(Color(.separator).opacity(colorScheme == .dark ? 0.36 : 0.22), lineWidth: 0.5)
                    .allowsHitTesting(false)
            }
    }
}

extension View {
    func chatTimelineAccessorySurface(
        fallbackMaterial: Material,
        cornerRadius: CGFloat
    ) -> some View {
        modifier(ChatTimelineAccessorySurfaceModifier(
            fallbackMaterial: fallbackMaterial,
            cornerRadius: cornerRadius
        ))
    }

    func chatTimelineAccessoryInsetSurface() -> some View {
        modifier(ChatTimelineAccessoryInsetSurfaceModifier())
    }
}
