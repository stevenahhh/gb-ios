import SwiftUI

struct AgendaDetailView: View {
    let route: AgendaRoute
    @State private var loader = Loader<AgendaDetail>()
    @Environment(AppModel.self) private var app

    var body: some View {
        LoadableContent(loader: loader, retry: load) { detail in
            List {
                Section {
                    TaskRow(item: detail.item.task, kind: detail.item.kind)
                } header: {
                    SectionHeader(title: "\(detail.dateLabel) · \(detail.item.kind.label)")
                }
                linkedWork(detail)
            }
            .listStyle(.insetGrouped)
            .refreshable { await load() }
        }
        .navigationTitle("일정 상세")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: app.dataVersion) { await load() }
    }

    private func load() async {
        let route = route
        await loader.load { try await RoundupAPI.agendaDetail(route) }
    }

    @ViewBuilder
    private func linkedWork(_ detail: AgendaDetail) -> some View {
        switch route.target {
        case .session:
            Section {
                if detail.cards.isEmpty {
                    Text("아직 예약이 없어요")
                        .foregroundStyle(.secondary)
                }
                cards(detail.cards)
            } header: {
                SectionHeader(title: "이 수업의 예약 \(detail.cards.count)건", area: .bookings)
            }
        case .order, .shipment:
            Section {
                cards(detail.cards)
            } header: {
                SectionHeader(title: "주문과 배송", area: route.target == .order ? .orders : .deliveries)
            }
        case .task, .event:
            EmptyView()
        }
    }

    private func cards(_ items: [WorkItem]) -> some View {
        let primaryID = items.primaryActionID
        return ForEach(items) { WorkCard(item: $0, isPrimary: $0.id == primaryID) }
    }
}
