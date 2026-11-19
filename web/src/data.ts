export type Metric = { readonly value: string; readonly label: string };
export type Tone = "attention" | "done" | "progress" | "neutral";
export type Status = { readonly text: string; readonly tone: Tone };
export type EventKind = "booking" | "order" | "delivery" | "todo";
export type AreaId = "bookings" | "orders" | "deliveries" | "channels";

export function assertNever(value: never): never {
  throw new Error(`Unhandled variant: ${JSON.stringify(value)}`);
}

const st = (text: string, tone: Tone): Status => ({ text, tone });
const m = (value: string, label: string): Metric => ({ value, label });

// 오늘 탭의 배송·재료 타일만 색과 아이콘을 쓴다. 캘린더·운영은 label만 쓴다.
export const kindInfo: Record<EventKind, { readonly label: string; readonly color: string; readonly symbol: string; readonly area?: AreaId }> = {
  booking: { label: "예약", color: "var(--blue)", symbol: "calendar", area: "bookings" },
  order: { label: "주문", color: "var(--brown)", symbol: "bag", area: "orders" },
  delivery: { label: "배송", color: "var(--teal)", symbol: "box", area: "deliveries" },
  todo: { label: "할 일", color: "var(--purple)", symbol: "checklist" },
};

export const toneInfo: Record<Tone, { readonly color: string; readonly symbol: string }> = {
  attention: { color: "var(--orange)", symbol: "exclFill" },
  done: { color: "var(--green)", symbol: "checkFill" },
  progress: { color: "var(--secondary)", symbol: "progress" },
  neutral: { color: "var(--secondary)", symbol: "circle" },
};

export const todayDay = 4;
const sundayFirst = ["일", "월", "화", "수", "목", "금", "토"] as const;
export const weekdayName = (day: number) => sundayFirst[new Date(2026, 10, day).getDay()] ?? "";

export const bookingIds = ["booking-1", "booking-2", "booking-3", "booking-4"] as const;
export type BookingId = (typeof bookingIds)[number];
export type Booking = {
  readonly id: BookingId;
  readonly title: string;
  readonly day: number;
  readonly start: string;
  readonly end: string;
  readonly booker: string;
  readonly people: number;
  readonly minutes: number;
  readonly channel: string;
  readonly deadline?: string;
  readonly note?: string;
  readonly deposit: boolean;
  readonly attended: boolean;
};
export const seedBookings: Readonly<Record<BookingId, Booking>> = {
  "booking-1": { id: "booking-1", title: "도자기 원데이 클래스", day: 4, start: "10:00", end: "11:30", booker: "정은주 님 외 3명", people: 4, minutes: 90, channel: "네이버 예약", deposit: true, attended: true },
  "booking-2": { id: "booking-2", title: "나만의 머그컵 만들기", day: 4, start: "14:00", end: "16:00", booker: "박*은 님 외 3명", people: 4, minutes: 120, channel: "네이버 예약", deposit: false, attended: false, deadline: "입금 기한 오늘 18:00" },
  "booking-3": { id: "booking-3", title: "주말 도자기 클래스", day: 7, start: "10:00", end: "12:00", booker: "이*진 님 외 5명", people: 6, minutes: 120, channel: "네이버 예약", deposit: true, attended: false, note: "남은 자리 3개" },
  "booking-4": { id: "booking-4", title: "원데이 물레 체험", day: 8, start: "11:00", end: "12:30", booker: "최*우 님", people: 1, minutes: 90, channel: "네이버 예약", deposit: false, attended: false, deadline: "입금 기한 내일 12:00" },
};

