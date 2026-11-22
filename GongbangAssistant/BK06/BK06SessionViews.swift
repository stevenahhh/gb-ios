#if BUILD_B
import SwiftUI
import UIKit

struct BK06SessionListView: View {
    let sessions: [BK06SessionLine]

    var body: some View {
        List {
            CardSection {
                if sessions.isEmpty { Text("앞으로 2주 동안 잡힌 수업이 없어요").foregroundStyle(Color.secondaryText) }
                ForEach(sessions) { item in
                    NavigationLink { BK06SessionView(sessionID: item.sessionId) } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(verbatim: item.classTitle).font(.headline)
                            PhraseText(text: "\(item.schedule) · \(item.booked)/\(item.capacity)명")
                                .font(.subheadline)
                                .foregroundStyle(Color.secondaryText)
                        }
                    }
                    .accessibilityIdentifier("k06.session.\(item.sessionId)")
                }
            }
        }
        .cardList()
        .navigationTitle("출석 체크와 대기 손님")
        .navigationBarTitleDisplayMode(.inline)
    }
}

struct BK06SessionView: View {
    let sessionID: String
    @State private var loader = Loader<BK06SessionDetail>()
    @State private var isAddingGuest = false
    @State private var isPlanning = false
    @Environment(AppModel.self) private var app

    var body: some View {
        LoadableContent(loader: loader, retry: load) { detail in
            List {
                CardSection {
                    if detail.guests.isEmpty { Text("예약한 손님이 없어요").foregroundStyle(Color.secondaryText) }
                    ForEach(detail.guests) { guestRow($0) }
                } header: {
                    Text("\(detail.schedule) · \(detail.booked)/\(detail.capacity)명")
                } footer: {
                    Text("손님이 오시면 행을 눌러 주세요. 길게 누르면 규정 안내를 복사할 수 있어요.")
                }
                CardSection("자리를 기다리는 분") {
                    ForEach(detail.targets) { target in
                        BK06ValueRow(label: "\(target.name) 님", value: target.sourceText)
                            .swipeActions {
                                Button("빼기", role: .destructive) {
                                    act { try await RoundupAPI.k06RemoveWaiting(sessionID: sessionID, entryID: target.entryId) }
                                }
                            }
                    }
                    Button("기다리는 분 추가", systemImage: "plus") { isAddingGuest = true }
                        .accessibilityIdentifier("k06.addWaiting")
                }
                CardSection("최소 인원") {
                    if let seats = detail.minSeats { BK06ValueRow(label: "최소 인원", value: "\(seats)명") }
                    if let deadline = detail.materialOrderDeadline {
                        BK06ValueRow(label: "재료 발주 마감", value: BK06Format.when(deadline))
                    }
                    Button(detail.minSeats == nil ? "최소 인원을 정하면 미리 알려 드려요" : "고치기") { isPlanning = true }
                        .accessibilityIdentifier("k06.plan")
                }
            }
            .cardList()
            .sheet(isPresented: $isPlanning) {
                BK06PlanEditor(detail: detail) { seats, deadline, material in
                    act { try await RoundupAPI.k06SavePlan(
                        sessionID: sessionID, minSeats: seats, deadline: deadline, materialWon: material) }
                }
            }
        }
        .navigationTitle(loader.value?.classTitle ?? "수업")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: app.dataVersion) { await load() }
        .sheet(isPresented: $isAddingGuest) {
            BK06WaitingEditor { name, phone, isMakeup in
                act { try await RoundupAPI.k06AddWaiting(
                    sessionID: sessionID, name: name, phone: phone, isMakeup: isMakeup) }
            }
        }
    }

    private func load() async { await loader.load { try await RoundupAPI.k06Session(id: sessionID) } }

    private func act(_ operation: @escaping () async throws -> Void) {
        Task { await app.run(id: "k06.session.\(sessionID)", operation) }
    }

    private func guestRow(_ guest: BK06Guest) -> some View {
        Button {
            act {
                if guest.attendedAt == nil && guest.noShowAt == nil {
                    _ = try await RoundupAPI.k06Attendance(bookingID: guest.bookingId, arrived: true)
                } else {
                    try await RoundupAPI.k06UndoAttendance(bookingID: guest.bookingId)
                }
            }
        } label: {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("\(guest.customerName) 님 · \(guest.people)명").font(.headline)
                    Text(guest.noShowAt != nil ? "노쇼" : guest.attendedAt != nil ? "도착" : "아직 체크 없음")
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                }
                Spacer(minLength: 8)
                DoneMark(isDone: guest.attendedAt != nil)
            }
            .contentShape(.rect)
        }
        .foregroundStyle(Color.primary)
        .contextMenu {
            Button(guest.noticed ? "규정 안내 다시 복사" : "규정 안내 복사", systemImage: "doc.on.doc") { copyNotice(guest) }
        }
        .accessibilityIdentifier("k06.guest.\(guest.bookingId)")
    }

    private func copyNotice(_ guest: BK06Guest) {
        act {
            let notice = try await RoundupAPI.k06Notice(bookingID: guest.bookingId)
            UIPasteboard.general.string = notice.summary
            app.showToast("규정 \(notice.version)판 안내를 복사했어요", seconds: 3)
        }
    }
}

