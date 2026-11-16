import SwiftUI

struct CalendarScreen: View {
    enum Mode: String, CaseIterable, Identifiable {
        case month = "월간"
        case week = "주간"
        var id: Self { self }
    }

    @State private var mode: Mode = .month
    @State private var selectedDay = SampleData.today.day ?? 4

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Picker("보기", selection: $mode) {
                        ForEach(Mode.allCases) { Text($0.rawValue).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    .listRowInsets(EdgeInsets())
                    .listRowBackground(Color.clear)
                }

                Section {
                    switch mode {
                    case .month:
                        MonthCalendarView(selectedDay: $selectedDay, events: SampleData.novemberEvents)
                    case .week:
                        WeekStrip(selectedDay: $selectedDay, events: SampleData.novemberEvents)
                    }
                } header: {
                    if mode == .week {
                        Text("11월 2일 – 8일")
                    }
                } footer: {
                    EventLegend()
                }

                Section {
                    let items = SampleData.agenda[selectedDay] ?? []
                    if items.isEmpty {
                        Text("일정이 없어요")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(items) { AgendaRow(item: $0) }
                    }
                } header: {
                    HStack {
                        Text(dayTitle)
                        Spacer()
                        Text("일정 \((SampleData.agenda[selectedDay] ?? []).count)개")
                    }
                }
            }
            .listStyle(.insetGrouped)
            .navigationTitle("캘린더")
            .navigationSubtitle("공방의 모든 일정을 한눈에 확인하세요")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("오늘") {
                        selectedDay = SampleData.today.day ?? 4
                    }
                }
                ToolbarSpacer(.fixed, placement: .topBarTrailing)
                ToolbarItem(placement: .topBarTrailing) {
                    Button("일정 추가", systemImage: "plus") {}
                }
            }
        }
    }

    private var dayTitle: String {
        var components = SampleData.today
        components.day = selectedDay
        guard let date = components.date else { return "" }
        return date.formatted(.dateTime.month().day().weekday(.wide).locale(Locale(identifier: "ko_KR")))
    }
}

struct WeekStrip: View {
    @Binding var selectedDay: Int
    let events: [Int: [EventKind]]

    private let days = Array(2...8)
    private let weekdays = ["월", "화", "수", "목", "금", "토", "일"]

    var body: some View {
        HStack(spacing: 0) {
            ForEach(days, id: \.self) { day in
                let isSelected = day == selectedDay
                Button {
                    selectedDay = day
                } label: {
                    VStack(spacing: 6) {
                        Text(weekdays[day - days[0]])
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text("\(day)")
                            .font(.body.weight(isSelected ? .bold : .regular))
                            .monospacedDigit()
                            .foregroundStyle(isSelected ? Color(.systemBackground) : .primary)
                            .frame(width: 36, height: 36)
                            .background {
                                if isSelected {
                                    Circle().fill(.tint)
                                }
                            }
                        HStack(spacing: 2) {
                            ForEach(events[day] ?? []) { kind in
                                Circle().fill(kind.color).frame(width: 5, height: 5)
                            }
                        }
                        .frame(height: 5)
                    }
                    .frame(maxWidth: .infinity)
                    .contentShape(.rect)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("11월 \(day)일")
            }
        }
        .padding(.vertical, 6)
    }
}

struct EventLegend: View {
    var body: some View {
        HStack(spacing: 14) {
            ForEach(EventKind.allCases) { kind in
                HStack(spacing: 4) {
                    Circle().fill(kind.color).frame(width: 7, height: 7)
                    Text(kind.rawValue)
                }
            }
        }
        .font(.caption)
    }
}

#Preview {
    CalendarScreen()
}