export const workIds = [
  "order-1042", "order-1043", "order-1044",
  "delivery-1042", "delivery-1043", "delivery-1038", "delivery-1044", "delivery-1031",
  "material-clay", "material-m", "channel-instagram", "channel-naver",
] as const;
export type WorkId = (typeof workIds)[number];
export type PerformAction = { readonly label: string; readonly doneText: string; readonly doneStatus: Status };
export type WorkItem = {
  readonly id: WorkId;
  readonly title: string;
  readonly status: Status;
  readonly lines: readonly string[];
  readonly deadline?: string;
  readonly tag?: string;
  readonly perform?: PerformAction;
};
const perform = (label: string, doneText: string, doneStatus: Status): PerformAction => ({ label, doneText, doneStatus });
const confirmOrder = perform("주문 확인하기", "주문을 확인했어요", st("확인 완료", "done"));
export const workItems: Readonly<Record<WorkId, WorkItem>> = {
  "order-1042": { id: "order-1042", title: "머그컵 2종 세트", status: st("결제 완료", "done"), lines: ["#1042 · 11월 4일 주문 · 네이버 스토어", "김*연 · 1개 · 42,000원"], tag: "결제 완료", perform: confirmOrder },
  "order-1043": { id: "order-1043", title: "오롯 세라믹 플레이트", status: st("처리 중", "progress"), lines: ["#1043 · 11월 4일 주문 · 네이버 스토어", "이*진 · 2개 · 56,000원"], tag: "처리 중" },
  "order-1044": { id: "order-1044", title: "핸드메이드 미니 화병", status: st("결제 완료", "done"), lines: ["#1044 · 11월 4일 주문 · 네이버 스토어", "정*우 · 1개 · 28,000원"], tag: "결제 완료", perform: confirmOrder },
  "delivery-1042": { id: "delivery-1042", title: "머그컵 2종 세트", status: st("포장 대기", "attention"), lines: ["#1042 · 김*연 · 1개", "깨지지 않게 포장 필요"], deadline: "오늘 16:00 택배 수거", tag: "발송 예정", perform: perform("포장 완료하기", "포장을 완료했어요", st("포장 완료", "done")) },
  "delivery-1043": { id: "delivery-1043", title: "오롯 세라믹 플레이트", status: st("송장 대기", "attention"), lines: ["#1043 · 이*진 · 2개", "포장 완료 · 오늘 발송 예정"], tag: "발송 예정", perform: perform("송장 등록하기", "송장을 등록했어요", st("송장 등록", "done")) },
  "delivery-1038": { id: "delivery-1038", title: "핸드메이드 커피잔", status: st("배송 중", "progress"), lines: ["#1038 · 최*서 · 1개", "택배사 인계 완료 · 내일 도착 예정"], tag: "배송 중" },
  "delivery-1044": { id: "delivery-1044", title: "도자기 찬기 3종 세트", status: st("배송 중", "progress"), lines: ["#1044 · 안*지 · 1개", "오늘 도착 예정"], tag: "배송 중" },
  "delivery-1031": { id: "delivery-1031", title: "핸드메이드 머그컵", status: st("배송 완료", "done"), lines: ["#1031 · 윤*아 · 1개", "11월 3일 도착"], tag: "완료" },
  "material-clay": { id: "material-clay", title: "도자기용 점토 50kg", status: st("주문 필요", "attention"), lines: ["도예사"], perform: perform("주문 완료로 표시", "재료를 주문했어요", st("주문 완료", "done")) },
  "material-m": { id: "material-m", title: "도자기용 점토 50kg", status: st("주문 완료", "done"), lines: ["점토M"] },
  "channel-instagram": { id: "channel-instagram", title: "Instagram", status: st("연결됨", "done"), lines: ["@orot.studio · 팔로워 1,284", "이번 주 +24 · 게시물 초안 2건"], tag: "채널" },
  "channel-naver": { id: "channel-naver", title: "네이버 스마트스토어", status: st("연결됨", "done"), lines: ["오롯 공방 · 이번 달 주문 38건", "오늘 주문 3건 · 결제금액 126,000원"], tag: "채널" },
};
export const shipTodayIds: readonly WorkId[] = ["delivery-1042", "delivery-1043"];
export const inTransitIds: readonly WorkId[] = ["delivery-1044", "delivery-1038"];
export const channelCardIds: readonly WorkId[] = ["channel-instagram", "channel-naver"];
export const todayWorkGroups: readonly { readonly title: string; readonly kind: EventKind; readonly area?: AreaId; readonly ids: readonly WorkId[] }[] = [
  { title: "배송", kind: "delivery", area: "deliveries", ids: ["delivery-1042", "delivery-1043"] },
  { title: "재료 주문", kind: "order", ids: ["material-clay", "material-m"] },
];

