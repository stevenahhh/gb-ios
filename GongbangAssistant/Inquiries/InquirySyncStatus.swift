import SwiftUI
import RoundupCore

/// Shared feedback stays visible on every screen whose counts come from inquiries.
struct InquirySyncStatus: View {
    @Environment(DemoStore.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if store.isSample {
                Label("샘플 문의 · 서버에 저장하지 않아요", systemImage: "testtube.2")
            } else if store.isLoadingInquiries {
                ProgressView("서버 문의를 불러오는 중이에요")
            } else if let error = store.inquiryLoadError {
                Label(error, systemImage: "exclamationmark.circle")
                Text(store.hasLoadedInquiries ? "건수는 마지막으로 확인한 값이에요." : "아직 문의 건수를 확인하지 못했어요.")
                retry
            } else if store.requiresInquiryReload {
                Label("저장 결과를 확인해야 해요. 서버 문의를 다시 불러와 주세요.", systemImage: "arrow.clockwise")
                retry
            }
        }
        .font(.subheadline)
        .padding(.horizontal)
        .background(.bar)
        .accessibilityIdentifier("inquiry.sync")
    }

    private var retry: some View {
        Button("문의 다시 불러오기") {
            Task { await store.loadInquiries() }
        }
        .buttonStyle(.bordered)
        .controlSize(.large)
        .disabled(store.isInquiryBusy)
        .accessibilityIdentifier("inquiry.reload")
    }
}
