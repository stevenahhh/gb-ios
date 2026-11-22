import SwiftUI

/// Drawn because a native segmented picker cannot change its capsule corners.
struct TodaySegmentBar: View {
    @Binding var selection: TodaySegment
    @Namespace private var namespace
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private let trackRadius: CGFloat = 10
    private let selectedRadius: CGFloat = 8
    private let trackPadding: CGFloat = 2
    private let tapOutset: CGFloat = 4

    var body: some View {
        if dynamicTypeSize.isAccessibilitySize {
            Picker("보기", selection: $selection) {
                ForEach(TodaySegment.allCases) { segment in
                    Text(segment.rawValue).tag(segment)
                }
            }
            .pickerStyle(.menu)
            .accessibilityIdentifier("today.segment")
            .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
            .background(track)
        } else {
            HStack(spacing: 0) {
                ForEach(TodaySegment.allCases) { choice($0) }
            }
            .fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal, trackPadding)
            .background(track.padding(.vertical, tapOutset))
            .animation(reduceMotion ? nil : .snappy(duration: 0.2), value: selection)
            .accessibilityElement(children: .contain)
            .accessibilityLabel("보기")
            .accessibilityIdentifier("today.segment")
        }
    }

    private func choice(_ segment: TodaySegment) -> some View {
        let isSelected = segment == selection
        return Button {
            selection = segment
        } label: {
            Text(segment.rawValue)
                .font(.subheadline.weight(isSelected ? .semibold : .medium))
                .foregroundStyle(.primary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 2)
                .padding(.vertical, tapOutset + trackPadding + 4)
                .frame(maxWidth: .infinity, minHeight: 44, maxHeight: .infinity)
                .background {
                    if isSelected {
                        RoundedRectangle(cornerRadius: selectedRadius, style: .continuous)
                            .fill(colorScheme == .dark ? Color(.systemGray2) : .white)
                            .shadow(color: .black.opacity(0.12), radius: 2, y: 1)
                            .padding(.vertical, tapOutset + trackPadding)
                            .matchedGeometryEffect(id: "selected", in: namespace)
                    }
                }
                .contentShape(.rect)
        }
        .buttonStyle(PressDimStyle())
        .accessibilityAddTraits(isSelected ? .isSelected : [])
        .accessibilityIdentifier("today.segment.\(segment)")
    }

    /// Opaque, so rows that scroll under the pinned bar never show through the system's translucent fill.
    private var track: some View {
        let shape = RoundedRectangle(cornerRadius: trackRadius, style: .continuous)
        return shape.fill(Color(.tertiarySystemFill))
            .background(AppPalette.listBackground, in: shape)
    }
}