export const draftIds = ["inquiry-clay", "inquiry-group", "inquiry-change", "promo-weekend", "promo-turtle", "notice-pickup", "market-suncheon"] as const;
export type DraftId = (typeof draftIds)[number];
export type DraftKind = "inquiry" | "promo" | "notice" | "market";
export type DraftStatus = "pending" | "approved" | "rejected";
type DraftBase = {
  readonly id: DraftId;
  readonly title: string;
  readonly lines: readonly string[];
  readonly tag?: string;
  readonly text: string;
  readonly alternates: readonly string[];
  readonly status: DraftStatus;
  readonly edited: boolean;
  readonly error?: string;
  readonly editing?: string;
};
export type DraftContext =
  | { readonly kind: "inquiry"; readonly question: string; readonly facts: readonly string[] }
  | { readonly kind: "promo" }
  | { readonly kind: "notice" }
  | { readonly kind: "market" };
export type Draft = DraftBase & DraftContext;
const fresh = { status: "pending", edited: false } as const;
export const seedDrafts: Readonly<Record<DraftId, Draft>> = {
  "inquiry-clay": {
    ...fresh, id: "inquiry-clay", kind: "inquiry", title: "도자기 체험 준비물", lines: ["김하늘 (가상 고객)"], tag: "문의",
    question: "처음 도자기를 만들어 봐요. 준비물이 있을까요? 완성품은 당일 가져갈 수 있나요?",
    facts: ["공방 안내 · 앞치마와 도구는 공방에서 제공합니다.", "수업 안내 · 초보자도 참여할 수 있는 90분 수업입니다.", "제작 안내 · 건조와 소성에 약 3주가 필요하며 당일 수령은 불가합니다."],
    text: "안녕하세요! 처음 오셔도 괜찮아요. 앞치마와 도구는 준비되어 있습니다. 수업은 90분이며, 작품은 건조와 소성 후 약 3주 뒤 수령하실 수 있어요.",
    alternates: ["안녕하세요. 앞치마와 도구는 공방에서 드려서 따로 준비하실 건 없어요. 수업은 90분이고, 완성품은 건조와 소성을 거쳐 약 3주 뒤에 받으실 수 있어요."],
  },
  "inquiry-group": {
    ...fresh, id: "inquiry-group", kind: "inquiry", title: "두 사람 함께 참여", lines: ["이도윤 (가상 고객)"], tag: "문의",
    question: "친구와 둘이 같은 시간에 참여하고 싶어요. 예약이 바로 확정되나요?",
    facts: ["예약 규정 · 예약은 별도 확인 후 확정합니다.", "수업 정원 · 한 회차 최대 6명입니다.", "데모 규칙 · 문의 답변 승인으로 예약이 생성되지 않습니다."],
    text: "두 분이 함께 참여하실 수 있습니다. 원하시는 날짜와 회차를 알려 주시면 잔여 자리를 확인해 드릴게요. 이 답변만으로 예약이 확정되지는 않습니다.",
    alternates: ["네, 함께 오실 수 있어요. 희망 날짜와 회차를 알려 주시면 남은 자리를 확인해 드릴게요. 예약은 확인 후에 확정됩니다."],
  },
  "inquiry-change": {
    ...fresh, id: "inquiry-change", kind: "inquiry", title: "수업 일정 변경 안내", lines: ["박서연 (가상 고객)"], tag: "문의",
    question: "예약한 수업 날짜를 바꾸고 싶어요. 어떻게 하면 되나요?",
    facts: ["변경 규정 · 수업 2일 전까지 일정 변경을 요청할 수 있습니다.", "예약 규정 · 변경할 회차의 잔여 자리 확인이 필요합니다."],
    text: "수업 2일 전까지 일정 변경을 요청하실 수 있어요. 현재 예약일과 원하시는 날짜를 알려 주시면 잔여 자리를 확인해 드리겠습니다.",
    alternates: ["일정 변경은 수업 2일 전까지 가능해요. 지금 예약하신 날짜와 바꾸고 싶은 날짜를 알려 주시면 자리를 확인해 드릴게요."],
  },
  "promo-weekend": {
    ...fresh, id: "promo-weekend", kind: "promo", title: "주말 클래스 모집 글", lines: ["Instagram 게시물", "남은 3자리를 알릴 홍보 글이에요."], tag: "콘텐츠",
    text: "이번 주 토요일 오전 10시, 주말 도자기 클래스에 3자리가 남았어요. 흙을 처음 만져 보는 분도 함께하실 수 있어요. 신청은 프로필 링크에서 받아요.",
    alternates: ["토요일 오전, 흙과 함께 두 시간 보내실 분을 찾아요. 주말 도자기 클래스 남은 자리는 3개예요. 프로필 링크에서 신청해 주세요."],
  },
  "promo-turtle": {
    ...fresh, id: "promo-turtle", kind: "promo", title: "거북이 키링 이벤트 결과 글", lines: ["Instagram 게시물", "당첨자 발표를 담은 글이에요."], tag: "콘텐츠",
    text: "행운의 거북이 도자기 키링 이벤트에 함께해 주셔서 고마워요. 당첨되신 분께는 오늘 안에 개별 메시지를 보내 드릴게요.",
    alternates: ["거북이 키링 이벤트 결과를 알려 드려요. 당첨되신 분께 오늘 개별로 연락드릴게요. 참여해 주신 모든 분께 고마워요."],
  },
  "notice-pickup": {
    ...fresh, id: "notice-pickup", kind: "notice", title: "작품 수령 안내", lines: ["소성이 끝난 작품 2건이 수령 대기 중이에요.", "손님께 보낼 수령 안내를 준비했어요."],
    text: "안녕하세요, 오롯 공방이에요. 맡겨 주신 작품의 소성이 끝났어요. 공방에 들르실 수 있는 날을 알려 주세요.",
    alternates: ["작품이 완성되었어요. 편하신 날 공방에 들러 찾아가 주세요. 오시기 전에 날짜를 알려 주시면 준비해 둘게요."],
  },
  "market-suncheon": {
    ...fresh, id: "market-suncheon", kind: "market", title: "순천 달빛야행 플리마켓 소개 글", lines: ["순천시청 · 순천그린광장 달빛야행 플리마켓 모집 공고", "참가 조건을 확인하고 공방 작품을 소개해 보세요."],
    text: "오롯 공방은 손으로 빚은 머그컵과 접시를 만드는 도자기 공방이에요. 달빛야행 플리마켓에서 일상에 쓰는 그릇을 소개하고 싶어요.",
    alternates: ["일상에서 쓰는 도자기를 만드는 오롯 공방이에요. 이번 플리마켓에서 머그컵과 접시를 직접 보여 드리고 싶어요."],
  },
};
export const inquiryIds: readonly DraftId[] = ["inquiry-clay", "inquiry-group", "inquiry-change"];
export const promoIds: readonly DraftId[] = ["promo-weekend", "promo-turtle"];
export const todaySuggestionIds: readonly DraftId[] = ["notice-pickup", "promo-weekend", "market-suncheon"];
export const channelTodoDraftId: DraftId = "promo-turtle";

