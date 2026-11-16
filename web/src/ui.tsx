import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Icon } from "./icons";
import { kindInfo, toneInfo, type AreaId, type EventKind, type Metric, type Status, type TaskItem, type WorkItem } from "./data";

export type Route =
  | { kind: "root" }
  | { kind: "area"; area: AreaId; filter?: string }
  | { kind: "detail"; item: WorkItem }
  | { kind: "placeholder"; title: string; symbol: string };

export const NavContext = createContext<{ push: (route: Route) => void; pop: () => void }>({ push: () => {}, pop: () => {} });
export const useNav = () => useContext(NavContext);

export function Screen(props: {
  title: string;
  subtitle?: string;
  large?: boolean;
  back?: boolean;
  trailing?: ReactNode;
  accessory?: ReactNode;
  children: ReactNode;
}) {
  const { pop } = useNav();
  const [scrolled, setScrolled] = useState(false);
  const showBarTitle = !props.large || scrolled;
  return (
    <div className="screen">
      <header className={`navbar${scrolled || props.accessory ? " navbar-solid" : ""}`}>
        <div className="navbar-row">
          <div className="navbar-side">
            {props.back ? (
              <button className="glass-circle" onClick={pop} aria-label="뒤로">
                <Icon name="chevronLeft" size={20} weight={2.2} />
              </button>
            ) : null}
          </div>
          <div className="navbar-title" style={{ opacity: showBarTitle ? 1 : 0 }}>
            <div className="navbar-title-main">{props.title}</div>
            {props.subtitle && scrolled ? <div className="navbar-title-sub">{props.subtitle}</div> : null}
          </div>
          <div className="navbar-side navbar-trailing">{props.trailing}</div>
        </div>
        {props.accessory}
      </header>
      <div className={`scroll${props.accessory ? " scroll-with-accessory" : ""}`} onScroll={(e) => setScrolled(e.currentTarget.scrollTop > 36)}>
        {props.large ? (
          <div className="large-title">
            <h1>{props.title}</h1>
            {props.subtitle ? <p>{props.subtitle}</p> : null}
          </div>
        ) : null}
        {props.children}
        <div className="scroll-tail" />
      </div>
    </div>
  );
}

export function Section(props: { header?: ReactNode; footer?: ReactNode; plain?: boolean; children: ReactNode }) {
  return (
    <section className="section">
      {props.header ? <div className="section-header">{props.header}</div> : null}
      <div className={props.plain ? "section-plain" : "section-body"}>{props.children}</div>
      {props.footer ? <div className="section-footer">{props.footer}</div> : null}
    </section>
  );
}

export function Row(props: { children: ReactNode; onClick?: () => void; chevron?: boolean; label?: string }) {
  const content = (
    <>
      <div className="row-content">{props.children}</div>
      {props.chevron ? <Icon name="chevronRight" size={16} weight={2.4} color="var(--tertiary)" /> : null}
    </>
  );
  return props.onClick ? (
    <button className="row row-button" onClick={props.onClick} aria-label={props.label}>{content}</button>
  ) : (
    <div className="row">{content}</div>
  );
}

export function MetricStrip({ metrics }: { metrics: Metric[] }) {
  return (
    <div className="metrics">
      {metrics.map((m, i) => (
        <div className="metric" key={m.label}>
          {i > 0 ? <span className="metric-divider" /> : null}
          <div className="metric-value sk">{m.value}</div>
          <div className="metric-label sk">{m.label}</div>
        </div>
      ))}
    </div>
  );
}

export function StatusBadge({ status }: { status: Status }) {
  const tone = toneInfo[status.tone];
  return (
    <span className="badge" aria-label={`상태 ${status.text}`}>
      <Icon name={tone.symbol} size={14} color={tone.color} weight={2.2} />
      <span className="sk">{status.text}</span>
    </span>
  );
}

export function KindTag({ kind }: { kind: EventKind }) {
  const info = kindInfo[kind];
  return (
    <span className="kind-tag" style={{ background: `color-mix(in srgb, ${info.color} 14%, transparent)` }}>
      <Icon name={info.symbol} size={14} color={info.color} weight={2} />
      {info.label}
    </span>
  );
}

export function Segmented<T extends string>(props: { options: T[]; value: T; onChange: (v: T) => void; label: string }) {
  return (
    <div className="segmented" role="tablist" aria-label={props.label}>
      {props.options.map((o) => (
        <button key={o} role="tab" aria-selected={o === props.value} className={o === props.value ? "seg seg-on" : "seg"} onClick={() => props.onChange(o)}>
          {o}
        </button>
      ))}
    </div>
  );
}

export function PhraseText({ text, className }: { text: string; className?: string }) {
  const phrases = text.split(" · ");
  return (
    <span className={`phrase ${className ?? ""}`}>
      {phrases.map((p, i) => (
        <span className="phrase-piece" key={i}>{i < phrases.length - 1 ? `${p} ·` : p}</span>
      ))}
    </span>
  );
}

