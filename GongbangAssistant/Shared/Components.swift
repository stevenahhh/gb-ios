import SwiftUI

struct MetricStrip: View {
    let metrics: [Metric]

    var body: some View {
        HStack(spacing: 0) {
            ForEach(Array(metrics.enumerated()), id: \.element.id) { index, metric in
                if index > 0 {
                    Divider().frame(height: 32)
                }
                VStack(spacing: 2) {
                    Text(metric.value)
                        .font(.title3.bold())
                        .monospacedDigit()
                    Text(metric.label)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity)
                .accessibilityElement(children: .combine)
            }
        }
        .padding(.vertical, 4)
    }
}

struct TaskRow: View {
    let item: TaskItem

    var body: some View {
        HStack(spacing: 12) {
            Text(item.leading)
                .font(.subheadline.monospacedDigit())
                .foregroundStyle(.secondary)
                .frame(width: 48, alignment: .leading)
            Image(systemName: "calendar")
                .foregroundStyle(.secondary)
                .frame(width: 36, height: 36)
                .background(.fill.tertiary, in: .rect(cornerRadius: 8))
            VStack(alignment: .leading, spacing: 2) {
                Text(item.title)
                    .font(.body.weight(.medium))
                Text(item.detail)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 8)
            if let isDone = item.isDone {
                Image(systemName: isDone ? "checkmark.circle.fill" : "circle")
                    .font(.title3)
                    .foregroundStyle(isDone ? AnyShapeStyle(.green) : AnyShapeStyle(.tertiary))
                    .accessibilityLabel(isDone ? "완료" : "미완료")
            } else if let badge = item.badge {
                StatusBadge(badge)
            }
        }
    }
}

struct WorkCard: View {
    let item: WorkItem

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline) {
                Text(item.title)
                    .font(.headline)
                Spacer(minLength: 8)
                if let status = item.status {
                    StatusBadge(status)
                }
            }
            ForEach(item.lines, id: \.self) { line in
                Text(line)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            if let action = item.action {
                Button {} label: {
                    Text(action)
                        .font(.subheadline.weight(.semibold))
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.glassProminent)
                .padding(.top, 4)
            }
        }
        .padding(.vertical, 4)
    }
}

struct StatusBadge: View {
    let text: String

    init(_ text: String) {
        self.text = text
    }

    var body: some View {
        Text(text)
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 7)
            .padding(.vertical, 3)
            .foregroundStyle(tint)
            .background(tint.opacity(0.14), in: .capsule)
    }

    private var tint: Color {
        switch text {
        case "확정", "결제 완료", "연결됨": .green
        case "예약금 대기", "포장 대기", "송장 대기": .orange
        case "처리 중", "배송 중", "초안 준비": .blue
        default: .secondary
        }
    }
}

struct AgendaRow: View {
    let item: AgendaItem

    var body: some View {
        HStack(spacing: 12) {
            Text(item.time)
                .font(.subheadline.monospacedDigit())
                .foregroundStyle(.secondary)
                .frame(width: 48, alignment: .leading)
            Capsule()
                .fill(item.kind.color)
                .frame(width: 4, height: 34)
            VStack(alignment: .leading, spacing: 2) {
                Text(item.title)
                    .font(.body.weight(.semibold))
                Text(item.detail)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 8)
            Text(item.kind.rawValue)
                .font(.caption.weight(.semibold))
                .padding(.horizontal, 10)
                .padding(.vertical, 4)
                .foregroundStyle(item.kind.color)
                .background(item.kind.color.opacity(0.12), in: .rect(cornerRadius: 6))
        }
    }
}

struct PlaceholderScreen: View {
    let title: String
    let systemImage: String

    var body: some View {
        ContentUnavailableView(title, systemImage: systemImage, description: Text("아직 디자인이 없는 화면이에요."))
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
    }
}
