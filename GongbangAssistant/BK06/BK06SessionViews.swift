import SwiftUI
import UIKit

struct BK06SessionListView: View {
    let sessions: [BK06SessionLine]

    var body: some View {
        List {
            CardSection {
                if sessions.isEmpty { Text("앞으로 2주는 수업이 하나도 없어요").foregroundStyle(Color.secondaryText) }
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
        .navigationTitle("출석 체크, 빈자리 기다리는 손님")
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
                    if detail.guests.isEmpty { Text("예약하신 손님이 아직 없어요").foregroundStyle(Color.secondaryText) }
                    ForEach(detail.guests) { guestRow($0) }
                } header: {
                    Text("\(detail.schedule) · \(detail.booked)/\(detail.capacity)명")
                } footer: {
                    Text("오른쪽 버튼을 누르면 환불 규정 안내를 복사해요. 손님이 도착하시면 그분 이름을 눌러 주세요.")
                }
                CardSection("빈자리를 기다리는 손님") {
                    ForEach(detail.targets) { target in
                        BK06ValueRow(label: "\(target.name) 님", value: target.sourceText)
                            .swipeActions {
                                Button("명단에서 빼기", role: .destructive) {
                                    act { try await RoundupAPI.k06RemoveWaiting(sessionID: sessionID, entryID: target.entryId) }
                                }
                            }
                    }
                    Button("기다리는 손님 추가", systemImage: "plus") { isAddingGuest = true }
                        .accessibilityIdentifier("k06.addWaiting")
                }
                CardSection("최소 인원") {
                    if let seats = detail.minSeats { BK06ValueRow(label: "최소 인원", value: "\(seats)명") }
                    if let deadline = detail.materialOrderDeadline {
                        BK06ValueRow(label: "재료 주문 마감일", value: BK06Format.when(deadline))
                    }
                    Button(detail.minSeats == nil ? "모자랄 것 같으면 미리 알려 드릴게요. 최소 인원을 적어 두세요" : "고치기") { isPlanning = true }
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
        HStack(spacing: 12) {
            attendanceButton(guest)
            // Visible, not only behind a long press: copying the rule notice is a common next step.
            Button(guest.noticed ? "규정 안내 한 번 더 복사" : "규정 안내 복사하기", systemImage: "doc.on.doc") { copyNotice(guest) }
                .labelStyle(.iconOnly)
                .frame(minWidth: 44, minHeight: 44)
                .buttonStyle(.borderless)
                .accessibilityIdentifier("k06.notice.\(guest.bookingId)")
        }
    }

    private func attendanceButton(_ guest: BK06Guest) -> some View {
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
                    Text(guest.noShowAt != nil ? "노쇼" : guest.attendedAt != nil ? "도착" : "출석 체크 전")
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                }
                Spacer(minLength: 8)
                DoneMark(isDone: guest.attendedAt != nil)
            }
            .contentShape(.rect)
        }
        .buttonStyle(.borderless)
        .foregroundStyle(Color.primary)
        .contextMenu {
            Button(guest.noticed ? "규정 안내 한 번 더 복사" : "규정 안내 복사하기", systemImage: "doc.on.doc") { copyNotice(guest) }
        }
        .accessibilityIdentifier("k06.guest.\(guest.bookingId)")
    }

    private func copyNotice(_ guest: BK06Guest) {
        act {
            let notice = try await RoundupAPI.k06Notice(bookingID: guest.bookingId)
            UIPasteboard.general.string = notice.summary
            app.showToast("\(notice.version)번째 규정 안내 복사 끝!", seconds: 3)
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
                    DatePicker("재료 주문 마감일", selection: $deadline)
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
                    TextField("전화번호(없어도 괜찮아요)", text: $phone).keyboardType(.phonePad)
                    Picker("어떤 손님인가요", selection: $isMakeup) {
                        Text("빈자리 나면 연락 달라고 하신 손님").tag(false)
                        Text("보강 수업이 남은 수강생").tag(true)
                    }
                }
            }
            .cardList()
            .navigationTitle("기다리는 손님")
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
                        Text("노쇼로 기록해 뒀어요")
                    }
                }
                .cardList()
            } else if outcome == nil, let card = cards.late.first(where: { $0.id == bookingID }) {
                list(card)
            } else {
                ContentUnavailableView("이미 정리하신 손님이에요", systemImage: "checkmark.circle",
                                       description: Text("이미 도착이나 노쇼로 표시하셨거나 그사이 예약 내용이 달라졌어요."))
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
                    Text(verbatim: card.headline).font(.headline)
                    PhraseText(text: card.detail)
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                }
                if let phone = card.phone, let url = URL(string: "tel:\(phone.filter(\.isNumber))") {
                    Button("전화 걸기", systemImage: "phone") { openURL(url) }
                        .buttonStyle(.bordered)
                }
            }
            CardSection("확인 문자 보내기") {
                BK06CopyableDraft(name: card.customerName, text: card.draft)
            }
            CardSection {
                if let errorMessage { BK06ErrorRow(message: errorMessage) }
                Button("도착") { mark(arrived: true) }
                    .buttonStyle(.bordered)
                    .disabled(isBusy)
                    .accessibilityIdentifier("k06.arrived")
                BK06PrimaryButton(title: "노쇼로 기록하기", isBusy: isBusy, identifier: "k06.noShow") { mark(arrived: false) }
            } footer: {
                Text("예약금은 앱이 건드리지 않아요. 노쇼 기록도 우리 공방 안에서만 보여요.")
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
                app.showToast(arrived ? "도착 체크 끝!" : "노쇼로 기록해 뒀어요") {
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
                        Text("연락드릴 손님이 없어요").accessibilityIdentifier("k06.refill.empty")
                        NavigationLink("빈자리 대기 명단 채우러 가기") { BK06SessionView(sessionID: sessionID) }
                    } footer: {
                        Text("빈자리 나면 연락 달라고 하신 손님이나 보강 수업이 남은 분을 적어 두시면 연락드릴 순서대로 보여 드려요.")
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
        CardSection("연락드릴 순서") {
            ForEach(Array(refill.targets.enumerated()), id: \.element.id) { index, item in
                Button { chosen = item.id } label: {
                    HStack(spacing: 10) {
                        BK06ValueRow(label: "\(index + 1). \(item.name) 님", value: item.sourceText)
                        if item.id == target.id {
                            Image(systemName: "checkmark").accessibilityLabel("골랐어요")
                        }
                    }
                    .contentShape(.rect)
                }
                .foregroundStyle(Color.primary)
            }
        }
        CardSection {
            Text(verbatim: target.draft).textSelection(.enabled)
            BK06PrimaryButton(title: target.id == refill.targets[0].id ? "맨 앞 손님께 갈 초안 복사하기" : "\(target.name) 님께 보낼 초안 복사하기",
                              identifier: "k06.refill.copy") {
                UIPasteboard.general.string = target.draft
                app.showToast("복사 끝! 카톡이든 문자든 평소 쓰시는 채널에 붙여 보내 주세요", seconds: 3)
            }
        } header: {
            Text("빈자리 안내 초안")
        } footer: {
            Text("자리 하나에 한 분씩 연락하고 답이 올 때까지 기다려 주세요. 오신다고 하면 예약 넣기에서 이름을 올리시면 돼요.")
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
                BK06ValueRow(label: "예약", value: "\(card.booked)명", tag: "적어도 \(card.minSeats)명")
                BK06ValueRow(label: "재료 주문 마감일", value: BK06Format.when(card.orderDeadline))
                if let material = card.materialWon {
                    BK06ValueRow(label: "예약된 인원만큼 드는 재료비", value: BK06Format.won(material), tag: "추정")
                }
            }
            if let drafts {
                CardSection("안내 문자 초안") {
                    if drafts.isEmpty { Text("연락드릴 손님이 없어요") }
                    ForEach(drafts) { BK06CopyableDraft(name: $0.customerName, text: $0.draft) }
                }
            } else {
                choices
            }
        }
        .cardList()
        .navigationTitle("인원 부족")
        .navigationBarTitleDisplayMode(.inline)
        .confirmationDialog(decision == "merge" ? "예약을 다른 날 수업으로 옮길까요?" : "이번 수업을 취소할까요?",
                            isPresented: $isConfirming, titleVisibility: .visible) {
            Button(decision == "merge" ? "반 합치고 초안 받기" : "취소하고 초안 받기", role: .destructive) { decide() }
        } message: {
            Text("손님께는 아무 연락도 가지 않아요. 다만 한 번 하면 앱에서 원래대로 돌릴 수 없어요.")
        }
        .onDisappear { if drafts != nil { app.dataDidChange() } }
    }

    private var choices: some View {
        CardSection {
            Picker("수업을 어떻게 할까요", selection: $decision) {
                Text("예정대로 수업하기").tag("run")
                if !card.mergeCandidates.isEmpty { Text("다른 수업이랑 반 합치기").tag("merge") }
                Text("이번 수업 취소하기").tag("cancel")
            }
            .accessibilityIdentifier("k06.underMin.decision")
            if decision == "merge" {
                Picker("합칠 수업 고르기", selection: $mergeInto) {
                    Text("하나 골라 주세요").tag(String?.none)
                    ForEach(card.mergeCandidates) { option in
                        Text("\(BK06Format.when(option.startsAt)) · \(option.openSeats)자리 비어 있어요").tag(Optional(option.sessionId))
                    }
                }
            }
            if let errorMessage { BK06ErrorRow(message: errorMessage) }
            BK06PrimaryButton(title: "정하고 손님 안내 문자 초안 받기", isBusy: isBusy, identifier: "k06.underMin.decide") {
                if decision == "run" { decide() } else { isConfirming = true }
            }
            .disabled(decision == "merge" && mergeInto == nil)
        } header: {
            Text("어떻게 할까요")
        } footer: {
            if card.mergeCandidates.isEmpty { Text("같은 주에는 합칠 만한 수업이 안 보여요.") }
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
                errorMessage = "그새 자리가 다 찼어요. 합칠 수업을 새로 골라 주세요."
            } catch {
                errorMessage = error.localizedDescription
            }
            isBusy = false
        }
    }
}
