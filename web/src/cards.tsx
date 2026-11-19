import { Icon } from "./icons";
import { assertNever, kindInfo, workItems, type AgendaEntry, type AgendaTarget, type AreaEntry, type Booking, type EventKind, type WorkId, type WorkItem } from "./data";
import { DraftCompact } from "./drafts";
import { isDone, useStore, workStatus, type State } from "./store";
import { PhraseText, StatusBadge, useNav, type Route } from "./ui";

export function BookingTaskRow({ booking }: { booking: Booking }) {
  const { dispatch } = useStore();
  const { push } = useNav();
  return (
    <div className={booking.attended ? "task struck" : "task"}>
      <button className="row row-button task-row" onClick={() => push({ kind: "booking", id: booking.id })}>
        <span className="task-time sk">{booking.start}</span>
        <span className="task-text">
          <span className="task-title sk">{booking.title}</span>
          <PhraseText text={`${booking.booker} · ${booking.people}명 · ${booking.minutes}분`} className="task-detail sk" />
        </span>
      </button>
      <button
        className="check"
        onClick={() => dispatch({ type: "booking/attended", id: booking.id, value: !booking.attended })}
        aria-label={`${booking.title} 수업 완료 표시`}
        aria-pressed={booking.attended}
      >
        <Icon name={booking.attended ? "checkFill" : "circle"} size={26} color={booking.attended ? "var(--green)" : "var(--secondary)"} weight={1.6} />
      </button>
    </div>
  );
}

export function WorkTaskRow({ item, kind }: { item: WorkItem; kind: EventKind }) {
  const { state } = useStore();
  const { push } = useNav();
  const info = kindInfo[kind];
  return (
    <button className="row row-button task-row" onClick={() => push({ kind: "work", id: item.id })}>
      <span className="icon-tile" style={{ background: `color-mix(in srgb, ${info.color} 12%, transparent)` }}>
        <Icon name={info.symbol} size={20} color={info.color} />
      </span>
      <span className="task-text">
        <span className="task-title sk">{item.title}</span>
        <PhraseText text={item.lines[0] ?? ""} className="task-detail sk" />
      </span>
      <StatusBadge status={workStatus(state, item)} />
    </button>
  );
}

export function WorkCard({ item, primary = false }: { item: WorkItem; primary?: boolean }) {
  const { state, dispatch } = useStore();
  const { push } = useNav();
  const done = isDone(state, item.id);
  return (
    <div className="card-wrap">
      <button className="row row-button" onClick={() => push({ kind: "work", id: item.id })}>
        <span className="row-content card">
          <span className="card-head"><span className="card-title sk">{item.title}</span><StatusBadge status={workStatus(state, item)} /></span>
          {item.lines.map((line) => <PhraseText key={line} text={line} className="card-line sk" />)}
          {item.deadline && !done ? (
            <span className="card-deadline sk"><Icon name="clockFill" size={16} color="var(--orange)" />{item.deadline}</span>
          ) : null}
        </span>
        <Icon name="chevronRight" size={16} weight={2.4} color="var(--tertiary)" />
      </button>
      {item.perform ? (
        <div className="card-act">
          <button
            className={primary && !done ? "btn btn-prominent" : "btn btn-bordered"}
            disabled={done}
            onClick={() => dispatch({ type: "work/done", id: item.id, value: true })}
          >
            {done ? <><Icon name="checkmark" size={16} weight={2.4} /> 처리했어요</> : item.perform.label}
          </button>
        </div>
      ) : null}
    </div>
  );
}

export const firstPendingWork = (ids: readonly WorkId[], state: State): WorkId | undefined =>
  ids.find((id) => workItems[id].perform !== undefined && !isDone(state, id));

export function WorkCards({ ids }: { ids: readonly WorkId[] }) {
  const { state } = useStore();
  const first = firstPendingWork(ids, state);
  return <>{ids.map((id) => <WorkCard key={id} item={workItems[id]} primary={id === first} />)}</>;
}

export function EntryCard({ entry, primary }: { entry: AreaEntry; primary: boolean }) {
  switch (entry.kind) {
    case "work": return <WorkCard item={workItems[entry.id]} primary={primary} />;
    case "draft": return <DraftCompact id={entry.id} />;
    default: return assertNever(entry);
  }
}

function routeFor(target: AgendaTarget): Route {
  switch (target.kind) {
    case "area": return { kind: "area", area: target.area };
    case "draft": return { kind: "draft", id: target.id };
    default: return assertNever(target);
  }
}

export function AgendaRow({ entry }: { entry: AgendaEntry }) {
  const { state } = useStore();
  const { push } = useNav();
  switch (entry.kind) {
    case "booking": {
      const b = state.bookings[entry.id];
      return (
        <button className={b.attended ? "row row-button agenda-row struck" : "row row-button agenda-row"} onClick={() => push({ kind: "booking", id: b.id })}>
          <span className="task-time sk">{entry.time}</span>
          <span className="task-text">
            <span className="agenda-title sk">{b.title}</span>
            <PhraseText text={`${b.booker} · ${b.people}명`} className="task-detail sk" />
          </span>
          <span className="agenda-kind sk">{kindInfo.booking.label}</span>
        </button>
      );
    }
    case "order":
    case "delivery":
    case "todo":
      return (
        <button className="row row-button agenda-row" onClick={() => push(routeFor(entry.target))}>
          <span className="task-time sk">{entry.time}</span>
          <span className="task-text">
            <span className="agenda-title sk">{entry.title}</span>
            <PhraseText text={entry.detail} className="task-detail sk" />
          </span>
          <span className="agenda-kind sk">{kindInfo[entry.kind].label}</span>
        </button>
      );
    default:
      return assertNever(entry);
  }
}
