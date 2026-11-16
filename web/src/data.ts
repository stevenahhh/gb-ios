export type Metric = { value: string; label: string };
export type Tone = "attention" | "done" | "progress" | "neutral";
export type Status = { text: string; tone: Tone };
export type CardAction = { kind: "perform"; label: string } | { kind: "open" };

export type WorkItem = {
  id: string;
  title: string;
  status?: Status;
  lines: string[];
  deadline?: string;
  tag?: string;
  action?: CardAction;
};

export type TaskItem = { id: string; time?: string; title: string; detail: string; status?: Status; isDone?: boolean };
export type EventKind = "booking" | "order" | "delivery" | "todo";
export type TaskGroup = { title: string; kind: EventKind; area?: AreaId; items: TaskItem[] };
export type DayEvent = { kind: EventKind; count: number };
export type AgendaItem = { id: string; time: string; title: string; kind: EventKind; detail: string };
export type AreaId = "bookings" | "orders" | "deliveries" | "channels";

let seq = 0;
const id = () => `i${++seq}`;
const st = (text: string, tone: Tone): Status => ({ text, tone });
const perform = (label: string): CardAction => ({ kind: "perform", label });
const open: CardAction = { kind: "open" };
const work = (item: Omit<WorkItem, "id">): WorkItem => ({ id: id(), ...item });
const task = (item: Omit<TaskItem, "id">): TaskItem => ({ id: id(), ...item });

export const kindInfo: Record<EventKind, { label: string; color: string; symbol: string; area?: AreaId }> = {
  booking: { label: "예약", color: "var(--blue)", symbol: "calendar", area: "bookings" },
  order: { label: "주문", color: "var(--brown)", symbol: "bag", area: "orders" },
  delivery: { label: "배송", color: "var(--teal)", symbol: "box", area: "deliveries" },
  todo: { label: "할 일", color: "var(--purple)", symbol: "checklist" },
};
export const kinds: EventKind[] = ["booking", "order", "delivery", "todo"];

export const toneInfo: Record<Tone, { color: string; symbol: string }> = {
  attention: { color: "var(--orange)", symbol: "exclFill" },
  done: { color: "var(--green)", symbol: "checkFill" },
  progress: { color: "var(--secondary)", symbol: "progress" },
  neutral: { color: "var(--secondary)", symbol: "circle" },
};

export const attentionCount = 7;
export const todayDay = 4;

export type TodaySegment = "할 일" | "채널" | "배송" | "비서 추천";
export const todaySegments: TodaySegment[] = ["할 일", "채널", "배송", "비서 추천"];
export const todayMetrics: Record<TodaySegment, Metric[]> = {
  "할 일": [{ value: "8명", label: "예약" }, { value: "3건", label: "새 주문" }, { value: "2건", label: "발송 예정" }],
  채널: [{ value: "1,284", label: "SNS 팔로워" }, { value: "3건", label: "새 주문" }, { value: "3건", label: "미답변 문의" }],
  배송: [{ value: "2건", label: "발송 예정" }, { value: "2건", label: "배송 중" }, { value: "1건", label: "배송 완료" }],
  "비서 추천": [{ value: "3개", label: "오늘의 추천" }, { value: "2건", label: "준비된 초안" }, { value: "1건", label: "확인 필요" }],
};

export const todayTaskGroups: TaskGroup[] = [
  { title: "예약", kind: "booking", area: "bookings", items: [
    task({ time: "10:00", title: "도자기 원데이 클래스", detail: "네이버 · 정은주 님 외 3명 · 90분", isDone: true }),
    task({ time: "14:00", title: "나만의 머그컵 만들기", detail: "4명 · 120분", isDone: false }),
  ] },
  { title: "배송", kind: "delivery", area: "deliveries", items: [
    task({ title: "머그컵 세트 발송", detail: "네이버 · 2건 · 포장 필요", status: st("포장 대기", "attention") }),
    task({ title: "그릇·접시 세트 발송", detail: "인스타그램 · 2건 · 출고 완료", status: st("발송 완료", "done") }),
  ] },
  { title: "재료 주문", kind: "order", items: [
    task({ title: "도자기용 점토 50kg", detail: "도예사", status: st("주문 필요", "attention") }),
    task({ title: "도자기용 점토 50kg", detail: "점토M", status: st("주문 완료", "done") }),
  ] },
];

