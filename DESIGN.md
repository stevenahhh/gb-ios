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

- Native components only: TabView with Tab, NavigationStack, List with per-row card backgrounds (`CardSection`, so dark cards can use a smaller radius), Picker, Gauge, searchable, ContentUnavailableView. No custom-drawn bars. The calendar tab is the one exception: it draws its own week strip, month grid, and timeline (see 캘린더).
- One prominent button per screen (borderedProminent). Every other state-changing action is bordered. Actions that only open something become whole-row navigation links.
- Liquid Glass stays in the control layer: tab bar, toolbars, the assistant accessory, and the assistant composer. Content rows never use glass button styles.
- Status never relies on color alone. Each status badge pairs a symbol or dot with text. Saturated color carries one meaning each (`ColorRoles.swift`): `pendingOrange` is only the small dot on a status the owner must act on (검토 대기, 포장·송장 대기, 예약금 대기); `overdueRed` is only "기한 지남"/"지남", its clock, and the calendar's missed node; `assistantAccent` is reserved for the assistant's face (`AssistantFace`, 22/24/28pt) and its "비서가 쓴 답변/글" label. Secondary text uses `Color.secondaryText` (#636366 / #AEAEB2, 4.5:1 or better); lighter grays are for icons, chevrons, and rules. A failed load shows one `ConnectionNotice` line under the title, never a pinned overlay. Done is gray: a gray circle with a gray check, as in the calendar. Icon boxes are gray with a black line symbol, and 반려 is black text because it can be undone. Today's 할 일 gathers overdue rows into one top group with a single red title; rows show a gray "어제 16:00 · 포장 대기" and leave their own sections. Color means status, never category: Operations uses no per-category color or row separator, and the calendar uses no color at all (see 캘린더). Only navigation rows to work areas and 기회 carry a monochrome secondary-colored symbol.
- Dynamic Type everywhere: scaled metrics for fixed widths, stacked layouts and menu pickers at accessibility sizes.
- Text size floor: body text uses body (17pt) and secondary text uses subheadline (15pt) or larger, including status badges, metric labels, row details, legends, and kind tags. System chrome keeps Apple's own styles: navigation subtitles, section headers, tab labels, and the footnote-sized assistant disclaimer.
- Korean text breaks only between words. Titles go through `Text(keepingWords:)`, which joins the characters inside each word with U+2060 and keeps the original string as the accessibility label. Detail lines go through `PhraseText`, a flow layout of plain Text pieces: a line with ` · ` separators wraps only at the separators, any other line wraps only between words.
- IDs such as order numbers can be selected on cards that are not navigation links. Each PhraseText piece is its own selectable plain Text, so copying `#1042` copies exactly that text.
- Every button performs a persisted server action or opens a real screen. Features without a backend are removed or state plainly that they are not connected. Empty and error actions use the large control size (44pt).
- The assistant sheet keeps a typed draft: swipe-to-dismiss is disabled while a draft exists, and 닫기 asks 버리기 / 계속 쓰기 first.
- Counts agree across screens because the server computes them from the same rows; the app never derives or stores display numbers.
- Every server-backed screen has loaded, loading (progress indicator), empty, and error-with-retry states. A failed refresh keeps the last loaded data and says so.

## Screens

### Root (tab bar)
- Primary action: switch between 오늘, 캘린더, 운영, 설정.
- Priorities: 1) the four tabs, 2) the assistant accessory with a separate mic button on every tab, 3) the 운영 badge showing the items that need action.
- Left out on purpose: a fifth tab, actions inside the tab bar.
- Layout: tab bar with sidebarAdaptable (bottom on iPhone, top on iPad); each tab owns its NavigationStack; scroll owner is each tab's List; the tab bar minimizes on scroll unless Reduce Motion is on. Anti-patterns: hidden or disabled tabs, accessory shown only on some tabs.

### 오늘
- Primary action: the first state-changing card action of the selected segment (for example 포장 완료하기 on 배송).
- Priorities: 1) the three numbers for today, 2) the segment control (할 일 / 채널 / 배송 / 비서 추천), 3) the grouped rows with done toggles and status badges. 예약 rows sit on a vertical timeline; checking any row strikes its title through in place.
- Left out on purpose: monthly statistics, settings, a second prominent button.
- Layout: List insetGrouped; scroll owner is the List; large title is a one-line headline of the most urgent work (`TodayHeadline`: overdue, class within two hours, waiting work, remaining today, all done, tomorrow/this week), always label-colored and at most 10 Hangul syllables, with a subtitle showing the date and the last update time; pull to refresh. Anti-patterns: nested segmented controls, card buttons that only navigate.