export type LiveCounts = { readonly deposit: number; readonly inquiry: number; readonly promo: number; readonly ship: number; readonly suggestions: number };

export type TodaySegment = "할 일" | "채널" | "배송" | "비서 추천";
export const todaySegments: readonly TodaySegment[] = ["할 일", "채널", "배송", "비서 추천"];
export function todayMetrics(segment: TodaySegment, c: LiveCounts): readonly Metric[] {
  switch (segment) {
    case "할 일": return [m("8명", "예약"), m("3건", "새 주문"), m(`${c.ship}건`, "발송 예정")];
    case "채널": return [m("1,284", "SNS 팔로워"), m("3건", "새 주문"), m(`${c.inquiry}건`, "미답변 문의")];
    case "배송": return [m(`${c.ship}건`, "발송 예정"), m("2건", "배송 중"), m("1건", "배송 완료")];
    case "비서 추천": return [m("3개", "오늘의 추천"), m(`${c.suggestions}건`, "검토할 초안"), m("1건", "확인 필요")];
    default: return assertNever(segment);
  }
}
export function areaMetrics(area: AreaId, c: LiveCounts): readonly Metric[] {
  switch (area) {
    case "bookings": return [m("32건", "전체"), m(`${26 - c.deposit}건`, "확정"), m(`${c.deposit}건`, "예약금 대기")];
    case "orders": return [m("38건", "전체 주문"), m("8건", "처리 대기"), m("126만원", "이번 달 매출")];
    case "deliveries": return [m(`${c.ship}건`, "발송 예정"), m("2건", "배송 중"), m("1건", "배송 완료")];
    case "channels": return [m("2개", "연결 채널"), m(`${c.inquiry}건`, "미답변 문의"), m(`${c.promo}건`, "홍보 초안")];
    default: return assertNever(area);
  }
}

