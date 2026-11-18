import { Icon } from "./icons";
import { weekdayName, workItems, type BookingId, type WorkId } from "./data";
import { bookingStatus, isDone, useStore, workStatus } from "./store";
import { Screen, Section, StatusBadge, UndoButton } from "./ui";

type Step = {
  readonly label: string;
  readonly done: boolean;
  readonly doneText: string;
  readonly deadline?: string;
  readonly actionLabel: string;
  readonly onChange: (done: boolean) => void;
};

export function StepRow({ step }: { step: Step }) {
  return (
    <div className="step">
      <div className="step-top">
        <span className="task-text">
          <span className="step-label">{step.label}</span>
          {step.done ? (
            <span className="done-line"><Icon name="checkFill" size={18} color="var(--green)" />{step.doneText}</span>
          ) : step.deadline ? (
            <span className="card-deadline"><Icon name="clockFill" size={15} color="var(--orange)" />{step.deadline}</span>
          ) : null}
        </span>
        {step.done ? <UndoButton onClick={() => step.onChange(false)} /> : null}
      </div>
      {step.done ? null : <button className="btn btn-prominent" onClick={() => step.onChange(true)}>{step.actionLabel}</button>}
    </div>
  );
}

export function BookingDetailScreen({ id }: { id: BookingId }) {
  const { state, dispatch } = useStore();
  const b = state.bookings[id];
  const rows: readonly (readonly [string, string])[] = [
    ["일시", `11월 ${b.day}일 ${weekdayName(b.day)} · ${b.start}–${b.end}`],
    ["예약자", b.booker],
    ["인원", `${b.people}명`],
    ["수업 시간", `${b.minutes}분`],
    ["예약 경로", b.channel],
    ...(b.note ? [["자리", b.note] as const] : []),
  ];
  return (
    <Screen title="예약 상세" back>
      <div className="detail">
        <div>
          <Section header="예약 정보">
            <div className="row"><span className="row-content card-title sk">{b.title}</span><StatusBadge status={bookingStatus(b)} /></div>
            {rows.map(([k, v]) => <div key={k} className="kv"><span>{k}</span><b className="sk">{v}</b></div>)}
          </Section>
        </div>
        <div>
          <Section header="처리">
            <StepRow step={{
              label: "예약금", done: b.deposit, doneText: "입금을 확인했어요", deadline: b.deadline, actionLabel: "입금 확인하기",
              onChange: (value) => dispatch({ type: "booking/deposit", id, value }),
            }} />
            <StepRow step={{
              label: "수업", done: b.attended, doneText: "수업을 완료했어요", actionLabel: "수업 완료로 표시",
              onChange: (value) => dispatch({ type: "booking/attended", id, value }),
            }} />
          </Section>
        </div>
      </div>
    </Screen>
  );
}

export function WorkDetailScreen({ id }: { id: WorkId }) {
  const { state, dispatch } = useStore();
  const item = workItems[id];
  return (
    <Screen title={item.title} back>
      <div className="detail">
        <div>
          <Section header="정보">
            <div className="row"><span className="row-content card-title sk">{item.title}</span><StatusBadge status={workStatus(state, item)} /></div>
            {item.lines.map((l) => <div key={l} className="kv kv-left"><b className="sk">{l}</b></div>)}
          </Section>
        </div>
        <div>
          {item.perform ? (
            <Section header="처리">
              <StepRow step={{
                label: "상태", done: isDone(state, id), doneText: item.perform.doneText, deadline: item.deadline, actionLabel: item.perform.label,
                onChange: (value) => dispatch({ type: "work/done", id, value }),
              }} />
            </Section>
          ) : null}
        </div>
      </div>
    </Screen>
  );
}