export function TaskRow({ item, kind }: { item: TaskItem; kind: EventKind }) {
  const [done, setDone] = useState(item.isDone ?? false);
  const info = kindInfo[kind];
  return (
    <div className="row task-row">
      {item.time ? (
        <span className="task-time sk">{item.time}</span>
      ) : (
        <span className="icon-tile" style={{ background: `color-mix(in srgb, ${info.color} 12%, transparent)` }}>
          <Icon name={info.symbol} size={20} color={info.color} />
        </span>
      )}
      <div className="task-text">
        <div className="task-title sk">{item.title}</div>
        <PhraseText text={item.detail} className="task-detail sk" />
      </div>
      {item.isDone !== undefined ? (
        <button className="check" onClick={() => setDone(!done)} aria-label={`${item.title} 완료 표시`} aria-pressed={done}>
          <Icon name={done ? "checkFill" : "circle"} size={26} color={done ? "var(--green)" : "var(--secondary)"} weight={1.6} />
        </button>
      ) : item.status ? (
        <StatusBadge status={item.status} />
      ) : null}
    </div>
  );
}

export function WorkCard({ item, primary = false, showAction = true }: { item: WorkItem; primary?: boolean; showAction?: boolean }) {
  const [completed, setCompleted] = useState(false);
  const status = completed ? { text: "처리 완료", tone: "done" as const } : item.status;
  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title sk">{item.title}</div>
        {status ? <StatusBadge status={status} /> : null}
      </div>
      {item.lines.map((line) => (
        <PhraseText key={line} text={line} className="card-line sk" />
      ))}
      {item.deadline ? (
        <div className="card-deadline sk">
          <Icon name="clockFill" size={16} color="var(--orange)" />
          {item.deadline}
        </div>
      ) : null}
      {showAction && item.action?.kind === "perform" ? (
        <button
          className={primary && !completed ? "btn btn-prominent" : "btn btn-bordered"}
          disabled={completed}
          onClick={(e) => { e.stopPropagation(); setCompleted(true); }}
        >
          {completed ? <><Icon name="checkmark" size={16} weight={2.4} /> 처리했어요</> : item.action.label}
        </button>
      ) : null}
    </div>
  );
}

export function WorkCardRow({ item, primary = false }: { item: WorkItem; primary?: boolean }) {
  const { push } = useNav();
  if (item.action?.kind === "open") {
    return (
      <button className="row row-button card-row" onClick={() => push({ kind: "detail", item })}>
        <div className="row-content"><WorkCard item={item} /></div>
        <Icon name="chevronRight" size={16} weight={2.4} color="var(--tertiary)" />
      </button>
    );
  }
  return <div className="row card-row"><WorkCard item={item} primary={primary} /></div>;
}

export function primaryId(items: WorkItem[]) {
  return items.find((i) => i.action?.kind === "perform")?.id;
}

export function AgendaRow({ time, title, detail, kind }: { time: string; title: string; detail: string; kind: EventKind }) {
  return (
    <div className="row agenda-row">
      <span className="task-time sk">{time}</span>
      <div className="task-text">
        <div className="agenda-title sk">{title}</div>
        <PhraseText text={detail} className="task-detail sk" />
      </div>
      <KindTag kind={kind} />
    </div>
  );
}

export function SectionHeader({ title, area }: { title: string; area?: AreaId }) {
  const { push } = useNav();
  return (
    <div className="section-header-row">
      <span>{title}</span>
      {area ? <button className="link" onClick={() => push({ kind: "area", area })}>전체 보기</button> : null}
    </div>
  );
}

export function EmptyState(props: { symbol: string; title: string; message?: string; action?: ReactNode }) {
  return (
    <div className="empty">
      <Icon name={props.symbol} size={44} color="var(--secondary)" weight={1.5} />
      <div className="empty-title">{props.title}</div>
      {props.message ? <div className="empty-message">{props.message}</div> : null}
      {props.action ? <div className="empty-action">{props.action}</div> : null}
    </div>
  );
}

export function LoadError({ retry }: { retry: () => void }) {
  return (
    <EmptyState
      symbol="wifiExcl"
      title="불러오지 못했어요"
      message={"인터넷 연결을 확인하고\n다시 시도해 주세요."}
      action={<button className="btn btn-prominent btn-pill" onClick={retry}>다시 시도</button>}
    />
  );
}

export function PlaceholderBody({ title, symbol }: { title: string; symbol: string }) {
  return <EmptyState symbol={symbol} title={title} message={"아직 준비 중인 화면이에요.\n곧 열어 드릴게요."} />;
}

export function MenuButton<T extends string>(props: { label: ReactNode; ariaLabel: string; options: T[]; value: T; onChange: (v: T) => void; className?: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: PointerEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);
  return (
    <div className="menu-wrap" ref={ref}>
      <button className={props.className ?? "glass-circle"} aria-label={props.ariaLabel} aria-expanded={open} onClick={() => setOpen(!open)}>
        {props.label}
      </button>
      {open ? (
        <div className="menu" role="menu">
          {props.options.map((o) => (
            <button key={o} role="menuitemradio" aria-checked={o === props.value} className="menu-item" onClick={() => { props.onChange(o); setOpen(false); }}>
              <span className="menu-check">{o === props.value ? <Icon name="checkmark" size={16} weight={2.4} /> : null}</span>
              {o}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
