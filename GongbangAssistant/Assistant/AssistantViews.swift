import SwiftUI

struct AssistantAccessory: View {
    @Environment(\.tabViewBottomAccessoryPlacement) private var placement
    let open: () -> Void

    var body: some View {
        Button(action: open) {
            HStack(spacing: 10) {
                Image(systemName: "plus")
                    .foregroundStyle(.primary)
                Text("AI에게 물어보세요")
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                Spacer(minLength: 0)
                if placement != .inline {
                    Image(systemName: "mic")
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.horizontal, 16)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("assistant.accessory")
    }
}

struct AssistantSheet: View {
    @Environment(\.dismiss) private var dismiss
    @State private var message = ""

    var body: some View {
        NavigationStack {
            ContentUnavailableView(
                "무엇을 도와드릴까요?",
                systemImage: "sparkles",
                description: Text("예약, 주문, 배송, 홍보에 대해 물어보세요.")
            )
            .navigationTitle("비서")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("닫기", systemImage: "xmark") {
                        dismiss()
                    }
                }
            }
            .safeAreaInset(edge: .bottom) {
                HStack(spacing: 8) {
                    TextField("AI에게 물어보세요", text: $message)
                        .textFieldStyle(.plain)
                        .padding(.horizontal, 16)
                        .frame(minHeight: 44)
                        .glassEffect(.regular, in: .capsule)
                    Button("보내기", systemImage: "arrow.up") {}
                        .labelStyle(.iconOnly)
                        .buttonStyle(.glassProminent)
                        .buttonBorderShape(.circle)
                        .disabled(message.isEmpty)
                }
                .padding()
            }
        }
        .presentationDetents([.medium, .large])
    }
}
