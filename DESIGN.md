# Design contract: 공방 AI 비서 iOS skeleton

This file is the brief and layout contract for every screen. Visual QA checks each screen against it.

## Persona and jobs

The primary user is a craft-studio owner in their 30s or 40s. They run the studio alone, sell classes through Instagram and Naver booking, and handle most work on a phone (feature spec 2.1). They check the app in short gaps: before opening, between classes, and after closing. During class their hands are often busy, so one-handed use and quick glances matter more than density.

Ranked jobs:
1. See what needs action right now: unpaid deposits, unanswered inquiries, packages due today.
2. Know today's classes and headcount.
3. Finish small status changes in one tap (packed, invoice registered, deposit confirmed).
4. Ask the assistant quickly, by short text or dictation, from any screen.
5. Check channels, deliveries, and suggestions when there is more time.

## Principles

- Native components only: TabView with Tab, NavigationStack, inset-grouped List cards (`CardSection`) with the system corner radius in both modes on the calendar's page colors (`AppPalette` reuses `CalendarTokens.background` and `.pinned`: white page with #F5F5F7 cards, black page with #1C1C1E cards); a drawn box uses the same radius (`.card`, 26pt continuous) and a box inside a card uses `.inner` (18pt), Picker, Gauge, searchable, ContentUnavailableView. No custom-drawn bars. Two places draw their own: the calendar tab has its week strip, month grid, and timeline (see 캘린더), and 운영 현황 has its collection rings (see 운영).
- One prominent button per screen (borderedProminent). Every other state-changing action is bordered. Actions that only open something become whole-row navigation links.
- Liquid Glass stays in the control layer: tab bar, toolbars, the assistant accessory, and the assistant composer. Content rows never use glass button styles.
- Status never relies on color alone. Each status badge pairs a symbol or dot with text. Saturated color carries one meaning each (`ColorRoles.swift`): `pendingOrange` is only the small dot on a status the owner must act on (검토 대기, 포장·송장 대기, 예약금 대기); `overdueRed` is only `OverdueMark`, the clock on an item past its deadline; `assistantAccent` is reserved for the assistant's "비서가 쓴 답변/글" label and the live voice orb. `writingLead` (dusty amber) and `writingTrail` (soft lavender), both near 30% saturation, appear only while assistant-written text arrives (`GeneratedText`, `KoreanTextEditor(isFresh:)`, and the `GeneratingIndicator` shimmer). Each glyph fades in out of an 8 pt blur, 3 pt below its place, tinted amber and then lavender, and rests in the label color within 0.55 s. The front moves at about 50 characters a second and a whole answer takes at most 2.75 s. Under Reduce Motion the text fades in whole and the indicator is static text with a spinner. Secondary text uses `Color.secondaryText` (#636366 / #AEAEB2, 4.5:1 or better); lighter grays are for icons, chevrons, and rules. Something unavailable turns gray and stays readable instead of fading: the calendar's 오늘 while today is showing, and a row with no step left in 선택. An error line is label-colored text beside an orange symbol; the words are never orange, because orange text measures 2.1:1 on the light card. Empty-state descriptions take `secondaryText` too, because the system's gray measures 3.4:1 on the white page. Inside a `CardSection` header `.primary` resolves to the header's gray, so a header that must be black uses `Color.primary`. A failed load shows one `ConnectionNotice` line under the title, never a pinned overlay. Done is gray: a gray circle with a gray check, as in the calendar. Icon boxes are gray with a black line symbol, and 반려 is black text because it can be undone. Today's 할 일 gathers overdue rows into one top group under a plain title; each row carries the overdue mark and a gray "어제 16:00 · 포장 대기", and leaves its own section. Color means status, never category: Operations uses no per-category color or row separator, and the calendar uses no color at all (see 캘린더). Only navigation rows to work areas and 기회 carry a monochrome secondary-colored symbol. The one category color left is the blue booking node on Today's 예약 timeline.
- An item past its deadline shows one thing: `OverdueMark`, a red clock (`clock.fill`) with no words, at its top-left. On cards and rows it leads the title and takes the title's font, so it grows with Dynamic Type. On the calendar timeline it takes the node's place, and on an operations tile it sits in the top-left corner. The deadline line under it (`DueLabel`) turns gray and drops its own clock. VoiceOver reads the mark as 기한 지남. A deadline that has not passed keeps its gray outline clock in the deadline line.
- Brand: the home-screen name is 공도리 in both configurations. Show the app's mark once, at 28pt in the leading toolbar of 오늘, with the VoiceOver label 공도리. Do not repeat it beside answers or drafts.
- Dynamic Type everywhere: scaled metrics for fixed widths, stacked layouts and menu pickers at accessibility sizes.
- Text size floor: body text uses body (17pt) and secondary text uses subheadline (15pt) or larger, including status badges, metric labels, row details, legends, kind tags, the calendar's weekday letters and time chip, and the text of the two controls that sit in a header (오늘 and the period button). Those two draw a 32pt capsule inside a 44pt tap area. System chrome keeps Apple's own styles: navigation subtitles, section headers, tab labels, and the footnote-sized assistant disclaimer.
- Korean text breaks only between words. Titles are plain `Text(verbatim:)`, whose standard line-break strategy keeps Hangul words whole; joining a word's characters with U+2060 made iOS 27 break inside words, so no joiner is added. Detail lines go through `PhraseText`, a flow layout of plain Text pieces: a line with ` · ` separators wraps only at the separators, any other line wraps only between words.
- IDs such as order numbers can be selected on cards that are not navigation links. Each PhraseText piece is its own selectable plain Text, so copying `#1042` copies exactly that text.
- Every button performs a persisted server action or opens a real screen. Features without a backend are removed or state plainly that they are not connected. Empty and error actions use the large control size (44pt).
- Undo is one toast for the whole app (`ToastHost`), laid over the assistant accessory so the row that changed stays visible. Every state change taken from a list shows it, and one 되돌리기 undoes a whole batch. A completion toast names its row on one line ("‘제목’ 완료했어요" or "‘제목’ 완료를 취소했어요"). It leaves after 7 seconds, or stays until closed while VoiceOver runs.
- The assistant sheet keeps a typed draft: swipe-to-dismiss is disabled while a draft exists, and 닫기 asks 버리기 / 계속 쓰기 first.
- Counts agree across screens because the server computes them from the same rows; the app never derives or stores display numbers.
- Every server-backed screen has loaded, loading (a progress indicator that shows after 0.35 s, so a quick load shows none), empty, and error-with-retry states. A failed refresh keeps the last loaded data and says so.
- Reconnecting needs no tap. While a screen that cannot reach the server is visible, `ServerConnection` retries after about 1, 2, 4, 8, 16, then 30 seconds (±20% jitter), and at once when the network path returns. The row under the title shows a spinner with 다시 연결하는 중 (인터넷 연결을 기다리는 중 without a path); a screen with no data shows `ReconnectingView` with a secondary 지금 다시 시도. Recovery shows 다시 연결됐어요 once. Only transport failures and 502/503/504 retry; 401/404/409/422 never do, and writes are never repeated by themselves. GETs get one quick retry on a dropped connection.
- Cold launch shows the last response from today for 오늘, 운영, 캨린더, 문의, and 설정 at once (`ResponseCache`), then replaces it with fresh data. A cache from an earlier day is ignored, because the server words dates as 오늘/내일.

