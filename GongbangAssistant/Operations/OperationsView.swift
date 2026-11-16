import SwiftUI

struct OperationsView: View {
    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack(spacing: 20) {
                        Gauge(value: 0.75) {
                            Text("처리율")
                        } currentValueLabel: {
                            Text("75%")
                        }
                        .gaugeStyle(.accessoryCircularCapacity)
                        .tint(.accentColor)

                        Grid(alignment: .leading, horizontalSpacing: 24, verticalSpacing: 8) {
                            GridRow {
                                summary("예약", "24건")
                                summary("주문", "8건")
                            }
                            GridRow {
                                summary("배송", "5건")
                                summary("SNS", "2개")
                            }
                        }
                    }
                    .padding(.vertical, 4)
                    HStack(spacing: 0) {
                        comparison("+12%")
                        Divider().frame(height: 36)
                        comparison("+5%")
                    }
                } header: {
                    HStack {
                        Text("11월 운영 현황")
                        Spacer()
                        Menu("11.01 – 11.30") {
                            Button("11월") {}
                            Button("10월") {}
                        }
                        .font(.footnote)
                        .textCase(nil)
                    }
                }

                Section {
                    HStack(alignment: .firstTextBaseline) {
                        Label {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("먼저 확인해주세요")
                                    .font(.headline)
                                Text("예약금 미확인 2 · 미답변 문의 3 · 발송 마감 2")
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                            }
                        } icon: {
                            Image(systemName: "exclamationmark.circle")
                                .foregroundStyle(.orange)
                        }
                        Spacer(minLength: 8)
                        StatusBadge("7건")
                    }
                } footer: {
                    Text("각 업무에서 확인하고 처리할 수 있어요.")
                }

                Section("전체 업무 관리") {
                    ForEach(OperationArea.allCases) { area in
                        NavigationLink(value: area) {
                            LabeledContent {
                                Text(area.count)
                                    .monospacedDigit()
                            } label: {
                                Label {
                                    Text(area.title)
                                    Text(area.summary)
                                } icon: {
                                    Image(systemName: area.systemImage)
                                }
                            }
                        }
                        .accessibilityIdentifier("operations.\(area.rawValue)")
                    }
                }
            }
            .listStyle(.insetGrouped)
            .navigationTitle("운영")
            .navigationSubtitle("예약부터 판매까지, 공방 업무를 한곳에서")
            .navigationDestination(for: OperationArea.self) { area in
                OperationAreaView(area: area)
            }
        }
    }

    private func comparison(_ change: String) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("전월 대비")
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(change)
                .font(.title2.bold())
                .monospacedDigit()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.leading, 4)
    }

    private func summary(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.headline)
                .monospacedDigit()
        }
    }
}

#Preview {
    OperationsView()
}
