import { createContext, useContext, useMemo, useReducer, type Dispatch, type ReactNode } from "react";
import {
  assertNever, bookingIds, inquiryIds, promoIds, seedBookings, seedDrafts, shipTodayIds, todaySuggestionIds,
  type Booking, type BookingId, type Draft, type DraftId, type LiveCounts, type Status, type WorkId, type WorkItem,
} from "./data";

export type State = {
  readonly bookings: Readonly<Record<BookingId, Booking>>;
  readonly drafts: Readonly<Record<DraftId, Draft>>;
  readonly done: readonly WorkId[];
};

type DraftAction =
  | { readonly type: "draft/approve"; readonly id: DraftId }
  | { readonly type: "draft/reject"; readonly id: DraftId }
  | { readonly type: "draft/reopen"; readonly id: DraftId }
  | { readonly type: "draft/edit"; readonly id: DraftId }
  | { readonly type: "draft/buffer"; readonly id: DraftId; readonly value: string }
  | { readonly type: "draft/cancel"; readonly id: DraftId }
  | { readonly type: "draft/save"; readonly id: DraftId }
  | { readonly type: "draft/rewrite"; readonly id: DraftId };

export type Action =
  | { readonly type: "booking/attended"; readonly id: BookingId; readonly value: boolean }
  | { readonly type: "booking/deposit"; readonly id: BookingId; readonly value: boolean }
  | { readonly type: "work/done"; readonly id: WorkId; readonly value: boolean }
  | DraftAction;

export const blankApproveError = "빈 내용은 승인할 수 없어요. 내용을 쓰거나 반려해 주세요.";

// 되돌리기는 발송·게시 전까지만 허용한다. 실제 발송/게시가 생기면 그 확인을 여기에 추가한다.
export function canReopen(draft: Draft): boolean {
  return draft.status !== "pending";
}

function reduceDraft(draft: Draft, action: DraftAction): Draft {
  switch (action.type) {
    case "draft/approve":
      if (draft.status !== "pending") return draft;
      if (!draft.text.trim()) return { ...draft, error: blankApproveError };
      return { ...draft, status: "approved", error: undefined };
    case "draft/reject":
      if (draft.status !== "pending") return draft;
      return { ...draft, status: "rejected", error: undefined };
    case "draft/reopen":
      return canReopen(draft) ? { ...draft, status: "pending" } : draft;
    case "draft/edit":
      return { ...draft, editing: draft.text, error: undefined };
    case "draft/buffer":
      return draft.editing === undefined ? draft : { ...draft, editing: action.value };
    case "draft/cancel":
      return { ...draft, editing: undefined };
    case "draft/save":
      return draft.editing === undefined ? draft : { ...draft, text: draft.editing.trim(), editing: undefined, edited: true };
    case "draft/rewrite": {
      const [next, ...rest] = draft.alternates;
      return next === undefined ? draft : { ...draft, text: next, alternates: [...rest, draft.text], edited: false, error: undefined };
    }
    default:
      return assertNever(action);
  }
}

export function reduce(state: State, action: Action): State {
  switch (action.type) {
    case "booking/attended":
      return { ...state, bookings: { ...state.bookings, [action.id]: { ...state.bookings[action.id], attended: action.value } } };
    case "booking/deposit":
      return { ...state, bookings: { ...state.bookings, [action.id]: { ...state.bookings[action.id], deposit: action.value } } };
    case "work/done": {
      const rest = state.done.filter((id) => id !== action.id);
      return { ...state, done: action.value ? [...rest, action.id] : rest };
    }
    case "draft/approve":
    case "draft/reject":
    case "draft/reopen":
    case "draft/edit":
    case "draft/buffer":
    case "draft/cancel":
    case "draft/save":
    case "draft/rewrite": {
      const draft = state.drafts[action.id];
      const next = reduceDraft(draft, action);
      return next === draft ? state : { ...state, drafts: { ...state.drafts, [action.id]: next } };
    }
    default:
      return assertNever(action);
  }
}

export const initialState = (): State => ({ bookings: seedBookings, drafts: seedDrafts, done: [] });

export const isDone = (state: State, id: WorkId) => state.done.includes(id);

export const bookingStatus = (b: Booking): Status =>
  b.attended ? { text: "수업 완료", tone: "done" } : b.deposit ? { text: "확정", tone: "done" } : { text: "예약금 대기", tone: "attention" };
export const bookingTag = (b: Booking) => (b.deposit ? "확정" : "예약금 대기");

export function draftStatus(d: Draft): Status {
  switch (d.status) {
    case "pending": return { text: "검토 대기", tone: "attention" };
    case "approved": return { text: "승인함", tone: "done" };
    case "rejected": return { text: "반려함", tone: "neutral" };
    default: return assertNever(d.status);
  }
}

export const workStatus = (state: State, item: WorkItem): Status => (item.perform && isDone(state, item.id) ? item.perform.doneStatus : item.status);

export function liveCounts(state: State): LiveCounts {
  const pending = (id: DraftId) => state.drafts[id].status === "pending";
  return {
    deposit: bookingIds.filter((id) => !state.bookings[id].deposit).length,
    inquiry: inquiryIds.filter(pending).length,
    promo: promoIds.filter(pending).length,
    ship: shipTodayIds.filter((id) => !isDone(state, id)).length,
    suggestions: todaySuggestionIds.filter(pending).length,
  };
}

export function attentionCount(state: State): number {
  const c = liveCounts(state);
  return c.deposit + c.inquiry + c.ship;
}

export const todayBookings = (state: State): readonly Booking[] =>
  bookingIds.map((id) => state.bookings[id]).filter((b) => b.day === 4).sort((a, b) => a.start.localeCompare(b.start));

type Store = { readonly state: State; readonly dispatch: Dispatch<Action> };
const StoreContext = createContext<Store | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reduce, undefined, initialState);
  const store = useMemo(() => ({ state, dispatch }), [state]);
  return <StoreContext.Provider value={store}>{children}</StoreContext.Provider>;
}

export function useStore(): Store {
  const store = useContext(StoreContext);
  if (!store) throw new Error("StoreProvider missing");
  return store;
}