## Screens

### Root (tab bar)
- Primary action: switch between 오늘, 캘린더, 운영, 설정.
- Priorities: 1) the four tabs, 2) the 채팅하기 button on every tab, which opens the assistant sheet, and its separate mic for live voice conversation, 3) the 운영 badge showing the items that need action.
- Left out on purpose: a fifth tab, actions inside the tab bar.
- Layout: tab bar with sidebarAdaptable (bottom on iPhone, top on iPad); each tab owns its NavigationStack; scroll owner is each tab's List; the tab bar minimizes on scroll unless Reduce Motion is on. Anti-patterns: hidden or disabled tabs, accessory shown only on some tabs.

### 오늘
- Primary action: the first state-changing card action of the selected segment (for example 포장 완료하기 on 배송).
- Priorities: 1) the three numbers for today, 2) 확인해 주실 일, up to three assistant drafts to decide or fix in place, 3) the segment control (할 일 / 채널 / 배송 / 비서 추천), 4) the grouped rows with done toggles and status badges. A reply card's button is 답변 완료 and a post or suggestion card's is 승인; a decided card stays with 되돌리기, and replies and posts add copy and open-the-channel buttons. 예약 rows sit on a vertical timeline; checking any row strikes its title through in place.
- Left out on purpose: monthly statistics, settings, a second prominent button.
- 비서 제안 (`AgentProposalSection`) sits under the three numbers and the K06 cards: up to three waiting proposals, each row opening its card, and 모두 보기 when there are more. With none waiting it is hidden. A failed load keeps the list and adds 다시 시도.
- Layout: List insetGrouped; scroll owner is the List; large title is a one-line headline of the most urgent work (`TodayHeadline`: overdue, class within two hours, waiting work, remaining today, all done, tomorrow/this week), always label-colored and at most 10 Hangul syllables, with a subtitle showing the date and the last update time; pull to refresh. Anti-patterns: nested segmented controls, card buttons that only navigate.

