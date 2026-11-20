import { useEffect, useRef, useState } from "react";
import { Icon } from "./icons";

export type DayRange = { readonly start: Date; readonly end: Date };

const YEAR = 2026;
const dayOf = (month: number, day: number) => new Date(YEAR, month, day);
const lastDayOf = (month: number) => new Date(YEAR, month + 1, 0).getDate();
const two = (n: number) => String(n).padStart(2, "0");
const sameDay = (a: Date | undefined, b: Date) => a !== undefined && a.getTime() === b.getTime();

export const novemberRange: DayRange = { start: dayOf(10, 1), end: dayOf(10, 30) };

export const rangeLabel = (r: DayRange) =>
  `${two(r.start.getMonth() + 1)}.${two(r.start.getDate())} – ${two(r.end.getMonth() + 1)}.${two(r.end.getDate())}`;

export function rangeHeading(r: DayRange): string {
  const wholeMonth = r.start.getDate() === 1 && r.start.getMonth() === r.end.getMonth() && r.end.getDate() === lastDayOf(r.start.getMonth());
  return wholeMonth ? `${r.start.getMonth() + 1}월 운영 현황` : "선택 기간 운영 현황";
}

type Selection = { readonly start?: Date; readonly end?: Date };

function select(current: Selection, day: Date): Selection {
  if (current.start === undefined || current.end !== undefined) return { start: day };
  if (day < current.start) return { start: day };
  return { start: current.start, end: day };
}

function selectionHint(sel: Selection): string {
  if (sel.start !== undefined && sel.end !== undefined) return rangeLabel({ start: sel.start, end: sel.end });
  if (sel.start !== undefined) return `${sel.start.getMonth() + 1}월 ${sel.start.getDate()}일부터 · 끝 날짜를 골라 주세요`;
  return "시작 날짜를 골라 주세요";
}

function DayCell({ day, sel, onPick }: { day: Date; sel: Selection; onPick: (d: Date) => void }) {
  const edge = sameDay(sel.start, day) || sameDay(sel.end, day);
  const inRange = sel.start !== undefined && sel.end !== undefined && day > sel.start && day < sel.end;
  const cls = ["period-day", edge ? "range-edge" : "", inRange ? "in-range" : ""].join(" ").trim();
  return (
    <button className={cls} aria-pressed={edge} aria-label={`${day.getMonth() + 1}월 ${day.getDate()}일`} onClick={() => onPick(day)}>
      {day.getDate()}
    </button>
  );
}

export function PeriodPicker({ value, onApply, onCancel }: { value: DayRange; onApply: (r: DayRange) => void; onCancel: () => void }) {
  const [month, setMonth] = useState(value.start.getMonth());
  const [sel, setSel] = useState<Selection>({ start: value.start, end: value.end });
  const dialog = useRef<HTMLDivElement>(null);
  useEffect(() => { dialog.current?.focus(); }, []);
  const leading = dayOf(month, 1).getDay();
  const days = Array.from({ length: lastDayOf(month) }, (_, i) => dayOf(month, i + 1));
  const complete = sel.start !== undefined && sel.end !== undefined ? { start: sel.start, end: sel.end } : undefined;
  return (
    <div className="dialog-center" onClick={onCancel}>
      <div
        ref={dialog}
        className="period-dialog"
        role="dialog"
        aria-label="기간 선택"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => { if (e.key === "Escape") onCancel(); }}
      >
        <div className="period-head">
          <button className="period-nav" aria-label="이전 달" disabled={month === 0} onClick={() => setMonth(month - 1)}>
            <Icon name="chevronLeft" size={20} weight={2.2} />
          </button>
          <span className="period-month">{YEAR}년 {month + 1}월</span>
          <button className="period-nav" aria-label="다음 달" disabled={month === 11} onClick={() => setMonth(month + 1)}>
            <Icon name="chevronRight" size={20} weight={2.2} />
          </button>
        </div>
        <div className="period-grid">
          {["일", "월", "화", "수", "목", "금", "토"].map((w) => <span key={w} className="period-weekday">{w}</span>)}
          {Array.from({ length: leading }, (_, i) => <span key={`blank-${i}`} />)}
          {days.map((d) => <DayCell key={d.getDate()} day={d} sel={sel} onPick={(picked) => setSel(select(sel, picked))} />)}
        </div>
        <div className="period-hint">{selectionHint(sel)}</div>
        <div className="period-foot">
          <button className="btn btn-bordered" onClick={onCancel}>취소</button>
          <button className="btn btn-prominent" disabled={complete === undefined} onClick={() => { if (complete) onApply(complete); }}>적용</button>
        </div>
      </div>
    </div>
  );
}
