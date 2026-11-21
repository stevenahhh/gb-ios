import SwiftUI

struct AppToast: Identifiable {
    let id = UUID()
    let message: String
    let seconds: Int
    let undo: (@MainActor () async -> Void)?
}

/// Covers the assistant bar for a moment instead of the list, so the changed row stays visible.
/// It leaves after its seconds; with VoiceOver or Switch Control an undo stays until it is used or dismissed.
struct ToastHost: View {
    @Environment(AppModel.self) private var app
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.accessibilityVoiceOverEnabled) private var isVoiceOverOn
    @State private var undoCount = 0

    var body: some View {
        GeometryReader { proxy in
            let window = proxy.frame(in: .global)
            if let toast = app.toast {
                let slot = slot(in: window)
                ToastBar(toast: toast, minHeight: slot.height, undo: undo, dismiss: { app.toast = nil })
                    .frame(width: slot.width)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
                    .padding(.leading, slot.minX - window.minX)
                    // A slot below the visible area means the keyboard covers the bar; then sit just above the keyboard.
                    .padding(.bottom, max(8, window.maxY - slot.maxY))
                    .transition(reduceMotion ? .opacity : .scale(scale: 0.94).combined(with: .opacity))
                    .task(id: toast.id) { await present(toast) }
            }
        }
        .ignoresSafeArea(.container)
        .animation(reduceMotion ? .easeInOut(duration: 0.2) : .spring(duration: 0.3), value: app.toast?.id)
        .sensoryFeedback(.impact(weight: .light), trigger: undoCount)
    }

    /// The assistant bar's own frame. Beside a minimized tab bar it is too narrow for a sentence, so the toast
    /// then takes a full-width row just above it.
    private func slot(in window: CGRect) -> CGRect {
        let row = CGRect(x: window.minX + 21, y: window.maxY - 139, width: window.width - 42, height: 48)
        guard let bar = app.accessorySlot else { return row }
        return bar.width >= 280 ? bar : row.offsetBy(dx: 0, dy: bar.minY - 8 - row.maxY)
    }

    private func undo(_ action: @escaping @MainActor () async -> Void) {
        undoCount += 1
        app.toast = nil
        Task { await action() }
    }

    private func present(_ toast: AppToast) async {
        AccessibilityNotification.Announcement(toast.undo == nil ? toast.message : "\(toast.message). 되돌리기 버튼이 있어요").post()
        if toast.undo != nil, isVoiceOverOn || UIAccessibility.isSwitchControlRunning { return }
        try? await Task.sleep(for: .seconds(toast.seconds))
        if app.toast?.id == toast.id { app.toast = nil }
    }
}

/// Black glass with white text in both appearances; 되돌리기 is a white pill concentric with the bar.
private struct ToastBar: View {
    let toast: AppToast
    let minHeight: CGFloat
    let undo: (@escaping @MainActor () async -> Void) -> Void
    let dismiss: () -> Void
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @GestureState private var pull = CGFloat.zero

    var body: some View {
        // At accessibility sizes the button moves under the message, so neither is squeezed to one letter per line.
        let isStacked = dynamicTypeSize.isAccessibilitySize
        let layout = isStacked ? AnyLayout(VStackLayout(alignment: .leading, spacing: 6)) : AnyLayout(HStackLayout(spacing: 8))
        layout {
            // Completion toasts carry the row's title; truncating its middle keeps the verb.
            Text(toast.message)
                .font(.subheadline.weight(.medium))
                .foregroundStyle(.white)
                .lineLimit(isStacked ? 3 : 1)
                .truncationMode(.middle)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.leading, 18)
                .padding(.trailing, toast.undo == nil || isStacked ? 18 : 0)
                .accessibilityAction(named: "닫기", dismiss)
                .accessibilityIdentifier("toast.message")
            if let action = toast.undo {
                Button {
                    undo(action)
                } label: {
                    Label("되돌리기", systemImage: "arrow.uturn.backward")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.black)
                        .lineLimit(1)
                        .padding(.horizontal, 14)
                        .frame(maxWidth: isStacked ? .infinity : nil, minHeight: 40, maxHeight: isStacked ? nil : .infinity)
                        .background(.white, in: .capsule)
                        .padding(4)
                        .contentShape(.rect)
                }
                .buttonStyle(PressDimStyle())
                .accessibilityIdentifier("toast.undo")
            }
        }
        .padding(.vertical, isStacked ? 10 : 0)
        .frame(minHeight: minHeight)
        .fixedSize(horizontal: false, vertical: true)
        .background {
            if reduceTransparency { RoundedRectangle(cornerRadius: 24, style: .continuous).fill(.black) }
        }
        // Radius 24 is a capsule at the bar's 48pt and a rounded card once the toast grows taller.
        .glassEffect(reduceTransparency ? .identity : .regular.tint(.black.opacity(0.9)), in: .rect(cornerRadius: 24))
        .offset(y: max(0, pull))
        .gesture(DragGesture(minimumDistance: 8)
            .updating($pull) { value, state, _ in state = value.translation.height }
            .onEnded { if $0.translation.height > 24 || $0.predictedEndTranslation.height > 80 { dismiss() } })
        .accessibilityElement(children: .contain)
        .accessibilityAction(.escape, dismiss)
        .accessibilityIdentifier("toast")
    }
}

/// Dims its label while pressed and does nothing else. Unlike `.plain` it does not fade a disabled label (that
/// fade measured about half), so a disabled pill or row can say so with its own gray and stay readable.
struct PressDimStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .opacity(configuration.isPressed ? 0.6 : 1)
    }
}

#Preview("알림 · 되돌리기") {
    @Previewable @State var app = AppModel()
    Color(.systemGroupedBackground)
        .ignoresSafeArea()
        .overlay { ToastHost() }
        .environment(app)
        .task { app.showToast("‘오롯 머그컵 2개 포장’ 완료했어요", seconds: 600) {} }
}

#Preview("알림 · 안내만") {
    @Previewable @State var app = AppModel()
    Color(.systemGroupedBackground)
        .ignoresSafeArea()
        .overlay { ToastHost() }
        .environment(app)
        .task { app.showToast("복사했어요", seconds: 600) }
}
