import { useMemo, useState } from "react";
import { Icon } from "./icons";
import { areaMetrics, areas, assertNever, bookingIds, launchState, weekdayName, workItems, type AreaEntry, type AreaId, type Booking, type ScreenState } from "./data";
import { EntryCard, firstPendingWork } from "./cards";
import { bookingStatus, bookingTag, liveCounts, useStore, type State } from "./store";
import { EmptyState, LoadError, MenuButton, MetricStrip, Screen, Section, Segmented, StatusBadge, useNav } from "./ui";

type Query = { readonly all: string; readonly filter: string; readonly text: string };

function entryText(e: AreaEntry, state: State): { readonly title: string; readonly lines: readonly string[]; readonly tag?: string } {
  switch (e.kind) {
    case "work": return workItems[e.id];
    case "draft": return state.drafts[e.id];
    default: return assertNever(e);
  }
}

const matches = (q: Query, title: string, lines: readonly string[], tag: string | undefined) =>
  (q.filter === q.all || tag === q.filter) && (!q.text || title.includes(q.text) || lines.some((l) => l.includes(q.text)));

function BookingRow({ booking }: { booking: Booking }) {
  const { push } = useNav();
  return (
    <button className="row row-button booking-row" onClick={() => push({ kind: "booking", id: booking.id })}>
      <span className="booking-time sk">{booking.start}</span>
      <span className="booking-main">
        <span className="booking-class sk">{booking.title}</span>
        <span className="booking-who sk">{booking.booker}</span>
      </span>
      <StatusBadge status={bookingStatus(booking)} />
      <Icon name="chevronRight" size={16} weight={2.4} color="var(--tertiary)" />
    </button>
  );
}

function NoResults({ areaId, q, resetFilter }: { areaId: AreaId; q: Query; resetFilter: () => void }) {
  const area = areas[areaId];
  return (
    <Section header={area.listTitle}>
      {q.text ? (
        <EmptyState symbol="search" title={`'${q.text}'에 대한 결과 없음`} message="검색어를 확인하거나 다른 검색어를 입력해 보세요." />
      ) : (
        <EmptyState symbol="tray" title={area.emptyTitle} message="지금 고른 상태에는 항목이 없어요."
          action={q.filter !== q.all ? <button className="btn btn-bordered btn-pill" onClick={resetFilter}>전체 보기</button> : undefined} />
      )}
    </Section>
  );
}

function BookingList({ q, resetFilter }: { q: Query; resetFilter: () => void }) {
  const { state } = useStore();
  const list = bookingIds.map((id) => state.bookings[id]).filter((b) => matches(q, b.title, [b.booker], bookingTag(b)));
  if (list.length === 0) return <NoResults areaId="bookings" q={q} resetFilter={resetFilter} />;
  const days = [...new Set(list.map((b) => b.day))].sort((a, b) => a - b);
  return (
    <>
      {days.map((day) => {
        const rows = list.filter((b) => b.day === day).sort((a, b) => a.start.localeCompare(b.start));
        return (
          <Section key={day} spaced header={`11월 ${day}일 ${weekdayName(day)}요일 · ${rows.length}건`}>
            {rows.map((b) => <BookingRow key={b.id} booking={b} />)}
          </Section>
        );
      })}
    </>
  );
}