export type DayEvent = { readonly kind: EventKind; readonly count: number };
export const novemberEvents: Readonly<Partial<Record<number, readonly DayEvent[]>>> = {
  2: [{ kind: "booking", count: 2 }],
  3: [{ kind: "order", count: 1 }],
  4: [{ kind: "booking", count: 2 }, { kind: "order", count: 1 }, { kind: "delivery", count: 1 }, { kind: "todo", count: 1 }],
  5: [{ kind: "delivery", count: 2 }],
  6: [{ kind: "todo", count: 1 }],
  7: [{ kind: "booking", count: 3 }],
  8: [{ kind: "booking", count: 1 }],
  10: [{ kind: "booking", count: 2 }],
  12: [{ kind: "delivery", count: 2 }],
  14: [{ kind: "booking", count: 4 }],
  17: [{ kind: "order", count: 1 }],
  19: [{ kind: "delivery", count: 2 }],
  21: [{ kind: "booking", count: 3 }],
  24: [{ kind: "todo", count: 1 }],
  27: [{ kind: "order", count: 2 }],
  28: [{ kind: "booking", count: 4 }],
};
export const eventCount = (day: number) => (novemberEvents[day] ?? []).reduce((sum, e) => sum + e.count, 0);

export type AgendaTarget = { readonly kind: "area"; readonly area: AreaId } | { readonly kind: "draft"; readonly id: DraftId };
export type AgendaEntry =
  | { readonly time: string; readonly kind: "booking"; readonly id: BookingId }
  | { readonly time: string; readonly kind: "order" | "delivery" | "todo"; readonly title: string; readonly detail: string; readonly target: AgendaTarget };
export const agenda: Readonly<Partial<Record<number, readonly AgendaEntry[]>>> = {
  4: [
    { time: "10:00", kind: "booking", id: "booking-1" },
    { time: "13:00", kind: "order", title: "온라인 주문 확인", detail: "머그컵 세트 · 신규 주문 3건", target: { kind: "area", area: "orders" } },
    { time: "14:00", kind: "booking", id: "booking-2" },
    { time: "16:00", kind: "delivery", title: "택배 발송 마감", detail: "포장 완료 2건 · 택배 수거 예정", target: { kind: "area", area: "deliveries" } },
    { time: "17:00", kind: "todo", title: "플리마켓 모집 조건 확인", detail: "순천그린광장 달빛야행", target: { kind: "draft", id: "market-suncheon" } },
  ],
};