### 캘린더
- Primary action: pick a day and read its schedule.
- Priorities: 1) the week strip (default) or the month calendar, 2) the selected day's schedule.
- Left out on purpose: an hour grid; the timeline lists rows in time order instead.
- Layout: "모노 타임라인". One white ScrollView, no cards on gray, margins 20pt, system large title "캘린더" with a "오늘 일정 N건" subtitle and + in the toolbar, like the other tabs. Colors come only from `CalendarTokens` (background, label, secondary, tertiary, separator, fill, pinned); label is the only accent. `tertiary` is for dots and arrows, never text, and holds 3:1 on the page and on the pinned box in both modes. Week strip and month grid share `PeriodNavigator` and `DayCell`; dots under a date count schedule (1, 2, or 3 dots), never kind. All-day facts such as arrivals, and the day's orders, go to a pinned box; an all-day task or owner-added event (stored at 23:59:59) stays in the timeline as 종일 and never becomes passed or next; everything else is a timeline whose node shape is the kind (filled circle booking, square delivery, hollow circle task) and whose weight is the state (gray check done, boldest next with a duration bar, semibold upcoming). Tasks and owner-added events carry a trailing 26pt check circle with a 44pt target, in the same place as the today rows and with the same gray ring; the node stays a marker, not a button. A check shows at once (strikethrough, gray node, "완료", success haptic) before the server answers, reverts on failure, and raises the shared undo toast, both when checking and when unchecking. Today shows a current-time line before the first timed row that has not started, refreshed every minute. Date controls stop at xxxLarge Dynamic Type; at accessibility sizes the time moves above the title. A task whose time has passed unfinished is `missed`, and a parcel past pickup is overdue: the overdue mark takes the node's place on both, and no word is added. A missed task is checked off in place, and its date changes in the task detail. Red (`overdueRed`) appears only on that mark. 일정 추가 is a capsule on `CalendarTokens.fill` with a plus, 44pt tall, like the 오늘 pill. Days with no timed rows show an empty message with 일정 추가 under it and hide the legend. A day that has a timeline keeps the same 일정 추가 pinned in the bottom safe area (`DayAddBar`), so it is in reach before any scrolling and the last row ends above it. Both open the form the toolbar + opens. The legend draws the rows' own marks, so 끝남 is the gray check and not a bare dot, and 지남 is the red clock beside a gray word. Anti-patterns: per-kind colors, orange emphasis, a system graphical date picker, order receipt times in the timeline.

### 운영
- Primary action: open the first item under 먼저 확인해주세요.
- Priorities: 1) 먼저 확인해주세요 as three tiles side by side, each a count and a label that opens its filtered list, with a red clock in the top-left corner when a deadline has passed (rows at accessibility sizes), 2) 운영 현황: three collection rings, then the period numbers (예약, 주문, 배송, 문의, each with a one-line explanation), a period button that opens a start-to-end calendar, and a 남은 일 row while work is left, 3) the four work areas, then 기회.
- The collection rings (`CollectionStatusRings`) read `GET /collectors/status` about every 5 seconds while they are on screen: 네이버 스토어, INSTAGRAM, 블로그, each a thick ring with its name inside and its state word (수집 중, 대기, 연결 필요, 오류) below. Only a collecting ring turns, like a loading mark, and Reduce Motion holds it still. 연결 필요 is an empty track and 오류 an orange arc. With no status, or with nothing connected, the rings turn as a sample under an 예시 데이터 badge; sample and real states are never mixed.
- Left out on purpose: charts.
- Layout: List insetGrouped; scroll owner is the List; rows push OperationAreaView with an optional preset filter. Anti-patterns: a non-tappable urgent summary, a period control that looks like plain text.