export const channelCards: WorkItem[] = [
  work({ title: "Instagram", status: st("연결됨", "done"), lines: ["@orot.studio", "팔로워 1,284 · 이번 주 +24"], action: open }),
  work({ title: "네이버 스마트스토어", status: st("연결됨", "done"), lines: ["오늘 주문 3건 · 결제금액 126,000원"], deadline: "상품 문의 3건이 답을 기다려요", action: open }),
];
export const channelTodos: WorkItem[] = [
  work({ title: "행운의 거북이 도자기 키링 이벤트", lines: ["오늘 결과 발표일이에요."], action: perform("이벤트 결과 올리기") }),
  work({ title: "SNS 콘텐츠 미리보기", lines: ["오늘 올릴 게시물을 확인해 주세요."], action: open }),
];
export const shipToday: WorkItem[] = [
  work({ title: "머그컵 2종 세트", status: st("포장 대기", "attention"), lines: ["김*연 · 주문 #1042 · 1개"], action: perform("포장 완료하기") }),
  work({ title: "오롯 세라믹 플레이트", status: st("송장 대기", "attention"), lines: ["이*진 · 주문 #1043 · 2개"], action: perform("송장 등록하기") }),
];
export const inTransit: WorkItem[] = [
  work({ title: "도자기 찬기 3종 세트", status: st("배송 중", "progress"), lines: ["안*지 · 주문 #1044 · 1개", "오늘 도착 예정"], action: open }),
  work({ title: "핸드메이드 커피잔", status: st("배송 중", "progress"), lines: ["최*서 · 주문 #1038 · 1개", "내일 도착 예정"], action: open }),
];
export const suggestions: WorkItem[] = [
  work({ title: "작품 수령을 기다리는 손님이 있어요", lines: ["소성이 끝난 작품 2건이 수령 대기 중이에요.", "손님께 보낼 수령 안내를 준비할까요?"], action: perform("수령 안내 준비하기") }),
  work({ title: "주말 클래스의 빈자리를 알려요", lines: ["토요일 클래스에 3자리가 남아 있어요.", "SNS에 올릴 모집 글을 준비해 두었어요."], action: open }),
  work({ title: "순천 달빛야행 플리마켓, 참여해볼까요?", lines: ["순천시청 · 순천그린광장 달빛야행 플리마켓 모집 공고", "참가 조건을 확인하고 공방 작품을 소개해보세요."], action: open }),
];