function EntryList({ areaId, q, resetFilter }: { areaId: Exclude<AreaId, "bookings">; q: Query; resetFilter: () => void }) {
  const area = areas[areaId];
  const { state } = useStore();
  const [sort, setSort] = useState(area.sortOptions[0] ?? "");
  const entries = useMemo(() => {
    const list = area.entries.filter((e) => { const t = entryText(e, state); return matches(q, t.title, t.lines, t.tag); });
    return area.sortOptions.length > 1 && sort === area.sortOptions[1] ? [...list].reverse() : list;
  }, [area, q, sort, state]);
  if (entries.length === 0) return <NoResults areaId={areaId} q={q} resetFilter={resetFilter} />;
  const first = firstPendingWork(entries.flatMap((e) => (e.kind === "work" ? [e.id] : [])), state);
  const sortControl = area.sortOptions.length > 1 ? (
    <MenuButton className="sort-control" ariaLabel={`정렬 바꾸기, 지금 ${sort}`} options={area.sortOptions} value={sort} onChange={setSort}
      label={<>{sort}<Icon name="chevronDown" size={14} weight={2.4} /></>} />
  ) : null;
  return (
    <Section spaced bodyClass="cards" header={<div className="section-header-row"><span>{area.listTitle}</span>{sortControl}</div>}>
      {entries.map((e) => <EntryCard key={e.id} entry={e} primary={e.kind === "work" && e.id === first} />)}
    </Section>
  );
}

function AreaTrailing({ areaId }: { areaId: AreaId }) {
  const { push } = useNav();
  switch (areaId) {
    case "bookings":
      return <button className="glass-circle" aria-label="예약 등록" onClick={() => push({ kind: "placeholder", title: "예약 등록", symbol: "calendarPlus" })}><Icon name="plus" size={20} weight={2.2} /></button>;
    case "channels":
      return <button className="glass-pill" onClick={() => push({ kind: "placeholder", title: "연결 관리", symbol: "link" })}>연결 관리</button>;
    case "orders":
    case "deliveries":
      return null;
    default:
      return assertNever(areaId);
  }
}

function AreaList({ areaId, q, resetFilter }: { areaId: AreaId; q: Query; resetFilter: () => void }) {
  switch (areaId) {
    case "bookings": return <BookingList q={q} resetFilter={resetFilter} />;
    case "orders":
    case "deliveries":
    case "channels": return <EntryList areaId={areaId} q={q} resetFilter={resetFilter} />;
    default: return assertNever(areaId);
  }
}

export function AreaScreen({ areaId, initialFilter }: { areaId: AreaId; initialFilter?: string }) {
  const area = areas[areaId];
  const { push } = useNav();
  const { state } = useStore();
  const all = area.filters[0] ?? "전체";
  const [filter, setFilter] = useState(initialFilter ?? all);
  const [text, setText] = useState("");
  const [screenState, setScreenState] = useState<ScreenState>(launchState);
  const q: Query = { all, filter, text: text.trim() };

  const search = (
    <div className="searchbar">
      <Icon name="search" size={17} color="var(--secondary)" weight={2.2} />
      <input value={text} onChange={(e) => setText(e.target.value)} placeholder={area.searchPrompt} aria-label={area.searchPrompt} />
      {text ? <button className="search-clear" aria-label="지우기" onClick={() => setText("")}><Icon name="xmark" size={12} weight={3} /></button> : null}
    </div>
  );

  return (
    <Screen title={area.title} back trailing={<AreaTrailing areaId={areaId} />} accessory={screenState === "loaded" || screenState === "loading" ? search : undefined}>
      {screenState === "error" ? (
        <LoadError retry={() => setScreenState("loaded")} />
      ) : screenState === "empty" ? (
        <EmptyState symbol={area.symbol} title={area.noDataTitle} message={area.noDataMessage}
          action={area.noDataAction ? <button className="btn btn-prominent btn-pill" onClick={() => push({ kind: "placeholder", title: area.noDataAction ?? "", symbol: area.symbol })}>{area.noDataAction}</button> : undefined} />
      ) : (
        <div className={screenState === "loading" ? "redacted" : undefined}>
          <Section><MetricStrip metrics={areaMetrics(areaId, liveCounts(state))} /></Section>
          <div className="segmented-wrap"><Segmented label="상태" options={area.filters} value={filter} onChange={setFilter} /></div>
          <AreaList areaId={areaId} q={q} resetFilter={() => setFilter(all)} />
        </div>
      )}
    </Screen>
  );
}