### 예약 관리, 주문 관리, 배송 관리, SNS·스토어 관리
- Primary action: the first state-changing action in the filtered list (for example 입금 확인하기).
- Priorities: 1) three numbers, 2) the status filter (short labels, counts live in the numbers), 3) the filtered cards with deadlines emphasized.
- Left out on purpose: counts inside filter labels, single-item menus.
- 먼저 확인해주세요 counts equal their filtered lists: 예약금 대기, 문의, and 발송 예정. SNS·스토어 filters are 전체, 채널, 문의, 콘텐츠.
- Fulfilment happens in one place: an order card carries its parcel's next step as its one button (주문 확인하기 → 포장 완료하기 → 송장 등록하기 → 배송 완료 확인), shows its status as 포장 대기 / 송장 대기 / 배송 중, and advances in place. Unfinished fulfilment cards show an "N/5단계" ProgressView under the badge; a leading swipe takes the next step.
- Every step after the first can be taken back in place. A bordered circle with `arrow.uturn.backward` (accessibility label 되돌리기) sits left of the step button on cards and details (`CardActions`); at accessibility sizes it is a full-width 되돌리기 under the step button. It uses the card's own undo, and an order past packing steps its parcel back. A finished parcel's detail keeps the circle beside "이전 단계로 돌아갈 수 있어요." The toast names the step taken back ("‘제목’ 포장 완료를 취소했어요") and its 되돌리기 takes that step again. Going back from 배송 중 clears the carrier and tracking number, so it asks first (송장 지우고 되돌리기) and its toast offers no 되돌리기. A delivered order's own card has no step back, because the server's order card then names neither an undo nor its parcel; the parcel's detail has it.
- 주문 상세 and 배송 상세 open with one centered card (`OrderSummarySections`): the title, the first card line, the deadline, the status badge centered above the steps (`ProgressSteps`), and the step controls, with no separate 처리 section. In list cards the badge stays at the trailing edge, centered on the title.
- `ProgressSteps` is a drawn track with one node per step. When a step is taken its node fills from the center, the check is drawn along its stroke, the line to the next node fills, and the next node's ring darkens, in about 0.75 s. A step back plays the same marks in reverse in about 0.5 s. Under Reduce Motion each mark cross-fades in 0.25 s. At accessibility sizes the track is vertical with each label beside its node. In the row the labels stop growing at xLarge, so long and short step names keep one size.
- 선택 in 주문 관리 and 배송 관리 turns rows into checkable rows with a bottom bar: the earliest step among the chosen rows is the one prominent button ("주문 확인 3건"), later steps sit in a compact row, and chosen rows stay chosen so the next step follows at once. A row with no step left turns gray and cannot be checked. Batch endpoints apply a whole batch in one transaction or none of it.
- The invoice sheet serves one parcel or many: it remembers the last carrier, focuses the number field on open, offers the system paste button and, where supported, a VisionKit barcode scanner; a paste or scan moves to the next empty parcel. Numbers are 10-14 digits and unique across the sheet.
- Inquiry replies have one action, 답변 완료, and no rejection. The reply stays editable and saves when the screen is left. A completed reply's badge reads 답변 준비됨, because completing sends nothing; 답변 복사하기 and 네이버 스마트스토어 열기 appear while the editor matches the saved reply.
- States: with no data the screen shows its own empty state, with 예약 등록하기 where booking creation exists; a filter or search with no match shows ContentUnavailableView and offers 전체 보기 only when another filter is selected.
- Layout: List insetGrouped under an inline title; scroll owner is the List; the search field stays visible in the navigation bar drawer over a hard scroll edge, so rows do not read through it; search and filter both narrow the list, and an empty result shows ContentUnavailableView (search or filter). Anti-patterns: filters that do not filter, more than one prominent button.

