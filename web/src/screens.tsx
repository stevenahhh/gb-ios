import { useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "./icons";
import {
  agenda, areaOrder, areas, assistantSuggestions, attentionCount, channelCards, channelTodos, eventCount, inTransit, kindInfo, kinds,
  launchState, novemberEvents, settingsSections, shipToday, suggestions, todayDay, todayMetrics, todaySegments, todayTaskGroups,
  type AreaId, type ScreenState, type TodaySegment, type WorkItem,
} from "./data";
import {
  AgendaRow, EmptyState, LoadError, MenuButton, MetricStrip, PlaceholderBody, Row, Screen, Section, SectionHeader, Segmented,
  StatusBadge, TaskRow, WorkCard, WorkCardRow, primaryId, useNav,
} from "./ui";

function Cards({ items }: { items: WorkItem[] }) {
  const first = primaryId(items);
  return <>{items.map((item) => <WorkCardRow key={item.id} item={item} primary={item.id === first} />)}</>;
}

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

export function TodayScreen() {
  const { push } = useNav();
  const [segment, setSegment] = useState<TodaySegment>("할 일");
  const [state, setState] = useState<ScreenState>(launchState);
  const now = useMemo(() => new Date(), []);
  const title = greeting(now.getHours());
  const subtitle = `11월 4일 수요일 · ${koreanTime(now)} 기준`;

  if (state === "error") return <Screen title={title} subtitle={subtitle} large><LoadError retry={() => setState("loaded")} /></Screen>;
  if (state === "empty") {
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
      <div className={state === "loading" ? "redacted" : undefined}>
        <Section><MetricStrip metrics={todayMetrics[segment]} /></Section>
        <div className="segmented-wrap"><Segmented label="보기" options={todaySegments} value={segment} onChange={setSegment} /></div>
        {segment === "할 일" &&
          todayTaskGroups.map((group) => (
            <Section key={group.title} header={<SectionHeader title={group.title} area={group.area} />}>
              {group.items.map((item) => <TaskRow key={item.id} item={item} kind={group.kind} />)}
            </Section>
          ))}
        {segment === "채널" && (
          <>
            <Section header={<SectionHeader title="채널 현황" area="channels" />}><Cards items={channelCards} /></Section>
            <Section header={<SectionHeader title={`오늘 챙길 일 ${channelTodos.length}건`} />}><Cards items={channelTodos} /></Section>
          </>
        )}
        {segment === "배송" && (
          <>
            <Section header={<SectionHeader title={`오늘 발송할 물건 ${shipToday.length}건`} area="deliveries" />}><Cards items={shipToday} /></Section>
            <Section header={<SectionHeader title="이동 중인 배송" />}>
              <Row chevron onClick={() => push({ kind: "area", area: "deliveries", filter: "배송 중" })}>
                <div className="summary-title sk">배송 중 2건 · 오늘 도착 1건</div>
                <div className="card-line sk">배송 지연 없이 잘 이동하고 있어요.</div>
              </Row>
              <Cards items={inTransit} />
            </Section>
          </>
        )}
        {segment === "비서 추천" && (
          <Section header={<SectionHeader title="오늘의 추천" />} footer="비서가 공방 현황을 보고 골랐어요. 틀릴 수 있으니 내용을 확인해 주세요.">
            <Cards items={suggestions} />
          </Section>
        )}
      </div>
    </Screen>
  );
}

const weekdays = ["월", "화", "수", "목", "금", "토", "일"];

export function CalendarScreen() {
  const { push } = useNav();
  const [mode, setMode] = useState<"주간" | "월간">("주간");
  const [day, setDay] = useState(todayDay);
  const [state, setState] = useState<ScreenState>(launchState);
  const addEvent = () => push({ kind: "placeholder", title: "일정 추가", symbol: "calendarPlus" });
  const trailing = (
    <>
      <button className="glass-pill" onClick={() => setDay(todayDay)}>오늘</button>
      <button className="glass-circle" aria-label="일정 추가" onClick={addEvent}><Icon name="plus" size={20} weight={2.2} /></button>
    </>
  );
  const subtitle = state === "loaded" || state === "loading" ? `오늘 일정 ${eventCount(todayDay)}개` : undefined;

  if (state === "error") return <Screen title="캘린더" subtitle={subtitle} large trailing={trailing}><LoadError retry={() => setState("loaded")} /></Screen>;
  if (state === "empty") {
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
  const dayLabel = `11월 ${day}일 ${["일", "월", "화", "수", "목", "금", "토"][new Date(2026, 10, day).getDay()]}요일`;
  return (
    <Screen title="캘린더" subtitle={subtitle} large trailing={trailing}>
      <div className={state === "loading" ? "redacted" : undefined}>
        <div className="segmented-wrap"><Segmented label="보기" options={["주간", "월간"]} value={mode} onChange={setMode} /></div>
        <Section header={mode === "주간" ? "11월 2일 – 8일" : undefined} footer={<Legend />}>
          {mode === "주간" ? <WeekStrip day={day} onSelect={setDay} /> : <MonthGrid day={day} onSelect={setDay} />}
        </Section>
        <Section header={count > 0 ? `${dayLabel} · 일정 ${count}개` : dayLabel}>
          {items ? (
            items.map((a) => <AgendaRow key={a.id} time={a.time} title={a.title} detail={a.detail} kind={a.kind} />)
          ) : events ? (
            events.map((e) => {
              const info = kindInfo[e.kind];
              const body = (
                <span className="summary-row">
                  <Icon name={info.symbol} size={20} color={info.color} />
                  <span className="summary-title">{info.label} {e.count}건</span>
                </span>
              );
              return info.area ? (
                <Row key={e.kind} chevron onClick={() => push({ kind: "area", area: info.area! })}>{body}</Row>
              ) : (
                <Row key={e.kind}>{body}</Row>
              );
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

function KindSymbols({ day }: { day: number }) {
  return (
    <span className="kind-symbols">
      {(novemberEvents[day] ?? []).map((e) => <Icon key={e.kind} name={kindInfo[e.kind].symbol} size={9} color={kindInfo[e.kind].color} weight={2.6} />)}
    </span>
  );
}

function WeekStrip({ day, onSelect }: { day: number; onSelect: (d: number) => void }) {
  return (
    <div className="week">
      {[2, 3, 4, 5, 6, 7, 8].map((d, i) => (
        <button key={d} className="week-day" onClick={() => onSelect(d)} aria-pressed={d === day}
          aria-label={`11월 ${d}일 ${weekdays[i]}요일, ${(novemberEvents[d] ?? []).map((e) => `${kindInfo[e.kind].label} ${e.count}건`).join(", ") || "일정 없음"}`}>
          <span className="week-name">{weekdays[i]}</span>
          <span className={d === day ? "day-num day-on" : "day-num"}>{d}</span>
          <KindSymbols day={d} />
        </button>
      ))}
    </div>
  );
}

function MonthGrid({ day, onSelect }: { day: number; onSelect: (d: number) => void }) {
  const first = new Date(2026, 10, 1).getDay();
  const cells = [...Array(first).fill(0), ...Array.from({ length: 30 }, (_, i) => i + 1)];
  return (
    <div className="month">
      <div className="month-head">
        <span className="month-label">2026년 11월 <Icon name="chevronRight" size={14} weight={2.6} color="var(--accent)" /></span>
        <span className="month-arrows"><Icon name="chevronLeft" size={20} weight={2.2} /><Icon name="chevronRight" size={20} weight={2.2} /></span>
      </div>
      <div className="month-grid">
        {["일", "월", "화", "수", "목", "금", "토"].map((w) => <span key={w} className="month-weekday">{w}</span>)}
        {cells.map((d, i) =>
          d === 0 ? <span key={`b${i}`} /> : (
            <button key={d} className="month-cell" onClick={() => onSelect(d)} aria-pressed={d === day}>
              <span className={d === day ? "day-num day-on" : "day-num"}>{d}</span>
              <KindSymbols day={d} />
            </button>
          ),
        )}
      </div>
    </div>
  );
}

function Legend() {
  return (
    <span className="legend">
      {kinds.map((k) => (
        <span key={k} className="legend-item"><Icon name={kindInfo[k].symbol} size={15} color={kindInfo[k].color} />{kindInfo[k].label}</span>
      ))}
    </span>
  );
}

export function OperationsScreen() {
  const { push } = useNav();
  const [period, setPeriod] = useState<"11월" | "10월">("11월");
  const attention: { title: string; count: number; symbol: string; area: AreaId; filter: string }[] = [
    { title: "예약금 미확인", count: 2, symbol: "won", area: "bookings", filter: "예약금 대기" },
    { title: "미답변 문의", count: 3, symbol: "bubble", area: "channels", filter: "문의" },
    { title: "발송 마감", count: 2, symbol: "box", area: "deliveries", filter: "발송 예정" },
  ];
  return (
    <Screen title="운영" subtitle={`먼저 확인할 일 ${attention.length > 0 ? attentionCount : 0}건`} large>
      <Section header={<div className="section-header-row"><span>먼저 확인해주세요</span><StatusBadge status={{ text: `${attentionCount}건`, tone: "attention" }} /></div>}>
        {attention.map((a) => (
          <Row key={a.title} chevron onClick={() => push({ kind: "area", area: a.area, filter: a.filter })}>
            <span className="labeled"><Icon name={a.symbol} size={21} color="var(--accent)" /><span>{a.title}</span><b>{a.count}건</b></span>
          </Row>
        ))}
      </Section>
      <Section header={
        <div className="section-header-row">
          <span>{period} 운영 현황</span>
          <MenuButton className="period-chip" ariaLabel={`기간 선택, ${period}`} options={["11월", "10월"] as ("11월" | "10월")[]} value={period} onChange={setPeriod}
            label={<>{period === "11월" ? "11.01 – 11.30" : "10.01 – 10.31"} <Icon name="chevronDown" size={14} weight={2.4} /></>} />
        </div>
      }>
        <div className="row summary-box">
          <div className="gauge-wrap" aria-label={`${period} 처리율 75퍼센트`}>
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
      <Section header="전체 업무 관리">
        {areaOrder.map((id) => {
          const a = areas[id];
          return (
            <Row key={id} chevron onClick={() => push({ kind: "area", area: id })}>
              <span className="labeled">
                <Icon name={a.symbol} size={21} color="var(--accent)" />
                <span className="labeled-text"><span>{a.title}</span><small>{a.summary}</small></span>
                <span className="secondary-value">{a.count}</span>
              </span>
            </Row>
          );
        })}
      </Section>
      <Section header="공방 성장">
        <Row chevron onClick={() => push({ kind: "placeholder", title: "기회", symbol: "sparkles" })}>
          <span className="labeled"><Icon name="sparkles" size={21} color="var(--accent)" /><span className="labeled-text"><span>기회</span><small>마켓·공모·지원사업 모집 공고</small></span></span>
        </Row>
        <Row chevron onClick={() => push({ kind: "placeholder", title: "리포트", symbol: "chart" })}>
          <span className="labeled"><Icon name="chart" size={21} color="var(--accent)" /><span className="labeled-text"><span>리포트</span><small>주간·월간 숫자</small></span></span>
        </Row>
      </Section>
    </Screen>
  );
}

export function AreaScreen({ areaId, initialFilter }: { areaId: AreaId; initialFilter?: string }) {
  const area = areas[areaId];
  const { push } = useNav();
  const [filter, setFilter] = useState(initialFilter ?? area.filters[0]!);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState(area.sortOptions[0] ?? "");
  const [state, setState] = useState<ScreenState>(launchState);
  const visible = useMemo(() => {
    const q = query.trim();
    const list = area.items.filter((item) =>
      (filter === area.filters[0] || item.tag === filter) &&
      (!q || item.title.includes(q) || item.lines.some((l) => l.includes(q))));
    return area.sortOptions.length > 1 && sort === area.sortOptions[1] ? [...list].reverse() : list;
  }, [area, filter, query, sort]);
  const first = primaryId(visible);

  const trailing =
    areaId === "bookings" ? (
      <button className="glass-circle" aria-label="예약 등록" onClick={() => push({ kind: "placeholder", title: "예약 등록", symbol: "calendarPlus" })}><Icon name="plus" size={20} weight={2.2} /></button>
    ) : areaId === "channels" ? (
      <button className="glass-pill" onClick={() => push({ kind: "placeholder", title: "연결 관리", symbol: "link" })}>연결 관리</button>
    ) : (
      <MenuButton ariaLabel="정렬" options={area.sortOptions} value={sort} onChange={setSort} label={<Icon name="sort" size={20} weight={2} />} />
    );
  const search = (
    <div className="searchbar">
      <Icon name="search" size={17} color="var(--secondary)" weight={2.2} />
      <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={area.searchPrompt} aria-label={area.searchPrompt} />
      {query ? <button className="search-clear" aria-label="지우기" onClick={() => setQuery("")}><Icon name="xmark" size={12} weight={3} /></button> : null}
    </div>
  );

  return (
    <Screen title={area.title} back trailing={trailing} accessory={state === "loaded" || state === "loading" ? search : undefined}>
      {state === "error" ? (
        <LoadError retry={() => setState("loaded")} />
      ) : state === "empty" ? (
        <EmptyState symbol={area.symbol} title={area.noDataTitle} message={area.noDataMessage}
          action={area.noDataAction ? <button className="btn btn-prominent btn-pill" onClick={() => push({ kind: "placeholder", title: area.noDataAction!, symbol: area.symbol })}>{area.noDataAction}</button> : undefined} />
      ) : (
        <div className={state === "loading" ? "redacted" : undefined}>
          <Section><MetricStrip metrics={area.metrics} /></Section>
          <div className="segmented-wrap"><Segmented label="상태" options={area.filters} value={filter} onChange={setFilter} /></div>
          <Section header={area.listTitle}>
            {visible.length === 0 ? (
              query ? (
                <EmptyState symbol="search" title={`'${query}'에 대한 결과 없음`} message="검색어를 확인하거나 다른 검색어를 입력해 보세요." />
              ) : (
                <EmptyState symbol="tray" title={area.emptyTitle} message="지금 고른 상태에는 항목이 없어요."
                  action={filter !== area.filters[0] ? <button className="btn btn-bordered btn-pill" onClick={() => setFilter(area.filters[0]!)}>전체 보기</button> : undefined} />
              )
            ) : (
              visible.map((item) => <WorkCardRow key={item.id} item={item} primary={item.id === first} />)
            )}
          </Section>
        </div>
      )}
    </Screen>
  );
}

export function DetailScreen({ item }: { item: WorkItem }) {
  return (
    <Screen title={item.title} back>
      <Section><div className="row"><WorkCard item={item} showAction={false} /></div></Section>
      <Section><Row><span className="labeled muted"><Icon name="hammer" size={20} color="var(--secondary)" /><span>세부 화면은 준비 중이에요.</span></span></Row></Section>
    </Screen>
  );
}

export function PlaceholderScreen({ title, symbol }: { title: string; symbol: string }) {
  return <Screen title={title} back><PlaceholderBody title={title} symbol={symbol} /></Screen>;
}

export function SettingsScreen() {
  const { push } = useNav();
  return (
    <Screen title="설정" large>
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