### 캘린더
- Primary action: pick a day and read its schedule.
- Priorities: 1) the week strip (default) or the month calendar, 2) the selected day's schedule.
- Left out on purpose: an hour grid; the timeline lists rows in time order instead.
- Layout: "모노 타임라인". One white ScrollView, no cards on gray, margins 20pt, system large title "캘린더" with a "오늘 일정 N건" subtitle and + in the toolbar, like the other tabs. Colors come only from `CalendarTokens` (background, label, secondary, tertiary, separator, fill, pinned); label is the only accent. Week strip and month grid share `PeriodNavigator` and `DayCell`; dots under a date count schedule (1, 2, or 3 dots), never kind. All-day rows and the day's orders go to a pinned box; everything else is a timeline whose node shape is the kind (filled circle booking, square delivery, hollow circle task) and whose weight is the state (gray check done, boldest next with a duration bar, semibold upcoming). Tasks and owner-added events carry a trailing 26pt check circle with a 44pt target, in the same place as the today rows; the node stays a marker, not a button. A check shows at once (strikethrough, gray node, "완료", success haptic) before the server answers, reverts on failure, and raises an undo toast. Today shows a current-time line, refreshed every minute. Date controls stop at xxxLarge Dynamic Type; at accessibility sizes the time moves above the title. A task whose time has passed unfinished is `missed`: red dashed node, "지남" in red, and an "오늘로 옮기기" button; a parcel past pickup shows "기한 지남". Red (`overdueRed`) appears only there. Days with no timed rows show an empty message and hide the legend. Anti-patterns: per-kind colors, orange emphasis, a system graphical date picker, order receipt times in the timeline.

### 운영
- Primary action: open the first item under 먼저 확인해주세요.
- Priorities: 1) 먼저 확인해주세요 with three tappable counts, 2) the monthly summary (labelled ring with "N건 중 M건 처리", four numbers (예약, 주문, 배송, 문의) each with a one-line explanation, a period button that opens a start-to-end calendar), 3) the four work areas, then 기회.
- Left out on purpose: charts.
- Layout: List insetGrouped; scroll owner is the List; rows push OperationAreaView with an optional preset filter. Anti-patterns: a non-tappable urgent summary, a period control that looks like plain text.

### 예약 관리, 주문 관리, 배송 관리, SNS·스토어 관리
- Primary action: the first state-changing action in the filtered list (for example 입금 확인하기).
- Priorities: 1) three numbers, 2) the status filter (short labels, counts live in the numbers), 3) the filtered cards with deadlines emphasized.
- Left out on purpose: counts inside filter labels, single-item menus.
- 먼저 확인해주세요 counts equal their filtered lists: 예약금 대기, 문의, and 발송 예정. SNS·스토어 filters are 전체, 채널, 문의, 콘텐츠.
- States: with no data the screen shows its own empty state, with 예약 등록하기 where booking creation exists; a filter or search with no match shows ContentUnavailableView and offers 전체 보기 only when another filter is selected.
- Layout: List insetGrouped under an inline title; scroll owner is the List; the search field stays visible in the navigation bar drawer; search and filter both narrow the list, and an empty result shows ContentUnavailableView (search or filter). Anti-patterns: filters that do not filter, more than one prominent button.

### 설정
- Primary action: open a settings row.
- Priorities: 1) the studio profile, 2) studio settings, 3) help.
- Left out on purpose: an in-app appearance setting.
- Layout: List insetGrouped; scroll owner is the List; rows push the workshop form, editable policy text, and channel status.

### 비서 sheet
- Primary action: send a question.
- Priorities: 1) the focused text field with the send button, 2) three suggested questions, 3) the reminder that the assistant can be wrong.
- Left out on purpose: stacked sheets.
- Layout: sheet with medium and large detents and a visible grabber; the composer sits in the bottom safe area; scroll owner is the message list. Anti-patterns: a decorative mic that does nothing different.
