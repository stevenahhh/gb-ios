import SwiftUI
import UIKit

/// Values the owner checks before a PDF exists. Contact, account, and manager stay on the device.
struct OutreachSheetDetails {
    var shopName = ""
    var phone = ""
    var account = ""
    var manager = ""
    var preparation = ""
    var payment = "계좌로 입금"
    var vat = OutreachVat.unknown
}

/// The A4 page itself. Print always uses black on white.
struct OutreachSheetPage: View {
    static let size = CGSize(width: 595, height: 842)
    let quote: OutreachQuote
    let details: OutreachSheetDetails

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("출장 수업 견적서").font(.system(size: 24, weight: .bold))
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(verbatim: details.shopName).fontWeight(.semibold)
                    if !details.phone.isEmpty { Text(verbatim: "연락처 \(details.phone)") }
                }
                Spacer()
                Text(verbatim: "\(OutreachFormat.dayText(Date.now.dayKey)) 작성")
            }
            Divider()
            table([
                ("기관", quote.fields.orgName ?? quote.fields.orgType.label),
                ("담당자", details.manager),
                ("수업", quote.classId),
                ("일시", [quote.fields.date.map(OutreachFormat.dayText) ?? quote.fields.dateText, quote.fields.timeRange]
                    .compactMap { $0 }.joined(separator: " ")),
                ("장소", quote.fields.locationText ?? ""),
                ("인원", "\(quote.inputs.headcount)명"),
            ])
            Divider()
            Text("금액 내역").fontWeight(.semibold)
            table(quote.calculation.lines.map { ($0.label, OutreachFormat.won($0.amountKrw)) })
            table([
                ("총액", OutreachFormat.won(quote.calculation.totalKrw)),
                ("1인당 가격", OutreachFormat.won(quote.calculation.perPersonKrw)),
                ("부가세", details.vat == .unknown ? "" : details.vat.label),
            ])
            .fontWeight(.semibold)
            if !quote.calculation.tierPrices.isEmpty {
                Divider()
                Text("인원에 따른 1인 가격").fontWeight(.semibold)
                table(quote.calculation.tierPrices.map { ("\($0.headcount)명", OutreachFormat.won($0.perPersonKrw)) })
            }
            Divider()
            table([
                ("날짜 변경, 취소는 언제까지", quote.changeDeadline.map(OutreachFormat.dayText) ?? ""),
                ("준비물", details.preparation),
                ("입금 방식", details.payment),
                ("계좌", details.account),
            ])
            Spacer(minLength: 0)
        }
        .font(.system(size: 12))
        .padding(40)
        .frame(width: Self.size.width, height: Self.size.height, alignment: .topLeading)
        .foregroundStyle(.black)
        .background(.white)
        .environment(\.colorScheme, .light)
        .environment(\.dynamicTypeSize, .large)
    }

    private func table(_ rows: [(String, String)]) -> some View {
        Grid(alignment: .leadingFirstTextBaseline, horizontalSpacing: 18, verticalSpacing: 5) {
            ForEach(rows.filter { !$0.1.isEmpty }, id: \.0) { label, value in
                GridRow {
                    Text(verbatim: label).frame(width: 110, alignment: .leading)
                    Text(verbatim: value).monospacedDigit()
                }
            }
        }
    }

    /// Writes the page to a temporary file on the device; nothing is uploaded.
    static func render(_ quote: OutreachQuote, details: OutreachSheetDetails) -> URL? {
        let url = FileManager.default.temporaryDirectory.appending(path: "출장 수업 견적서 \(quote.id.suffix(6)).pdf")
        let renderer = ImageRenderer(content: OutreachSheetPage(quote: quote, details: details))
        var box = CGRect(origin: .zero, size: size)
        guard let context = CGContext(url as CFURL, mediaBox: &box, nil) else { return nil }
        renderer.render { _, draw in
            context.beginPDFPage(nil)
            draw(context)
            context.endPDFPage()
        }
        context.closePDF()
        return url
    }
}