export const novemberEvents: Record<number, DayEvent[]> = {
  2: [{ kind: "booking", count: 2 }],
  3: [{ kind: "order", count: 1 }],
  4: [{ kind: "booking", count: 1 }, { kind: "order", count: 1 }, { kind: "delivery", count: 1 }, { kind: "todo", count: 1 }],
  5: [{ kind: "delivery", count: 2 }],
  6: [{ kind: "todo", count: 1 }],
  7: [{ kind: "booking", count: 3 }],
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
export const agenda: Record<number, AgendaItem[]> = {
  4: [
    { id: id(), time: "10:00", title: "도자기 원데이 클래스", kind: "booking", detail: "예약 4명 · 90분" },
    { id: id(), time: "13:00", title: "온라인 주문 확인", kind: "order", detail: "머그컵 세트 · 신규 주문 3건" },
    { id: id(), time: "16:00", title: "택배 발송 마감", kind: "delivery", detail: "포장 완료 2건 · 택배 수거 예정" },
    { id: id(), time: "17:00", title: "플리마켓 모집 조건 확인", kind: "todo", detail: "순천그린광장 달빛야행" },
  ],
};
export const eventCount = (day: number) => (novemberEvents[day] ?? []).reduce((sum, e) => sum + e.count, 0);

export type Area = {
  id: AreaId; title: string; summary: string; count: string; symbol: string; metrics: Metric[]; filters: string[];
  searchPrompt: string; listTitle: string; emptyTitle: string; noDataTitle: string; noDataMessage: string;
  noDataAction?: string; sortOptions: string[]; items: WorkItem[];
};

export const areas: Record<AreaId, Area> = {
  bookings: {
    id: "bookings", title: "예약 관리", summary: "예약금·일정 변경·출석을 관리해요", count: "32건", symbol: "calendarCheck",
    metrics: [{ value: "32건", label: "전체" }, { value: "24건", label: "확정" }, { value: "2건", label: "예약금 대기" }],
    filters: ["전체", "확정", "예약금 대기"], searchPrompt: "예약자명 또는 클래스 검색", listTitle: "예약 목록",
    emptyTitle: "해당하는 예약이 없어요", noDataTitle: "아직 예약이 없어요", noDataMessage: "네이버 예약을 연결하거나\n직접 등록해\u00a0보세요.",
    noDataAction: "예약 등록하기", sortOptions: [],
    items: [
      work({ title: "도자기 원데이 클래스", status: st("확정", "done"), lines: ["11월 4일 수 · 10:00–11:30", "김*연 외 3명 · 예약금 확인 완료"], tag: "확정", action: open }),
      work({ title: "나만의 머그컵 만들기", status: st("예약금 대기", "attention"), lines: ["11월 5일 목 · 14:00–16:00", "박*은 · 2명"], deadline: "입금 기한 오늘 18:00", tag: "예약금 대기", action: perform("입금 확인하기") }),
      work({ title: "원데이 물레 체험", status: st("예약금 대기", "attention"), lines: ["11월 8일 일 · 11:00–12:30", "최*우 · 1명"], deadline: "입금 기한 내일 12:00", tag: "예약금 대기", action: perform("입금 확인하기") }),
      work({ title: "주말 도자기 클래스", status: st("확정", "done"), lines: ["11월 7일 토 · 10:00–12:00", "이*진 외 5명 · 남은 자리 3개"], tag: "확정", action: open }),
    ],
  },
  orders: {
    id: "orders", title: "주문 관리", summary: "주문 확인부터 처리 상태까지", count: "38건", symbol: "bag",
    metrics: [{ value: "38건", label: "전체 주문" }, { value: "8건", label: "처리 대기" }, { value: "126만원", label: "이번 달 매출" }],
    filters: ["전체", "결제 완료", "처리 중"], searchPrompt: "주문번호 또는 고객명 검색", listTitle: "주문 목록",
    emptyTitle: "해당하는 주문이 없어요", noDataTitle: "아직 주문이 없어요", noDataMessage: "스마트스토어를 연결하면\n주문이 여기에 모여요.",
    noDataAction: "채널 연결하기", sortOptions: ["최근 주문순", "오래된 주문순"],
    items: [
      work({ title: "머그컵 2종 세트", status: st("결제 완료", "done"), lines: ["#1042 · 11월 4일 주문 · 네이버 스토어", "김*연 · 1개 · 42,000원"], tag: "결제 완료", action: perform("주문 확인하기") }),
      work({ title: "오롯 세라믹 플레이트", status: st("처리 중", "progress"), lines: ["#1043 · 11월 4일 주문 · 네이버 스토어", "이*진 · 2개 · 56,000원"], tag: "처리 중", action: open }),
      work({ title: "핸드메이드 미니 화병", status: st("결제 완료", "done"), lines: ["#1044 · 11월 4일 주문 · 네이버 스토어", "정*우 · 1개 · 28,000원"], tag: "결제 완료", action: perform("주문 확인하기") }),
    ],
  },
  deliveries: {
    id: "deliveries", title: "배송 관리", summary: "포장·송장·배송 현황을 확인해요", count: "5건", symbol: "box",
    metrics: [{ value: "2건", label: "발송 예정" }, { value: "2건", label: "배송 중" }, { value: "1건", label: "배송 완료" }],
    filters: ["전체", "발송 예정", "배송 중", "완료"], searchPrompt: "주문번호 또는 운송장 검색", listTitle: "발송·배송 목록",
    emptyTitle: "해당하는 배송이 없어요", noDataTitle: "발송할 물건이 없어요", noDataMessage: "주문이 들어오면\n발송할 물건이 여기에 생겨요.",
    sortOptions: ["마감 임박순", "늦은 마감순"],
    items: [
      work({ title: "머그컵 2종 세트", status: st("포장 대기", "attention"), lines: ["#1042 · 김*연 · 1개", "깨지지 않게 포장 필요"], deadline: "오늘 16:00 택배 수거", tag: "발송 예정", action: perform("포장 완료하기") }),
      work({ title: "오롯 세라믹 플레이트", status: st("송장 대기", "attention"), lines: ["#1043 · 이*진 · 2개", "포장 완료 · 오늘 발송 예정"], tag: "발송 예정", action: perform("송장 등록하기") }),
      work({ title: "핸드메이드 커피잔", status: st("배송 중", "progress"), lines: ["#1038 · 최*서 · 1개", "택배사 인계 완료 · 내일 도착 예정"], tag: "배송 중", action: open }),
      work({ title: "도자기 찬기 3종 세트", status: st("배송 중", "progress"), lines: ["#1044 · 안*지 · 1개", "오늘 도착 예정"], tag: "배송 중", action: open }),
      work({ title: "핸드메이드 머그컵", status: st("배송 완료", "done"), lines: ["#1031 · 윤*아 · 1개", "11월 3일 도착"], tag: "완료", action: open }),
    ],
  },
  channels: {
    id: "channels", title: "SNS·스토어 관리", summary: "채널과 문의, 콘텐츠를 관리해요", count: "2개", symbol: "bubbles",
    metrics: [{ value: "2개", label: "연결 채널" }, { value: "3건", label: "미답변 문의" }, { value: "2건", label: "홍보 초안" }],
    filters: ["전체", "채널", "문의", "콘텐츠"], searchPrompt: "채널 또는 콘텐츠 검색", listTitle: "채널과 할 일",
    emptyTitle: "해당하는 항목이 없어요", noDataTitle: "연결된 채널이 없어요", noDataMessage: "인스타그램과 네이버 스마트스토어를\n연결해\u00a0보세요.",
    noDataAction: "채널 연결하기", sortOptions: [],
    items: [
      work({ title: "Instagram", status: st("연결됨", "done"), lines: ["@orot.studio · 팔로워 1,284", "이번 주 +24 · 게시물 초안 2건"], tag: "채널", action: open }),
      work({ title: "네이버 스마트스토어", status: st("연결됨", "done"), lines: ["오롯 공방 · 이번 달 주문 38건", "상품 문의 3건 · 리뷰 답글 대기 2건"], tag: "채널", action: open }),
      work({ title: "선물 포장이 되나요?", status: st("답변 대기", "attention"), lines: ["네이버 스마트스토어 · 머그컵 2종 세트", "김*연 · 오늘 09:12"], tag: "문의", action: perform("답변 쓰기") }),
      work({ title: "주말 클래스에 주차할 수 있나요?", status: st("답변 대기", "attention"), lines: ["Instagram DM · 주말 도자기 클래스", "박*은 · 오늘 08:40"], tag: "문의", action: perform("답변 쓰기") }),
      work({ title: "플레이트 다른 색도 있나요?", status: st("답변 대기", "attention"), lines: ["네이버 스마트스토어 · 오롯 세라믹 플레이트", "정*우 · 어제 21:05"], tag: "문의", action: perform("답변 쓰기") }),
      work({ title: "주말 클래스 모집 글", status: st("초안 준비", "progress"), lines: ["Instagram 게시물 · 비서가 작성", "남은 3자리를 알릴 홍보 글이에요."], tag: "콘텐츠", action: perform("홍보 글 검토하기") }),
      work({ title: "거북이 키링 이벤트 결과 글", status: st("초안 준비", "progress"), lines: ["Instagram 게시물 · 비서가 작성", "당첨자 발표를 담은 글이에요."], tag: "콘텐츠", action: perform("홍보 글 검토하기") }),
    ],
  },
};
export const areaOrder: AreaId[] = ["bookings", "orders", "deliveries", "channels"];

export const settingsSections: { title?: string; rows: { title: string; symbol: string }[] }[] = [
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
