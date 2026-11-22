import SwiftUI
import UIKit

extension CardSection where Header == EmptyView {
    init(@ViewBuilder content: () -> Content, @ViewBuilder footer: () -> Footer) {
        self.init(content: content, header: { EmptyView() }, footer: footer)
    }
}

/// One failed request, worded in place so typed text stays.
struct BK06ErrorRow: View {
    let message: String

    var body: some View {
        Label { Text(verbatim: message) } icon: { Image(systemName: "exclamationmark.circle") }
            .font(.subheadline)
            .foregroundStyle(Color.secondaryText)
            .accessibilityIdentifier("k06.error")
    }
}

/// The screen's one prominent action.
struct BK06PrimaryButton: View {
    let title: String
    var isBusy = false
    let identifier: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            BusyLabel(title: title, isBusy: isBusy, isProminent: true)
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.borderedProminent)
        .controlSize(.large)
        .disabled(isBusy)
        .accessibilityIdentifier(identifier)
    }
}

/// A value row that stacks at accessibility sizes.
struct BK06ValueRow: View {
    let label: String
    let value: String
    var tag: String?

    var body: some View {
        LabeledContent {
            VStack(alignment: .trailing, spacing: 2) {
                Text(verbatim: value).foregroundStyle(Color.primary)
                if let tag {
                    Text(verbatim: tag).font(.subheadline).foregroundStyle(Color.secondaryText)
                }
            }
        } label: {
            Text(verbatim: label)
        }
    }
}

/// The dot that marks something the owner still has to decide.
struct BK06PendingLabel: View {
    let text: String

    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(Color.pendingOrange).frame(width: 8, height: 8).accessibilityHidden(true)
            Text(verbatim: text).font(.subheadline)
        }
    }
}

struct BK06Disclaimer: View {
    var body: some View { Text("앱이 계산한 금액은 참고용이며 법률 자문이 아닙니다.") }
}

/// A fixed message the owner copies and sends from their own channel.
struct BK06CopyableDraft: View {
    let name: String
    let text: String
    @Environment(AppModel.self) private var app

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(verbatim: text).textSelection(.enabled)
            Button("\(name) 님께 보낼 문장 복사", systemImage: "doc.on.doc") {
                UIPasteboard.general.string = text
                app.showToast("복사했어요. 쓰시는 채널에서 보내 주세요", seconds: 3)
            }
            .buttonStyle(.bordered)
        }
        .padding(.vertical, 4)
    }
}