### 설정
- Primary action: open a settings row.
- Priorities: 1) the studio profile, 2) studio settings, 3) help.
- Left out on purpose: an in-app appearance setting.
- Layout: List insetGrouped; scroll owner is the List; rows push the workshop form, editable policy text, channel status, 비서에게 맡길 일, which opens 비서 자율성, and 비서가 한 일.

### 비서 sheet
- Primary action: send a question.
- Priorities: 1) the focused text field with the send button, 2) three suggested questions, 3) the reminder that the assistant can be wrong.
- Left out on purpose: stacked sheets.
- Layout: sheet with medium and large detents and a visible grabber, on the system's translucent sheet background, like Siri; scroll owner is the transcript scroll view. `AssistantBackdrop` adds the page color (black in dark mode) as one gradient: none at the grabber, 50% at the composer's top edge, and 100% from the question field down, so messages fade out above the field (solid page color under Reduce Transparency). The composer sits in the bottom safe area, and from the field's top edge down it covers the messages with the page color (a 12 pt soft edge above), so no text shows behind the field. Toolbar: 닫기 leading; 파일 불러오기 (`doc.badge.plus`), 지난 대화 (`clock.arrow.circlepath`) and, on a conversation, 새 대화 (`square.and.pencil`) trailing. Anti-patterns: a decorative mic that does nothing different.
- Chats are saved on the device (`ConversationStore`, the last 100, one JSON file each) and reopen when used within 30 minutes. 지난 대화 lists them by day with swipe to delete; an opened chat pushes with the system back button and continuing it sends its history. Live voice turns are saved into the same chat.
- A sent question moves to the top and its answer is written below it; one question is sent at a time; a failed question shows 다시 시도. Cards in answers are drawn boxes with the `.card` radius on `AppPalette.card`, and one tap opens one detail.

- Under an answer, `AgentRunDetail` shows the run's status, its steps, then its proposal cards. Lookups share one 확인한 것 line. Proposals that aren't in the conversation on screen share one banner at the top, 승인을 기다리는 제안 N건.
- A run states: 처리 중이에요, or 처리 중 · N건 끝냈어요 once something is done, with 화면을 닫아도 계속 처리해요 under it; stopped; failed, which says whether anything changed. A question over 1,000 characters can't be sent, and the line under the field says so.

### 처음 안내 (onboarding)
- Primary action: one prominent button per step, at the bottom.
- Priorities: 1) the step's one question, 2) its rows, 3) the ways out (뒤로, 나중에 하기, 건너뛰기) in the bar with the progress.
- States: first launch; resumed on the page the owner left; replayed from 설정, which never comes back by itself at launch.
- Left out on purpose: logins, passwords, system permission prompts, payment. A saved value says 저장됨, never 연결됨; a plan says 아직 결제되지 않아요.
- Layout: a full-screen cover over the tabs. The cover draws the toast itself while it is up. Coach marks run over the real screens afterwards; mark rows with `tutorialAnchor`, never a section, which would become one row.

### 비서 제안 (proposal cards)
- Primary action: 승인하기 on the first open proposal. Only that card is prominent on a screen; in live voice none is.
- Priorities: 1) the state badge and the deadline, 2) the title and why it was raised, 3) the values it would write and 필요한 것, 4) 승인하기 and 하지 않기.
- Left out on purpose: approving several proposals at once (invoice files are the one group approval), editing values in the card.
- States: 승인 대기 says nothing has changed yet; 승인함 shows the step that ran, with undo when the server offers it; 하지 않기로 함; 만료; 닫힘 for one decided elsewhere. A decided card stays in place. The list also has an empty state (기다리는 제안이 없어요) and an error with 다시 시도.
- Layout: one card per `CardSection`. At accessibility sizes the header, values, and buttons stack. Anti-patterns: a card that looks finished before a yes, a deadline in words the rest of the app doesn't use.