export type AreaEntry = { readonly kind: "work"; readonly id: WorkId } | { readonly kind: "draft"; readonly id: DraftId };
export type Area = {
  readonly id: AreaId; readonly title: string; readonly summary: string; readonly count: string; readonly symbol: string;
  readonly filters: readonly string[]; readonly searchPrompt: string; readonly listTitle: string; readonly emptyTitle: string;
  readonly noDataTitle: string; readonly noDataMessage: string; readonly noDataAction?: string; readonly sortOptions: readonly string[];
  readonly entries: readonly AreaEntry[];
};
const work = (id: WorkId): AreaEntry => ({ kind: "work", id });
const draft = (id: DraftId): AreaEntry => ({ kind: "draft", id });
export const areas: Record<AreaId, Area> = {
  bookings: {
    id: "bookings", title: "예약 관리", summary: "예약금·일정 변경·출석을 관리해요", count: "32건", symbol: "calendarCheck",
    filters: ["전체", "확정", "예약금 대기"], searchPrompt: "예약자명 또는 클래스 검색", listTitle: "예약 목록",
    emptyTitle: "해당하는 예약이 없어요", noDataTitle: "아직 예약이 없어요", noDataMessage: "네이버 예약을 연결하거나\n직접 등록해\u00a0보세요.",
    noDataAction: "예약 등록하기", sortOptions: [], entries: [],
  },
  orders: {
    id: "orders", title: "주문 관리", summary: "주문 확인부터 처리 상태까지", count: "38건", symbol: "bag",
    filters: ["전체", "결제 완료", "처리 중"], searchPrompt: "주문번호 또는 고객명 검색", listTitle: "주문 목록",
    emptyTitle: "해당하는 주문이 없어요", noDataTitle: "아직 주문이 없어요", noDataMessage: "스마트스토어를 연결하면\n주문이 여기에 모여요.",
    noDataAction: "채널 연결하기", sortOptions: ["최근 주문순", "오래된 주문순"],
    entries: [work("order-1042"), work("order-1043"), work("order-1044")],
  },
  deliveries: {
    id: "deliveries", title: "배송 관리", summary: "포장·송장·배송 현황을 확인해요", count: "5건", symbol: "box",
    filters: ["전체", "발송 예정", "배송 중", "완료"], searchPrompt: "주문번호 또는 운송장 검색", listTitle: "발송·배송 목록",
    emptyTitle: "해당하는 배송이 없어요", noDataTitle: "발송할 물건이 없어요", noDataMessage: "주문이 들어오면\n발송할 물건이 여기에 생겨요.",
    sortOptions: ["마감 임박순", "늦은 마감순"],
    entries: [work("delivery-1042"), work("delivery-1043"), work("delivery-1038"), work("delivery-1044"), work("delivery-1031")],
  },
  channels: {
    id: "channels", title: "SNS·스토어 관리", summary: "채널과 문의, 콘텐츠를 관리해요", count: "2개", symbol: "bubbles",
    filters: ["전체", "채널", "문의", "콘텐츠"], searchPrompt: "채널 또는 콘텐츠 검색", listTitle: "채널과 할 일",
    emptyTitle: "해당하는 항목이 없어요", noDataTitle: "연결된 채널이 없어요", noDataMessage: "인스타그램과 네이버 스마트스토어를\n연결해\u00a0보세요.",
    noDataAction: "채널 연결하기", sortOptions: [],
    entries: [work("channel-instagram"), work("channel-naver"), draft("inquiry-clay"), draft("inquiry-group"), draft("inquiry-change"), draft("promo-weekend"), draft("promo-turtle")],
  },
};
export const areaOrder: readonly AreaId[] = ["bookings", "orders", "deliveries", "channels"];

export const settingsSections: readonly { readonly title?: string; readonly rows: readonly { readonly title: string; readonly symbol: string }[] }[] = [
  { title: "공방", rows: [{ title: "공방 정보", symbol: "storefront" }, { title: "예약·환불 규정", symbol: "docText" }, { title: "고객 안내 문구", symbol: "textBubble" }, { title: "채널 연결", symbol: "link" }] },
  { title: "팀", rows: [{ title: "직원·권한", symbol: "person2" }] },
  { title: "나", rows: [{ title: "알림", symbol: "bell" }, { title: "계정", symbol: "personCircle" }] },
  { rows: [{ title: "도움말", symbol: "question" }] },
];

export const assistantSuggestions = ["오늘 발송할 주문 알려줘", "예약금 안 낸 손님 알려줘", "주말 클래스 홍보 글 써 줘"];

export type ScreenState = "loaded" | "loading" | "empty" | "error";
export const launchState: ScreenState = (() => {
  const value = new URLSearchParams(location.search).get("state");
  return value === "loading" || value === "empty" || value === "error" ? value : "loaded";
})();
