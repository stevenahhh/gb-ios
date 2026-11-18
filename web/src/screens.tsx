import { useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "./icons";
import {
  agenda, areaOrder, areas, assertNever, assistantSuggestions, channelCardIds, channelTodoDraftId, eventCount, inTransitIds, kindInfo, launchState,
  novemberEvents, settingsSections, shipTodayIds, todayDay, todayMetrics, todaySegments, todaySuggestionIds, todayWorkGroups, weekdayName, workItems,
  type AreaId, type ScreenState, type TodaySegment,
} from "./data";
import { AgendaRow, BookingTaskRow, WorkCards, WorkTaskRow } from "./cards";
import { DraftCompact } from "./drafts";
import { novemberRange, PeriodPicker, rangeHeading, rangeLabel, type DayRange } from "./period";
import { attentionCount, liveCounts, todayBookings, useStore } from "./store";
import { EmptyState, LoadError, MetricStrip, PlaceholderBody, Row, Screen, Section, SectionHeader, Segmented, useNav } from "./ui";

function greeting(hour: number) {
  if (hour >= 5 && hour < 11) return "사장님, 좋은 아침이에요";
  if (hour >= 11 && hour < 17) return "사장님, 좋은 오후예요";
  if (hour >= 17 && hour < 22) return "사장님, 좋은 저녁이에요";
  return "사장님, 오늘도 수고했어요";
}

function koreanTime(d: Date) {
  const h = d.getHours();
  return `${h < 12 ? "오전" : "오후"} ${h % 12 || 12}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function TodayBody({ segment }: { segment: TodaySegment }) {
  const { push } = useNav();
  const { state } = useStore();
  const counts = liveCounts(state);
  switch (segment) {
    case "할 일":
      return (
        <div className="cols">
          <Section header={<SectionHeader title="예약" area="bookings" />}>
            {todayBookings(state).map((b) => <BookingTaskRow key={b.id} booking={b} />)}
          </Section>
          {todayWorkGroups.map((group) => (
            <Section key={group.title} header={<SectionHeader title={group.title} area={group.area} />}>
              {group.ids.map((id) => <WorkTaskRow key={id} item={workItems[id]} kind={group.kind} />)}
            </Section>
          ))}
        </div>
      );
    case "채널":
      return (
        <>
          <Section header={<SectionHeader title="채널 현황" area="channels" />} bodyClass="cards"><WorkCards ids={channelCardIds} /></Section>
          <Section header={<SectionHeader title="오늘 챙길 일 2건" />} bodyClass="cards">
            <DraftCompact id={channelTodoDraftId} />
            <Row chevron onClick={() => push({ kind: "area", area: "channels", filter: "콘텐츠" })}>
              <div className="summary-title sk">SNS 콘텐츠 미리보기</div>
              <div className="card-line sk">오늘 올릴 게시물을 확인해 주세요.</div>
            </Row>
          </Section>
        </>
      );
    case "배송":
      return (
        <>
          <Section header={<SectionHeader title={`오늘 발송할 물건 ${counts.ship}건`} area="deliveries" />} bodyClass="cards"><WorkCards ids={shipTodayIds} /></Section>
          <Section header={<SectionHeader title="이동 중인 배송" />}>
            <Row chevron onClick={() => push({ kind: "area", area: "deliveries", filter: "배송 중" })}>
              <div className="summary-title sk">배송 중 2건 · 오늘 도착 1건</div>
              <div className="card-line sk">배송 지연 없이 잘 이동하고 있어요.</div>
            </Row>
            <WorkCards ids={inTransitIds} />
          </Section>
        </>
      );
    case "비서 추천":
      return (
        <Section header={<SectionHeader title="오늘의 추천" />} footer="비서가 공방 현황을 보고 골랐어요. 틀릴 수 있으니 내용을 확인해 주세요." bodyClass="cards">
          {todaySuggestionIds.map((id) => <DraftCompact key={id} id={id} />)}
        </Section>
      );
    default:
      return assertNever(segment);
  }
}

export function TodayScreen() {
  const { push } = useNav();
  const { state } = useStore();
  const [segment, setSegment] = useState<TodaySegment>("할 일");
  const [screenState, setScreenState] = useState<ScreenState>(launchState);
  const now = useMemo(() => new Date(), []);
  const title = greeting(now.getHours());
  const subtitle = `11월 4일 수요일 · ${koreanTime(now)} 기준`;

  if (screenState === "error") return <Screen title={title} subtitle={subtitle} large><LoadError retry={() => setScreenState("loaded")} /></Screen>;
  if (screenState === "empty") {
    return (
      <Screen title={title} subtitle={subtitle} large>
        <EmptyState
          symbol="link"
          title="아직 연결된 채널이 없어요"
          message={"네이버 예약과 인스타그램을 연결하면\n오늘 할 일이 여기에 모여요."}
          action={<button className="btn btn-prominent btn-pill" onClick={() => push({ kind: "placeholder", title: "채널 연결", symbol: "link" })}>채널 연결하기</button>}
        />
      </Screen>
    );
  }

  return (
    <Screen title={title} subtitle={subtitle} large>
      <div className={screenState === "loading" ? "redacted" : undefined}>
        <Section><MetricStrip metrics={todayMetrics(segment, liveCounts(state))} /></Section>
        <div className="segmented-wrap"><Segmented label="보기" options={todaySegments} value={segment} onChange={setSegment} /></div>
        <TodayBody segment={segment} />
      </div>
    </Screen>
  );
}

const weekdays = ["월", "화", "수", "목", "금", "토", "일"];

function EventDot({ day }: { day: number }) {
  return <span className="dot-slot">{eventCount(day) > 0 ? <span className="dot" /> : null}</span>;
}

function WeekStrip({ day, onSelect }: { day: number; onSelect: (d: number) => void }) {
  return (
    <div className="week">
      {[2, 3, 4, 5, 6, 7, 8].map((d, i) => (
        <button key={d} className="week-day" onClick={() => onSelect(d)} aria-pressed={d === day} aria-label={`11월 ${d}일 ${weekdays[i]}요일, 일정 ${eventCount(d)}개`}>
          <span className="week-name">{weekdays[i]}</span>
          <span className={d === day ? "day-num day-on" : "day-num"}>{d}</span>
          <EventDot day={d} />
        </button>
      ))}
    </div>
  );
}

function MonthGrid({ day, onSelect }: { day: number; onSelect: (d: number) => void }) {
  const first = new Date(2026, 10, 1).getDay();
  return (
    <div className="month">
      <div className="month-grid">
        {["일", "월", "화", "수", "목", "금", "토"].map((w) => <span key={w} className="month-weekday">{w}</span>)}
        {Array.from({ length: first }, (_, i) => <span key={`blank-${i}`} />)}
        {Array.from({ length: 30 }, (_, i) => i + 1).map((d) => (
          <button key={d} className="month-cell" onClick={() => onSelect(d)} aria-pressed={d === day} aria-label={`11월 ${d}일, 일정 ${eventCount(d)}개`}>
            <span className={d === day ? "day-num day-on" : "day-num"}>{d}</span>
            <EventDot day={d} />
          </button>
        ))}
      </div>
    </div>
  );
}

export function CalendarScreen() {
  const { push } = useNav();
  const [mode, setMode] = useState<"주간" | "월간">("주간");
  const [day, setDay] = useState(todayDay);
  const [screenState, setScreenState] = useState<ScreenState>(launchState);
  const addEvent = () => push({ kind: "placeholder", title: "일정 추가", symbol: "calendarPlus" });
  const trailing = <button className="glass-circle" aria-label="일정 추가" onClick={addEvent}><Icon name="plus" size={20} weight={2.2} /></button>;
  const subtitle = screenState === "loaded" || screenState === "loading" ? `오늘 일정 ${eventCount(todayDay)}개` : undefined;

  if (screenState === "error") return <Screen title="캘린더" subtitle={subtitle} large trailing={trailing}><LoadError retry={() => setScreenState("loaded")} /></Screen>;
  if (screenState === "empty") {
    return (
      <Screen title="캘린더" subtitle={subtitle} large trailing={trailing}>
        <EmptyState symbol="calendar" title="아직 일정이 없어요" message={"예약과 할 일을 추가하면\n날짜별로 여기에 모여요."}
          action={<button className="btn btn-prominent btn-pill" onClick={addEvent}>일정 추가하기</button>} />
      </Screen>
    );
  }

  const events = novemberEvents[day];
  const items = agenda[day];
  const count = eventCount(day);
  const dayLabel = `11월 ${day}일 ${weekdayName(day)}요일`;
  return (
    <Screen title="캘린더" subtitle={subtitle} large trailing={trailing}>
      <div className={screenState === "loading" ? "redacted" : undefined}>
        <div className="segmented-wrap"><Segmented label="보기" options={["주간", "월간"]} value={mode} onChange={setMode} /></div>
        <Section spaced header={
          <div className="section-header-row">
            <span>{mode === "주간" ? "11월 2일 – 8일" : "2026년 11월"}</span>
            {day !== todayDay ? <button className="link" onClick={() => setDay(todayDay)}>오늘로</button> : null}
          </div>
        }>
          {mode === "주간" ? <WeekStrip day={day} onSelect={setDay} /> : <MonthGrid day={day} onSelect={setDay} />}
        </Section>
        <Section spaced header={count > 0 ? `${dayLabel} · 일정 ${count}개` : dayLabel}>
          {items ? (
            items.map((entry) => <AgendaRow key={`${entry.time}-${entry.kind}`} entry={entry} />)
          ) : events ? (
            events.map((e) => {
              const info = kindInfo[e.kind];
              const area = info.area;
              const body = <span className="summary-title sk">{info.label} {e.count}건</span>;
              return area ? <Row key={e.kind} chevron onClick={() => push({ kind: "area", area })}>{body}</Row> : <Row key={e.kind}>{body}</Row>;
            })
          ) : (
            <EmptyState symbol="calendar" title="이 날은 일정이 없어요" message="필요하면 일정을 추가해 보세요."
              action={<button className="btn btn-bordered btn-pill" onClick={addEvent}>일정 추가하기</button>} />
          )}
        </Section>
      </div>
    </Screen>
  );
}

export function OperationsScreen() {
  const { push } = useNav();
  const { state } = useStore();
  const counts = liveCounts(state);
  const attention = attentionCount(state);
  const [range, setRange] = useState<DayRange>(novemberRange);
  const [picking, setPicking] = useState(false);
  const checks: readonly { readonly title: string; readonly count: number; readonly area: AreaId; readonly filter: string }[] = [
    { title: "예약금 미확인", count: counts.deposit, area: "bookings", filter: "예약금 대기" },
    { title: "미답변 문의", count: counts.inquiry, area: "channels", filter: "문의" },
    { title: "발송 마감", count: counts.ship, area: "deliveries", filter: "발송 예정" },
  ];
  const picker = picking ? (
    <PeriodPicker value={range} onApply={(r) => { setRange(r); setPicking(false); }} onCancel={() => setPicking(false)} />
  ) : null;
  return (
    <Screen title="운영" subtitle={`먼저 확인할 일 ${attention}건`} large overlay={picker}>
      <div className="cols">
        <div>
          <Section spaced header={<div className="section-header-row"><span>먼저 확인해주세요</span><span>{attention}건</span></div>}>
            {checks.map((a) => (
              <Row key={a.title} chevron onClick={() => push({ kind: "area", area: a.area, filter: a.filter })}>
                <span className="labeled"><span>{a.title}</span><b>{a.count}건</b></span>
              </Row>
            ))}
          </Section>
          <Section spaced header={
            <div className="section-header-row">
              <span className="ops-heading">{rangeHeading(range)}</span>
              <button className="period-chip" aria-label={`기간 선택, ${rangeLabel(range)}`} aria-haspopup="dialog" onClick={() => setPicking(true)}>
                {rangeLabel(range)} <Icon name="chevronDown" size={14} weight={2.4} />
              </button>
            </div>
          }>
            <div className="row summary-box">
              <div className="gauge-wrap" aria-label="처리율 75퍼센트">
                <svg width="64" height="64" viewBox="0 0 64 64" aria-hidden="true">
                  <circle cx="32" cy="32" r="27" fill="none" stroke="var(--fill)" strokeWidth="6" />
                  <circle cx="32" cy="32" r="27" fill="none" stroke="var(--accent)" strokeWidth="6" strokeLinecap="round" strokeDasharray={`${2 * Math.PI * 27 * 0.75} ${2 * Math.PI * 27}`} transform="rotate(-90 32 32)" />
                  <text x="32" y="37" textAnchor="middle" className="gauge-text">75%</text>
                </svg>
                <span className="caption">처리율</span>
              </div>
              <div className="summary-grid">
                {[["예약", "24건"], ["주문", "8건"], ["배송", "5건"], ["SNS", "2개"]].map(([l, v]) => (
                  <div key={l}><div className="caption">{l}</div><div className="summary-value">{v}</div></div>
                ))}
              </div>
            </div>
            <div className="row compare">
              {["+12%", "+5%"].map((c, i) => (
                <div key={c} className={i ? "compare-cell compare-right" : "compare-cell"}><div className="caption">전월 대비</div><div className="compare-value">{c}</div></div>
              ))}
            </div>
          </Section>
        </div>
        <div>
          <Section spaced header="전체 업무 관리">
            {areaOrder.map((id) => {
              const a = areas[id];
              return (
                <Row key={id} chevron onClick={() => push({ kind: "area", area: id })}>
                  <span className="labeled">
                    <span className="labeled-text"><span>{a.title}</span><small>{a.summary}</small></span>
                    <span className="secondary-value">{a.count}</span>
                  </span>
                </Row>
              );
            })}
          </Section>
          <Section spaced header="공방 성장">
            <Row chevron onClick={() => push({ kind: "placeholder", title: "기회", symbol: "flag" })}>
              <span className="labeled"><span className="labeled-text"><span>기회</span><small>마켓·공모·지원사업 모집 공고</small></span></span>
            </Row>
            <Row chevron onClick={() => push({ kind: "placeholder", title: "리포트", symbol: "chart" })}>
              <span className="labeled"><span className="labeled-text"><span>리포트</span><small>주간·월간 숫자</small></span></span>
            </Row>
          </Section>
        </div>
      </div>
    </Screen>
  );
}

export function PlaceholderScreen({ title, symbol }: { title: string; symbol: string }) {
  return <Screen title={title} back><PlaceholderBody title={title} symbol={symbol} /></Screen>;
}

export function SettingsScreen() {
  const { push } = useNav();
  return (
    <Screen title="설정" subtitle="오롯 공방" large>
      <Section>
        <div className="row profile">
          <span className="profile-icon"><Icon name="storefront" size={26} color="var(--cell)" /></span>
          <span><b>오롯 공방</b><small>사장님</small></span>
        </div>
      </Section>
      {settingsSections.map((s, i) => (
        <Section key={i} header={s.title}>
          {s.rows.map((r) => (
            <Row key={r.title} chevron onClick={() => push({ kind: "placeholder", title: r.title, symbol: r.symbol })}>
              <span className="labeled"><Icon name={r.symbol} size={21} color="var(--accent)" /><span>{r.title}</span></span>
            </Row>
          ))}
        </Section>
      ))}
    </Screen>
  );
}

export function AssistantSheet({ voice, onClose }: { voice: boolean; onClose: () => void }) {
  const [message, setMessage] = useState("");
  const [sent, setSent] = useState<string[]>([]);
  const [large, setLarge] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => { field.current?.focus(); }, []);
  const draft = message.trim();
  const send = (text: string) => {
    const v = text.trim();
    if (!v) return;
    setSent((s) => [...s, v]);
    setMessage("");
  };
  const requestClose = () => (draft ? setConfirming(true) : onClose());
  return (
    <div className="sheet-layer">
      <div className="sheet-backdrop" onClick={requestClose} />
      <div className={large ? "sheet sheet-large" : "sheet"} role="dialog" aria-label="비서">
        <button className="grabber" aria-label={large ? "시트 줄이기" : "시트 크게 보기"} onClick={() => setLarge(!large)}><span /></button>
        <div className="sheet-bar">
          <button className="glass-circle" aria-label="닫기" onClick={requestClose}><Icon name="xmark" size={18} weight={2.4} /></button>
          <div className="navbar-title-main">비서</div>
          <span className="navbar-side" />
        </div>
        <div className="sheet-scroll">
          {sent.length === 0 ? (
            <div className="welcome">
              <Icon name="sparkles" size={40} color="var(--secondary)" />
              <div className="empty-title">무엇을 도와드릴까요?</div>
              <div className="empty-message">{voice ? "키보드의 마이크 버튼을 누르고 말로 물어보세요." : "예약, 주문, 배송, 홍보를 물어보세요."}</div>
              <div className="suggestions">
                {assistantSuggestions.map((s) => <button key={s} className="btn btn-bordered btn-pill" onClick={() => send(s)}>{s}</button>)}
              </div>
            </div>
          ) : (
            <div className="thread">
              {sent.map((t, i) => <div key={i} className="bubble">{t}</div>)}
              <div className="labeled muted"><Icon name="infoCircle" size={18} color="var(--secondary)" /><span>답변 기능은 아직 연결하지 않았어요.</span></div>
            </div>
          )}
        </div>
        <form className="composer" onSubmit={(e) => { e.preventDefault(); send(message); }}>
          <div className="composer-row">
            <input ref={field} className="composer-field" value={message} onChange={(e) => setMessage(e.target.value)} placeholder="예: 오늘 발송할 주문 알려줘" aria-label="비서에게 보낼 질문" enterKeyHint="send" />
            <button type="submit" className="send" aria-label="보내기" disabled={!draft}><Icon name="arrowUp" size={20} weight={2.6} /></button>
          </div>
          <div className="disclaimer">비서가 틀릴 수 있어요. 보내기 전에 내용을 확인해 주세요.</div>
        </form>
        {confirming ? (
          <div className="dialog-layer" onClick={() => setConfirming(false)}>
            <div className="action-sheet" role="alertdialog" aria-label="작성 중인 질문을 버릴까요?" onClick={(e) => e.stopPropagation()}>
              <div className="action-group">
                <div className="action-title">작성 중인 질문을 버릴까요?</div>
                <button className="action destructive" onClick={onClose}>버리기</button>
              </div>
              <button className="action action-cancel" onClick={() => setConfirming(false)}>계속 쓰기</button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