### 비서 단계 (steps and undo)
- Primary action: 되돌리기, a bordered circle beside a step the server can still take back; full width at accessibility sizes.
- Priorities: 1) what the step was, 2) its state word and target, 3) the owner's words it rested on, or why it stopped.
- States: 완료, 되돌림, 승인 대기, 승인함, 하지 않기로 함, 만료, 닫힘, 하지 않음, 확인 필요. Only 승인 대기 and 확인 필요 carry the orange dot; the others are gray marks with a word.
- Left out on purpose: tool names, confidence numbers, and raw arguments.

### 비서 자율성
- Primary action: 지금 모두 멈추기. While stopped it gives way to a bordered ‘물어보고’로 다시 맡기기.
- Priorities: 1) whether the assistant is working and the stop control, 2) 맡기는 방식 (끔, 물어보고, 알아서) with one sentence on the chosen one, 3) proactive proposals, 4) a mode per tool in two groups: work that stays inside the studio, then money, parcels, and customer state, 5) 맡길 수 없는 일, locked rows, 6) the daily cap and quiet hours, then 비서가 기억하는 것.
- States: loading and error with retry; stopped, where the proactive toggle and the tool pickers are disabled and say why; a refused change reverts and shows the server's reason on an orange-symbol line.
- Left out on purpose: a save button. Every change saves at once.
- Layout: List insetGrouped, pushed from 설정. Anti-patterns: the stop control below the fold, a switch for anything in 맡길 수 없는 일.

### 비서가 한 일
- Primary action: 되돌리기 on a step.
- Priorities: 1) the filter (전체, 채팅, 음성, 먼저 챙김), 2) entries by day, newest first, 3) each run's question, source, answer, and steps; drafts and notices with their facts.
- States: loading, error with retry, empty overall, empty for one filter with 전체 보기; on a run, 처리 중, stopped, and failed.
- Left out on purpose: runs that found nothing and said nothing.

### 비서가 기억하는 것
- Primary action: forget one memory, after a confirmation.
- Priorities: 1) what is remembered, 2) the owner's own sentence and its day, 3) the note that memories are context and never grounds for an action.
- States: loading, error with retry, empty (기억해 달라고 말씀하신 내용이 여기에 모여요), deleting (the row's button is disabled).
- Left out on purpose: typing or editing a memory here.

### 송장 파일 확인
- Primary action: N건 등록 승인 for every clean row.
- Priorities: 1) the file name, how many numbers were read, and that nothing is registered yet, 2) clean rows with one approval, 3) warned rows, each with its reason and its own bordered approval, 4) rows that can't be registered and why, 5) 등록 결과.
- States: loading; error with retry; approved rows; a format warning whose 이 건만 등록 승인 stays disabled until its switch is on; an alert for a file that is too large, can't be opened, or isn't CSV or XLSX.
- Left out on purpose: names, phone numbers, and addresses from the file, and any copy of the file on the device.
- Layout: List pushed inside the assistant sheet. Anti-patterns: approving a warned row with the group, a blocked row with a button.

### 실시간 음성 (live voice)
- Primary action: talk; the assistant answers aloud with subtitles.
- Priorities: 1) the orb, which follows the mic level while listening and the voice while speaking, and stops the answer when tapped, 2) the status line (듣고 있어요 / 생각하고 있어요 / 말하고 있어요 / 일시정지), 3) live captions, spoken words in the label color and the rest in `secondaryText`, 4) 대화 내용 (full transcript with work cards), 마이크, 끝내기.
- Speech: on-device SFSpeechRecognizer (ko-KR) shows partial captions and ends an utterance after 1.2 s of silence; the final text comes from NAVER CSR (`/stt`), with the on-device words as fallback. Answers are spoken sentence by sentence with CLOVA Voice Premium (유나 Pro) through `POST /tts`, prefetching the next sentence. When /tts fails, the best installed Korean device voice (premium, then enhanced, then default) speaks for the next 10 minutes; with only the default voice the transcript suggests downloading 유나(프리미엄). `LiveSpeechConfig.usesServerSpeech` switches server speech off if the plan is cancelled.
- Turns are saved to the assistant's conversation history, so the chat sheet shows them later.
- Layout: full-screen cover, dark-leaning; going to the background pauses; closing stops the audio engine. Reduce Motion keeps the orb still with an opacity pulse. Anti-patterns: a dead end on a denied mic or a network error (both offer 다시 시도).