struct BK06PlanEditor: View {
    let onSave: (Int?, Date?, Int?) -> Void
    @State private var seats: Int
    @State private var deadline: Date
    @State private var material: String
    @Environment(\.dismiss) private var dismiss

    init(detail: BK06SessionDetail, onSave: @escaping (Int?, Date?, Int?) -> Void) {
        self.onSave = onSave
        _seats = State(initialValue: detail.minSeats ?? 2)
        let start = BK06Format.date(detail.startsAt) ?? .now
        _deadline = State(initialValue: detail.materialOrderDeadline.flatMap(BK06Format.date) ?? start.addingTimeInterval(-86_400))
        _material = State(initialValue: detail.materialWon.map(String.init) ?? "")
    }

    var body: some View {
        NavigationStack {
            List {
                CardSection {
                    Stepper("최소 \(seats)명", value: $seats, in: 1...100)
                    DatePicker("재료 발주 마감", selection: $deadline)
                    TextField("1인 재료비(원)", text: $material).keyboardType(.numberPad)
                }
            }
            .cardList()
            .navigationTitle("최소 인원")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("닫기") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("저장") {
                        onSave(seats, deadline, Int(material))
                        dismiss()
                    }
                }
            }
        }
    }
}

struct BK06WaitingEditor: View {
    let onSave: (String, String, Bool) -> Void
    @State private var name = ""
    @State private var phone = ""
    @State private var isMakeup = false
    @Environment(\.dismiss) private var dismiss

    private var trimmed: String { name.trimmingCharacters(in: .whitespaces) }

    var body: some View {
        NavigationStack {
            List {
                CardSection {
                    TextField("이름", text: $name)
                    TextField("전화번호(선택)", text: $phone).keyboardType(.phonePad)
                    Picker("구분", selection: $isMakeup) {
                        Text("대기를 부탁한 손님").tag(false)
                        Text("보강이 남은 수강생").tag(true)
                    }
                }
            }
            .cardList()
            .navigationTitle("기다리는 분")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("닫기") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("추가") {
                        onSave(trimmed, phone, isMakeup)
                        dismiss()
                    }
                    .disabled(trimmed.isEmpty)
                }
            }
        }
    }
}

struct BK06LateView: View {
    let bookingID: String
    @State private var loader = Loader<BK06Cards>()
    @State private var outcome: BK06Attendance?
    @State private var isBusy = false
    @State private var errorMessage: String?
    @Environment(AppModel.self) private var app
    @Environment(\.openURL) private var openURL

    var body: some View {
        LoadableContent(loader: loader, retry: load) { cards in
            if let draft = outcome?.draft, let card = cards.late.first(where: { $0.id == bookingID }) {
                List {
                    CardSection {
                        BK06CopyableDraft(name: card.customerName, text: draft)
                    } header: {
                        Text("노쇼로 기록했어요")
                    }
                }
                .cardList()
            } else if outcome == nil, let card = cards.late.first(where: { $0.id == bookingID }) {
                list(card)
            } else {
                ContentUnavailableView("이미 처리한 손님이에요", systemImage: "checkmark.circle",
                                       description: Text("도착이나 노쇼로 표시했거나 예약이 바뀌었어요."))
                    .accessibilityIdentifier("k06.late.done")
            }
        }
        .navigationTitle("지각 확인")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .onDisappear { if outcome != nil { app.dataDidChange() } }
    }