struct OutreachPDFPreview: View {
    let quote: OutreachQuote
    let onShared: (Int?) -> Void
    let startedAt: () -> Date?
    @State private var details = OutreachSheetDetails()
    @State private var hasChecked = false
    @State private var file: OutreachPDFFile?
    @State private var errorMessage: String?
    @AppStorage("outreach.account") private var account = ""
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                if quote.locked {
                    CardSection {
                        Label("기관 정보를 확인하셔야 내보낼 수 있어요", systemImage: "lock")
                            .accessibilityIdentifier("outreach.locked")
                    }
                }
                CardSection {
                    page
                }
                CardSection {
                    field("연락처", $details.phone)
                    field("계좌", $details.account)
                    field("담당자 이름", $details.manager)
                    field("준비물", $details.preparation)
                    field("입금 방식", $details.payment)
                    Picker("부가세 적는 방식", selection: $details.vat) {
                        ForEach(OutreachVat.allCases) { Text($0.label).tag($0) }
                    }
                    Toggle("전화번호와 입금 계좌, 둘 다 봤어요", isOn: $hasChecked)
                        .accessibilityIdentifier("outreach.checked")
                } header: {
                    Text("견적서에 들어갈 정보")
                } footer: {
                    Text("여기에 쓰신 정보는 이 아이폰에만 남아요.")
                }
                CardSection {
                    if let errorMessage { Label(errorMessage, systemImage: "exclamationmark.circle") }
                    Button(action: export) {
                        BusyLabel(title: "PDF 파일로 저장", isBusy: false, isProminent: true)
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .disabled(quote.locked || !hasChecked)
                    .accessibilityIdentifier("outreach.export")
                }
            }
            .cardList()
            .navigationTitle("견적서 먼저 보기")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("닫기") { dismiss() } }
            }
            .sheet(item: $file) { file in
                OutreachShareSheet(url: file.url) { completed in
                    guard completed else { return }
                    account = details.account
                    onShared(startedAt().map { max(0, Int(Date.now.timeIntervalSince($0))) })
                }
            }
        }
        .task { await prepare() }
    }

    private var page: some View {
        GeometryReader { proxy in
            let scale = proxy.size.width / OutreachSheetPage.size.width
            OutreachSheetPage(quote: quote, details: details)
                .scaleEffect(scale, anchor: .topLeading)
        }
        .aspectRatio(OutreachSheetPage.size.width / OutreachSheetPage.size.height, contentMode: .fit)
        .clipShape(.rect)
        .listRowInsets(EdgeInsets())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("보내기 전에 견적서 보기, 합계 \(OutreachFormat.won(quote.calculation.totalKrw))")
    }

    private func field(_ title: String, _ value: Binding<String>) -> some View {
        LabeledContent(title) {
            TextField("입력", text: value)
                .multilineTextAlignment(.trailing)
                .accessibilityLabel(title)
        }
    }

    private func prepare() async {
        details.vat = quote.fields.budgetVat
        details.account = account
        if let workshop = try? await RoundupAPI.settings().workshop {
            details.shopName = workshop.name
            details.phone = workshop.phone
        }
    }

    private func export() {
        if let url = OutreachSheetPage.render(quote, details: details) {
            errorMessage = nil
            file = OutreachPDFFile(url: url)
        } else {
            errorMessage = "PDF 파일을 못 만들었어요. 조금 있다가 한 번 더 눌러 주세요."
        }
    }
}

private struct OutreachPDFFile: Identifiable {
    let url: URL
    var id: URL { url }
}

/// The system share sheet, which alone reports whether the owner really shared the file.
private struct OutreachShareSheet: UIViewControllerRepresentable {
    let url: URL
    let onFinish: (Bool) -> Void

    func makeUIViewController(context: Context) -> UIActivityViewController {
        let controller = UIActivityViewController(activityItems: [url], applicationActivities: nil)
        controller.completionWithItemsHandler = { _, completed, _, _ in onFinish(completed) }
        return controller
    }

    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}
