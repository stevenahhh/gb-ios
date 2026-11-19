import { Icon } from "./icons";
import { assertNever, type Draft, type DraftId, type DraftKind } from "./data";
import { canReopen, draftStatus, useStore } from "./store";
import { Screen, Section, StatusBadge, UndoButton, useNav } from "./ui";

const afterApproval: Record<DraftKind, string> = {
  inquiry: "답변 완료를 눌러도 손님께 자동으로 보내지지는 않아요.",
  notice: "승인해도 아직 손님께 발송되지는 않아요.",
  promo: "승인해도 자동으로 게시되지 않아요. 게시는 직접 해 주세요.",
  market: "승인해도 자동으로 신청되지 않아요. 신청은 직접 해 주세요.",
};

function Who() {
  return <span className="who"><Icon name="sparkles" size={15} />비서 초안</span>;
}

export function DraftCompact({ id }: { id: DraftId }) {
  const { state } = useStore();
  const { push } = useNav();
  const d = state.drafts[id];
  return (
    <button className="draft draft-compact" onClick={() => push({ kind: "draft", id })}>
      <span className="draft-top"><Who /><StatusBadge status={draftStatus(d)} /></span>
      <span className="draft-title sk">{d.title}</span>
      <span className="clamp sk">{d.text || "내용을 비운 초안이에요."}</span>
    </button>
  );
}

function InquiryReply({ d }: { d: Draft }) {
  const { dispatch } = useStore();
  const id = d.id;
  return (
    <>
      <textarea value={d.text} onChange={(e) => dispatch({ type: "inquiry/text", id, value: e.target.value })} aria-label="답변 작성" />
      {d.error ? <div className="err" role="alert"><Icon name="exclFill" size={16} color="var(--orange)" />{d.error}</div> : null}
      <div className="btns btns-two">
        <button className="btn btn-bordered" onClick={() => dispatch({ type: "draft/rewrite", id })}>비서로 다시 쓰기</button>
        <button className="btn btn-prominent" disabled={!d.text.trim() || (d.status === "approved" && !d.edited)}
          onClick={() => dispatch({ type: "inquiry/complete", id })}>답변 완료</button>
      </div>
      <div className="hint">{afterApproval.inquiry}</div>
    </>
  );
}

function DraftBody({ d }: { d: Draft }) {
  const { dispatch } = useStore();
  const id = d.id;
  if (d.kind === "inquiry") return <InquiryReply d={d} />;
  if (d.editing !== undefined) {
    return (
      <>
        <textarea value={d.editing} onChange={(e) => dispatch({ type: "draft/buffer", id, value: e.target.value })} aria-label="초안 수정" />
        <div className="btns btns-two">
          <button className="btn btn-bordered" onClick={() => dispatch({ type: "draft/cancel", id })}>취소</button>
          <button className="btn btn-prominent" onClick={() => dispatch({ type: "draft/save", id })}>저장</button>
        </div>
      </>
    );
  }
  switch (d.status) {
    case "pending":
      return (
        <>
          <div className="draft-text sk">{d.text || <span className="hint">내용이 비어 있어요.</span>}</div>
          {d.error ? <div className="err" role="alert"><Icon name="exclFill" size={16} color="var(--orange)" />{d.error}</div> : null}
          <button className="btn btn-prominent" onClick={() => dispatch({ type: "draft/approve", id })}>승인하기</button>
          <div className="btns">
            <button className="btn btn-bordered" onClick={() => dispatch({ type: "draft/edit", id })}>수정</button>
            <button className="btn btn-bordered" onClick={() => dispatch({ type: "draft/rewrite", id })}>다시 쓰기</button>
            <button className="btn btn-reject" onClick={() => dispatch({ type: "draft/reject", id })}>반려</button>
          </div>
          <div className="hint">{afterApproval[d.kind]}</div>
        </>
      );
    case "approved":
    case "rejected": {
      const approved = d.status === "approved";
      return (
        <>
          <div className="draft-text sk">{d.text || <span className="hint">내용을 비운 채 반려했어요.</span>}</div>
          <div className="step-top">
            <span className="done-line">
              <Icon name={approved ? "checkFill" : "xmark"} size={18} color={approved ? "var(--green)" : "var(--secondary)"} weight={2.2} />
              {approved ? "승인했어요" : "반려했어요"}
            </span>
            {canReopen(d) ? <UndoButton onClick={() => dispatch({ type: "draft/reopen", id })} /> : null}
          </div>
          {approved ? <div className="hint">{afterApproval[d.kind]}</div> : null}
        </>
      );
    }
    default:
      return assertNever(d.status);
  }
}

export function DraftFull({ id }: { id: DraftId }) {
  const { state } = useStore();
  const d = state.drafts[id];
  return (
    <div className="draft">
      <div className="draft-top"><Who /><StatusBadge status={draftStatus(d)} /></div>
      <DraftBody d={d} />
      {d.edited && d.editing === undefined && d.kind !== "inquiry" ? <div className="hint">사장님이 고친 내용이에요.</div> : null}
    </div>
  );
}

function DraftContext({ d }: { d: Draft }) {
  switch (d.kind) {
    case "inquiry":
      return (
        <Section header="손님 문의">
          <div className="row">
            <span className="task-text"><span className="card-title sk">{d.title}</span><span className="card-line sk">{d.lines[0]}</span></span>
          </div>
          <div className="ask sk">{d.question}</div>
        </Section>
      );
    case "promo":
    case "notice":
    case "market":
      return (
        <Section header="내용">
          <div className="row">
            <span className="task-text">
              <span className="card-title sk">{d.title}</span>
              {d.lines.map((l) => <span key={l} className="card-line sk">{l}</span>)}
            </span>
          </div>
        </Section>
      );
    default:
      return assertNever(d);
  }
}

export function DraftDetailScreen({ id }: { id: DraftId }) {
  const { state } = useStore();
  const d = state.drafts[id];
  return (
    <Screen title={d.title} back>
      <div className="detail detail-three">
        <div className="d-a"><DraftContext d={d} /></div>
        <div className="d-b">
          <Section header={d.kind === "inquiry" ? "답변 작성" : "초안 검토"} footer="비서가 틀릴 수 있어요. 내용을 확인해 주세요."><DraftFull id={id} /></Section>
        </div>
        <div className="d-c">
          {d.kind === "inquiry" ? (
            <Section header="답변 근거" footer="공방에 등록해 둔 안내만 근거로 비서가 썼어요.">
              {d.facts.map((f) => <div key={f} className="fact sk">{f}</div>)}
            </Section>
          ) : null}
        </div>
      </div>
    </Screen>
  );
}