    private func load() async {
        guard outcome == nil else { return }
        await loader.load { try await RoundupAPI.k06Cards() }
    }

    private func list(_ card: BK06LateCard) -> some View {
        List {
            CardSection {
                VStack(alignment: .leading, spacing: 4) {
                    Text("\(card.customerName) 님이 아직 안 오셨어요").font(.headline)
                    PhraseText(text: "\(card.classTitle) · 시작 \(BK06Format.elapsed(card.minutesLate)) 지남")
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                }
                if let phone = card.phone, let url = URL(string: "tel:\(phone.filter(\.isNumber))") {
                    Button("전화하기", systemImage: "phone") { openURL(url) }
                        .buttonStyle(.bordered)
                }
            }
            CardSection("확인 메시지") {
                BK06CopyableDraft(name: card.customerName, text: card.draft)
            }
            CardSection {
                if let errorMessage { BK06ErrorRow(message: errorMessage) }
                Button("도착") { mark(arrived: true) }
                    .buttonStyle(.bordered)
                    .disabled(isBusy)
                    .accessibilityIdentifier("k06.arrived")
                BK06PrimaryButton(title: "노쇼로 기록", isBusy: isBusy, identifier: "k06.noShow") { mark(arrived: false) }
            } footer: {
                Text("노쇼 기록은 우리 공방에서만 보여요. 예약금은 앱이 옮기지 않아요.")
            }
        }
        .cardList()
    }

    private func mark(arrived: Bool) {
        isBusy = true
        errorMessage = nil
        Task {
            do {
                outcome = try await RoundupAPI.k06Attendance(bookingID: bookingID, arrived: arrived)
                app.showToast(arrived ? "도착으로 표시했어요" : "노쇼로 기록했어요") {
                    await app.run(id: "k06.undoAttendance") { try await RoundupAPI.k06UndoAttendance(bookingID: bookingID) }
                }
            } catch {
                errorMessage = error.localizedDescription
            }
            isBusy = false
        }
    }
}

struct BK06RefillView: View {
    let sessionID: String
    @State private var loader = Loader<BK06Refill>()
    @State private var chosen: String?
    @Environment(AppModel.self) private var app

    var body: some View {
        LoadableContent(loader: loader, retry: load) { refill in
            List {
                CardSection {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(verbatim: refill.classTitle).font(.headline)
                        PhraseText(text: "\(BK06Format.when(refill.startsAt)) · \(BK06Format.remaining(refill.startsInMinutes))")
                            .font(.subheadline)
                            .foregroundStyle(refill.startsInMinutes <= 0 ? Color.overdueRed : Color.secondaryText)
                    }
                    BK06ValueRow(label: "빈 자리", value: "\(refill.openSeats)개")
                }
                if refill.targets.isEmpty {
                    CardSection {
                        Text("제안할 분이 없어요").accessibilityIdentifier("k06.refill.empty")
                        NavigationLink("기다리는 분 추가하러 가기") { BK06SessionView(sessionID: sessionID) }
                    } footer: {
                        Text("대기를 부탁한 손님이나 보강이 남은 수강생을 적어 두면 여기에 순서대로 보여요.")
                    }
                } else {
                    offers(refill)
                }
            }
            .cardList()
        }
        .navigationTitle("빈자리")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: app.dataVersion) { await load() }
    }

    private func load() async { await loader.load { try await RoundupAPI.k06Refill(sessionID: sessionID) } }

    @ViewBuilder
    private func offers(_ refill: BK06Refill) -> some View {
        let target = refill.targets.first { $0.id == chosen } ?? refill.targets[0]
        CardSection("제안할 순서") {
            ForEach(Array(refill.targets.enumerated()), id: \.element.id) { index, item in
                Button { chosen = item.id } label: {
                    HStack(spacing: 10) {
                        BK06ValueRow(label: "\(index + 1). \(item.name) 님", value: item.sourceText)
                        if item.id == target.id {
                            Image(systemName: "checkmark").accessibilityLabel("선택함")
                        }
                    }
                    .contentShape(.rect)
                }
                .foregroundStyle(Color.primary)
            }
        }
        CardSection {
            Text(verbatim: target.draft).textSelection(.enabled)
            BK06PrimaryButton(title: target.id == refill.targets[0].id ? "첫 번째 분께 보낼 초안 복사" : "\(target.name) 님께 보낼 초안 복사",
                              identifier: "k06.refill.copy") {
                UIPasteboard.general.string = target.draft
                app.showToast("복사했어요. 쓰시는 채널에서 보내 주세요", seconds: 3)
            }
        } header: {
            Text("제안 초안")
        } footer: {
            Text("한 분씩 보내고 답을 기다려 주세요. 수락하시면 예약 등록에서 자리를 채워 주세요.")
        }
    }
}

