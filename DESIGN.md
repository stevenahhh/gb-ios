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

- Native components only: TabView with Tab, NavigationStack, List insetGrouped, Picker, Gauge, UICalendarView, searchable, ContentUnavailableView. No custom-drawn bars.
- One prominent button per screen (borderedProminent). Every other state-changing action is bordered. Actions that only open something become whole-row navigation links.
- Liquid Glass stays in the control layer: tab bar, toolbars, the assistant accessory, and the assistant composer. Content rows never use glass button styles.
- Status never relies on color alone. Each status badge pairs a symbol with text. Status tones use orange (needs action), green (done), and gray (in progress or neutral). Event kinds use a different set (blue, brown, teal, purple) with their own symbols, so one color never means two things.
- Dynamic Type everywhere: scaled metrics for fixed widths, stacked layouts and menu pickers at accessibility sizes.
- Text size floor: body text uses body (17pt) and secondary text uses subheadline (15pt) or larger, including status badges, metric labels, row details, legends, and kind tags. System chrome keeps Apple's own styles: navigation subtitles, section headers, tab labels, and the footnote-sized assistant disclaimer.
- Korean text breaks only between words. Titles go through `Text(keepingWords:)`, which joins the characters inside each word with U+2060 and keeps the original string as the accessibility label. Detail lines go through `PhraseText`, a flow layout of plain Text pieces: a line with ` · ` separators wraps only at the separators, any other line wraps only between words.
- IDs such as order numbers can be selected on cards that are not navigation links. Each PhraseText piece is its own selectable plain Text, so copying `#1042` copies exactly that text.
- Every button leads somewhere: actions without a screen yet (예약 등록, 일정 추가, 채널 연결, 연결 관리) open the shared 준비 중 screen. Empty and error actions use the large control size (44pt).
- The assistant sheet keeps a typed draft: swipe-to-dismiss is disabled while a draft exists, and 닫기 asks 버리기 / 계속 쓰기 first.
- Counts agree across screens: 오늘 배송, 배송 관리 and its list all show 발송 예정 2, 배송 중 2, 배송 완료 1.
- Every list screen has loaded, loading (redacted placeholder), empty, and error states. Launch with `-screenState loading|empty|error` to see them.

## Screens

### Root (tab bar)
- Primary action: switch between 오늘, 캘린더, 운영, 설정.
- Priorities: 1) the four tabs, 2) the assistant accessory with a separate mic button on every tab, 3) the 운영 badge showing the 7 items that need action.
- Left out on purpose: a fifth tab, actions inside the tab bar.
- Layout: tab bar with sidebarAdaptable (bottom on iPhone, top on iPad); each tab owns its NavigationStack; scroll owner is each tab's List; the tab bar minimizes on scroll unless Reduce Motion is on. Anti-patterns: hidden or disabled tabs, accessory shown only on some tabs.

### 오늘
- Primary action: the first state-changing card action of the selected segment (for example 포장 완료하기 on 배송).
- Priorities: 1) the three numbers for today, 2) the segment control (할 일 / 채널 / 배송 / 비서 추천), 3) the grouped rows with done toggles and status badges.
- Left out on purpose: monthly statistics, settings, a second prominent button.
- Layout: List insetGrouped; scroll owner is the List; large title greeting by time of day with a subtitle showing the date and the last update time; pull to refresh. Anti-patterns: nested segmented controls, card buttons that only navigate.

### 캘린더
- Primary action: pick a day and read its schedule.
- Priorities: 1) the week strip (default) or the month calendar, 2) the selected day's schedule, 3) the legend.
- Left out on purpose: a custom time grid.
- Layout: List insetGrouped; scroll owner is the List; the month view is a UICalendarView inside one row that sizes to fit, capped at 380pt so neighbouring months never show; days with several kinds show one small symbol per kind; days without a detailed agenda show one summary row per kind that opens the matching work area; days without events show an empty state with an add action; loading, empty, and error states follow `-screenState`. Anti-patterns: color-only event markers, a dot on a day whose schedule is empty, a chevron on a row that does not navigate.

### 운영
- Primary action: open the first item under 먼저 확인해주세요.
- Priorities: 1) 먼저 확인해주세요 with three tappable counts, 2) the monthly summary (labelled ring, four numbers, month-over-month pair, period menu with a checkmark), 3) the four work areas, then 기회 and 리포트.
- Left out on purpose: charts.
- Layout: List insetGrouped; scroll owner is the List; rows push OperationAreaView with an optional preset filter. Anti-patterns: a non-tappable urgent summary, a period menu that looks like plain text.

### 예약 관리, 주문 관리, 배송 관리, SNS·스토어 관리
- Primary action: the first state-changing action in the filtered list (for example 입금 확인하기).
- Priorities: 1) three numbers, 2) the status filter (short labels, counts live in the numbers), 3) the filtered cards with deadlines emphasized.
- Left out on purpose: counts inside filter labels, single-item menus.
- Sample data keeps the 먼저 확인해주세요 counts true: 예약금 대기 shows 2 bookings, 문의 shows 3 inquiries, 발송 예정 shows 2 parcels. SNS·스토어 filters are 전체, 채널, 문의, 콘텐츠.
- States: with no data the screen shows its own empty state with the area's next step (예약 등록하기, 채널 연결하기); a filter or search with no match shows ContentUnavailableView and offers 전체 보기 only when another filter is selected.
- Layout: List insetGrouped under an inline title; scroll owner is the List; the search field stays visible in the navigation bar drawer; search and filter both narrow the list, and an empty result shows ContentUnavailableView (search or filter). Anti-patterns: filters that do not filter, more than one prominent button.

### 설정
- Primary action: open a settings row.
- Priorities: 1) the studio profile, 2) studio, team, and personal settings, 3) help.
- Left out on purpose: an in-app appearance setting.
- Layout: List insetGrouped; scroll owner is the List; rows push placeholder screens until designed.

### 비서 sheet
- Primary action: send a question.
- Priorities: 1) the focused text field with the send button, 2) three suggested questions, 3) the reminder that the assistant can be wrong.
- Left out on purpose: stacked sheets.
- Layout: sheet with medium and large detents and a visible grabber; the composer sits in the bottom safe area; scroll owner is the message list. Anti-patterns: a decorative mic that does nothing different.