struct BK06UnderMinView: View {
    let card: BK06UnderMinCard
    @State private var decision = "run"
    @State private var mergeInto: String?
    @State private var drafts: [BK06GuestDraft]?
    @State private var isBusy = false
    @State private var isConfirming = false
    @State private var errorMessage: String?
    @Environment(AppModel.self) private var app

    var body: some View {
        List {
            CardSection {
                VStack(alignment: .leading, spacing: 4) {
                    Text(verbatim: card.className).font(.headline)
                    Text(verbatim: BK06Format.when(card.startsAt)).font(.subheadline).foregroundStyle(Color.secondaryText)
                }
                BK06ValueRow(label: "예약", value: "\(card.booked)명", tag: "최소 \(card.minSeats)명")
                BK06ValueRow(label: "재료 발주 마감", value: BK06Format.when(card.orderDeadline))
                if let material = card.materialWon {
                    BK06ValueRow(label: "예약 인원 재료비", value: BK06Format.won(material), tag: "추정")
                }
            }
            if let drafts {
                CardSection("안내 초안") {
                    if drafts.isEmpty { Text("안내할 손님이 없어요") }
                    ForEach(drafts) { BK06CopyableDraft(name: $0.customerName, text: $0.draft) }
                }
            } else {
                choices
            }
        }
        .cardList()
        .navigationTitle("인원 미달")
        .navigationBarTitleDisplayMode(.inline)
        .confirmationDialog(decision == "merge" ? "이 회차 예약을 옮길까요?" : "이번 회차를 취소할까요?",
                            isPresented: $isConfirming, titleVisibility: .visible) {
            Button(decision == "merge" ? "합치고 초안 만들기" : "취소하고 초안 만들기", role: .destructive) { decide() }
        } message: {
            Text("앱에서 되돌릴 수 없어요. 손님에게는 아무것도 보내지 않아요.")
        }
        .onDisappear { if drafts != nil { app.dataDidChange() } }
    }

    private var choices: some View {
        CardSection {
            Picker("진행 방식", selection: $decision) {
                Text("그대로 진행").tag("run")
                if !card.mergeCandidates.isEmpty { Text("다른 회차와 합치기").tag("merge") }
                Text("이번 회차 취소").tag("cancel")
            }
            .accessibilityIdentifier("k06.underMin.decision")
            if decision == "merge" {
                Picker("합칠 회차", selection: $mergeInto) {
                    Text("골라 주세요").tag(String?.none)
                    ForEach(card.mergeCandidates) { option in
                        Text("\(BK06Format.when(option.startsAt)) · 남은 자리 \(option.openSeats)개").tag(Optional(option.sessionId))
                    }
                }
            }
            if let errorMessage { BK06ErrorRow(message: errorMessage) }
            BK06PrimaryButton(title: "결정하고 안내 초안 만들기", isBusy: isBusy, identifier: "k06.underMin.decide") {
                if decision == "run" { decide() } else { isConfirming = true }
            }
            .disabled(decision == "merge" && mergeInto == nil)
        } header: {
            Text("결정")
        } footer: {
            if card.mergeCandidates.isEmpty { Text("같은 주에 합칠 수 있는 회차가 없어요.") }
        }
    }

    private func decide() {
        isBusy = true
        errorMessage = nil
        Task {
            do {
                drafts = try await RoundupAPI.k06UnderMin(
                    sessionID: card.sessionId, decision: decision,
                    mergeInto: decision == "merge" ? mergeInto : nil, revision: card.revision).drafts
            } catch let error as RoundupAPIError where error.isConflict && decision == "merge" {
                errorMessage = "합칠 자리가 없어졌어요. 다른 회차를 골라 주세요."
            } catch {
                errorMessage = error.localizedDescription
            }
            isBusy = false
        }
    }
}
#endif
