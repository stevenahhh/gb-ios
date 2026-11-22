#!/usr/bin/env python3
"""Scripted stand-in for the 공도리 server, used only by AgentUITests.

It answers the screens the app loads at launch with a small fixed workshop, and plays the assistant
agent from a script keyed by the owner's words. The shapes, routes, query names and Korean refusals are
the server's own: Server/agent_types.py, agent_api.py, agent_approvals.py, agent_api_invoices.py and
agent_settings_edit.py. Request bodies and queries are checked as strictly as the server checks them,
so a field or query the server would refuse fails here too. State lives in memory.

Run: python3 agent-stub.py --port 18652
Control, for the tests only: POST /__stub/reset, /__stub/down, /__stub/advance and GET /__stub/log,
/__stub/state, /__stub/wait. The last one answers once a named request has arrived, so a test waits for
the app's write itself and never for a length of time.
"""

import argparse
import hashlib
import json
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

KST = timezone(timedelta(hours=9))
LOCK = threading.Lock()
ARRIVED = threading.Condition(LOCK)

TOOL_TIERS = {
    "save_reply_draft": "T1", "add_event": "T1", "move_event": "T1", "complete_task": "T1",
    "reopen_task": "T1", "save_content_draft": "T1", "remember": "T1", "forget": "T1",
    "confirm_order": "T2", "mark_packed": "T2", "register_invoice": "T2", "mark_delivered": "T2",
    "confirm_deposit": "T2", "create_booking": "T2", "decide_cancellation": "T2",
    "record_quote_outcome": "T2",
}
MODES = {"off", "ask", "auto"}
BAD_INPUT = "입력한 내용을 다시 확인해 주세요."
UNKNOWN_TOOL = "알 수 없는 도구예요. 고객에게 보내기, 결제, 환불, 삭제는 비서에게 맡길 수 없어요."
STALE_SETTINGS = "그사이에 설정이 바뀌었어요. 다시 불러온 뒤 저장해 주세요."
STALE_PROPOSAL = "그사이 내용이 바뀌었어요. 다시 확인해 주세요."
MISSING_VALUE = "제안을 실행할 수 없어요. 빠진 값을 말씀해 주세요."
NO_PROPOSAL = "제안을 찾지 못했어요."
CLOSED = {"approved": "이미 승인한 제안이에요.", "dismissed": "이미 넘긴 제안이에요.", "expired": "제안 시간이 지났어요."}
NO_STEP = "그 단계를 찾지 못했어요."
ALREADY_UNDONE = "이미 되돌렸어요."
NOT_UNDOABLE = "되돌릴 수 없는 단계예요."
OTHER_FILE = "처음에 올린 파일과 달라요. 같은 파일을 다시 보내 주세요."
NOTHING_TO_REGISTER = "등록할 수 있는 송장이 없어요. 파일을 다시 확인해 주세요."
BAD_LINES = "확인한 행 번호를 읽지 못했어요."
WRONG_FORMAT = "택배사 송장번호 형식과 맞지 않아요."
ALREADY_SHIPPED = "이미 발송한 주문이에요."
FILE_STEP = "송장 파일 가져오기"
STEP_TITLES = {"confirm_order": "주문 확인", "mark_packed": "포장 완료 처리", "mark_delivered": "배송 완료 처리",
               "confirm_deposit": "예약금 확인", "register_invoice": "송장 등록",
               "record_quote_outcome": "출강 견적 결과 기록"}
ORDER_STATUS = {"paid": "주문 확인 전", "packing": "포장 대기", "invoice_pending": "송장 대기",
                "in_transit": "배송 중", "delivered": "배송 완료"}
ATTENTION = {"paid", "packing", "invoice_pending"}
INVOICE_ROWS = (
    (2, "682100042841", 1044, ()), (3, "682100042852", 1045, ()),
    (4, "68210004", 1046, (("wrong_format", WRONG_FORMAT),)),
    (5, "682100042863", 1038, (("already_shipped", ALREADY_SHIPPED),)),
    (6, "682100042874", None, ()),
)


class Refused(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def now():
    return datetime.now(KST)


def stamp(moment):
    return moment.isoformat(timespec="seconds")


def only(given, allowed, required=()):
    """Refuse unknown or missing fields, like the server's strict request models."""
    if not isinstance(given, dict):
        raise Refused(422, BAD_INPUT)
    unknown = set(given) - set(allowed)
    missing = set(required) - set(given)
    if unknown or missing:
        raise Refused(422, f"stub: unknown {sorted(unknown)}, missing {sorted(missing)}")


class Workshop:
    def __init__(self):
        self.reset({})

    def reset(self, options):
        self.down = False
        self.log = []
        self.counter = 0
        self.session = uuid.uuid4().hex[:6]
        self.empty = options.get("empty") is True
        self.lose_reply = options.get("loseReply") is True
        self.no_agent = options.get("noAgent") is True
        self.file_rows = [row for row in INVOICE_ROWS if row[3] or row[2] is None] if options.get("dirtyFile") else INVOICE_ROWS
        self.settings = {
            "mode": options.get("mode", "auto"), "proactive": True, "per_tool": {}, "daily_cap": 20,
            "quiet": {"start": "22:00", "end": "08:00"}, "interval_minutes": 15, "revision": 0,
            "updated_at": None,
        }
        self.orders = {
            1038: {"title": "오롯 머그컵", "customer": "최민호", "status": "in_transit", "revision": 6},
            1040: {"title": "머그컵 2종 세트", "customer": "김지은", "status": "packing", "revision": 3},
            1041: {"title": "핸드메이드 접시", "customer": "박서준", "status": "paid", "revision": 2},
            1042: {"title": "오롯 화병", "customer": "이하나", "status": "packing", "revision": 3},
            1044: {"title": "찻잔 세트", "customer": "한서윤", "status": "invoice_pending", "revision": 4},
            1045: {"title": "오롯 접시", "customer": "문도현", "status": "invoice_pending", "revision": 4},
            1046: {"title": "미니 화분", "customer": "서지안", "status": "invoice_pending", "revision": 4},
        }
        self.invoices = {}
        self.quote_outcome = None
        self.deposit_confirmed = False
        self.steps = {}
        self.proposals = {}
        self.runs = []
        self.sent = {}
        self.background = None
        self.memories = [] if self.empty else [
            {"id": "mem-2", "kind": "rule_of_thumb", "text": "단체 문의는 6명부터 받아요",
             "sourceQuote": "단체는 여섯 명부터만 받아", "createdAt": stamp(now() - timedelta(days=1)),
             "lastUsedAt": stamp(now() - timedelta(hours=5))},
            {"id": "mem-1", "kind": "preference", "text": "택배는 주로 CJ대한통운으로 보내요",
             "sourceQuote": "우리는 거의 CJ로 보내", "createdAt": stamp(now() - timedelta(days=3)),
             "lastUsedAt": None},
        ]
        if not self.empty:
            self.seed(options)

    def next_id(self, prefix):
        self.counter += 1
        return f"{prefix}-{self.session}-{self.counter}"

    def order_target(self, number, kind="shipment"):
        order = self.orders[number]
        row = f"shipment-order-{number}" if kind == "shipment" else f"order-{number}"
        return {"kind": kind, "id": row, "label": f"주문 {number} · {order['customer']} 님"}

    def add_step(self, tool, title, decision, reason, target=None, evidence=(), undo=None):
        step = {
            "id": self.next_id("step"), "tool": tool, "title": title, "decision": decision, "reason": reason,
            "target": target, "evidence": [{"kind": "owner_turn", "excerpt": text} for text in evidence],
            "undoable": undo is not None, "undone": False,
        }
        self.steps[step["id"]] = {"view": step, "undo": undo}
        return step

    def add_proposal(self, tool, title, reason, preview, needed, target, lifetime, action, revision=2):
        """One proposed step and the proposal it raised; approving later runs that same step."""
        step = self.add_step(tool, title, "proposed", reason, target)
        proposal = {
            "id": self.next_id("proposal"), "stepId": step["id"], "title": title, "reason": reason,
            "preview": [{"label": label, "value": value} for label, value in preview],
            "evidenceNeeded": list(needed), "expiresAt": stamp(now() + lifetime),
            "expectedRevision": revision, "tool": tool, "state": "open", "target": target, "step": None,
        }
        self.proposals[proposal["id"]] = {"view": proposal, "action": action, "expires": now() + lifetime}
        return proposal, step

    def add_run(self, source, question, status, answer, steps=(), proposals=(), started=None):
        started = started or now()
        run = {
            "id": self.next_id("run"), "status": status, "source": source, "question": question,
            "answer": answer, "intent": "act" if steps else "lookup", "modelCalls": 0 if source == "proactive" else 1,
            "tokens": 0 if source == "proactive" else 420, "error": None, "createdAt": stamp(started),
            "startedAt": stamp(started),
            "endedAt": None if status in {"queued", "running"} else stamp(started + timedelta(seconds=4)),
            "steps": list(steps), "proposals": list(proposals),
        }
        self.runs.insert(0, run)
        return run

    def seed(self, options):
        packed = self.add_step("mark_packed", "포장 완료 처리", "auto", "사장님이 그 대화에서 직접 말씀하셨어요.",
                               {"kind": "shipment", "id": "shipment-order-1039", "label": "주문 1039 · 정유나 님"},
                               ["1039 포장 끝났어"])
        self.add_run("voice", "1039 포장 끝났어", "done", "주문 1039를 포장 완료로 바꿨어요.", [packed],
                     started=now() - timedelta(days=1, hours=2))
        event = self.add_step("add_event", "일정 추가", "auto", "공방 안에서 되돌릴 수 있는 일이에요.",
                              {"kind": "event", "id": "event-7", "label": "가마 청소 · 내일 10:00"},
                              ["내일 10시에 가마 청소 넣어 줘"], undo=("event", 7))
        self.add_run("chat", "내일 10시에 가마 청소 넣어 줘", "done", "내일 10:00에 가마 청소를 넣었어요.", [event],
                     started=now() - timedelta(hours=5))
        raised = [
            self.add_proposal(
                "confirm_order", "주문 1041을 확인할까요?", "결제하고 3시간이 지났는데 아직 확인 전이에요.",
                [("주문", "#1041 핸드메이드 접시"), ("주문한 분", "박서준 님"), ("결제", "45,000원 · 3시간 전")],
                [], self.order_target(1041, "order"), timedelta(hours=5), ("order", 1041, "packing")),
            self.add_proposal(
                "confirm_deposit", "김지은 님 예약금을 확인 처리할까요?", "예약금 기한이 24시간 안으로 다가왔어요.",
                [("예약", "토요일 14:00 물레 클래스 · 2명"), ("예약금", "20,000원"), ("기한", "내일 12:00")],
                ["입금을 확인했는지"], {"kind": "booking", "id": "booking-jieun", "label": "김지은 님 · 물레 클래스"},
                timedelta(hours=20), ("deposit",)),
        ]
        if options.get("expired"):
            raised.append(self.add_proposal(
                "mark_delivered", "주문 1038을 배송 완료로 바꿀까요?", "택배사 조회가 연결돼 있지 않아 확인이 필요해요.",
                [("주문", "#1038 오롯 머그컵"), ("받는 분", "최민호 님"), ("송장", "CJ대한통운 6821 0004 2841")],
                ["배송이 끝났는지"], self.order_target(1038), timedelta(minutes=-2), ("order", 1038, "delivered")))
        if options.get("needsValue"):
            raised.append(self.add_proposal(
                "register_invoice", "주문 1046 송장 등록", "포장을 마쳤는데 송장 번호가 없어요. 내일 16:00에 택배를 보내야 해요.",
                [("주문", "#1046 미니 화분"), ("받는 분", "서지안 님")],
                ["송장 번호"], self.order_target(1046), timedelta(hours=18), ("needs_value",), revision=4))
            raised.append(self.add_proposal(
                "record_quote_outcome", "순천초등학교 출강 견적 답 적기", "견적을 보낸 지 사흘이 지났는데 답을 적지 않았어요.",
                [("기관", "순천초등학교"), ("견적", "450,000원")],
                ["기관의 답"], {"kind": "quote", "id": "quote-1", "label": "순천초등학교 출강 견적"},
                timedelta(hours=22), ("needs_value",), revision=1))
        self.add_run("proactive", "오늘 챙길 일이 있는지 확인했어요.", "done", None,
                     [step for _, step in raised], [proposal for proposal, _ in raised],
                     started=now() - timedelta(hours=1))

    def shipment_task(self, number):
        order = self.orders[number]
        status = order["status"]
        return {
            "id": f"shipment-order-{number}", "target": "shipment", "time": None, "title": order["title"],
            "detail": f"#{number} · {order['customer']} 님",
            "status": {"text": ORDER_STATUS[status], "tone": "attention" if status in ATTENTION else "progress"},
            "isDone": None, "revision": order["revision"],
            "due": {"at": stamp((now() + timedelta(days=1)).replace(hour=16, minute=0, second=0)),
                    "prefix": "수거", "suffix": "까지", "missed": None},
            "startsAt": None,
        }

    def today(self):
        waiting = [n for n, order in self.orders.items() if order["status"] in ATTENTION]
        return {
            "date": now().date().isoformat(), "attentionCount": len(waiting),
            "tasks": {
                "metrics": [
                    {"key": "classes", "label": "오늘 수업", "display": "1건", "detail": None, "due": None},
                    {"key": "parcels", "label": "보낼 소포", "display": f"{len(waiting)}건", "detail": None, "due": None},
                    {"key": "inquiries", "label": "새 문의", "display": "0건", "detail": None, "due": None},
                ],
                "groups": [{"title": "보낼 소포", "kind": "delivery", "area": "deliveries",
                            "items": [self.shipment_task(n) for n in sorted(waiting)]}],
            },
            "channels": {"metrics": [], "cards": [], "todos": []},
            "delivery": {"metrics": [], "shipToday": [], "inTransit": [],
                         "transitSummary": "이동 중인 배송 1건", "transitDetail": "오늘 도착 예정은 없어요"},
            "suggestions": {"metrics": [], "items": []},
            "headline": None,
        }

    def baseline(self, path):
        month = {"key": now().strftime("%Y-%m"), "title": f"{now().month}월", "range": "이번 달"}
        screens = {
            "/today": self.today,
            "/inquiries": lambda: [],
            "/judgments": lambda: [] if self.empty else [{
                "id": "judgment-1", "inquiryId": "inquiry-1", "issue": "단체 할인 문의", "status": "open",
                "customer": "이서연", "question": "여덟 명이 가면 할인이 되나요?", "answerText": None}],
            "/opportunities": lambda: [],
            "/k06/cards": lambda: {"policyVersion": None, "late": [], "refill": [], "underMin": [],
                                   "reminders": [], "sessions": []},
            "/settings": lambda: {"workshop": {
                "name": "오롯 공방", "ownerTitle": "장가연 사장님", "phone": "061-000-0000",
                "address": "전남 순천시", "description": "도자기 원데이 클래스와 생활 자기",
                "latitude": None, "longitude": None, "revision": 1}, "items": [], "channels": []},
            "/calendar": lambda: {"days": [], "overdueShipments": []},
            "/collectors/status": lambda: {"sources": [], "updated_at": stamp(now())},
            "/operations": lambda: {
                "attentionCount": 3, "attention": [],
                "period": {"month": month, "handled": 0, "total": 0, "metrics": [], "comparisons": []},
                "months": [month], "areas": []},
            "/assistant/activities": lambda: [] if self.empty else [{
                "id": "activity-1", "at": stamp(now() - timedelta(hours=3)), "kind": "contentDraft",
                "targetId": "content-1", "summary": "주말 클래스 홍보 글 초안을 썼어요", "status": "검토 대기",
                "evidence": ["토요일 14:00 물레 클래스 두 자리 남음"]}],
        }
        build = screens.get(path)
        if build is None:
            raise Refused(404, "찾을 수 없는 항목이에요.")
        return build()

    def tool_mode(self, tool):
        stored = self.settings
        return "off" if stored["mode"] == "off" else stored["per_tool"].get(tool, stored["mode"])

    def settings_view(self):
        stored = self.settings
        return {
            "mode": stored["mode"], "proactive": stored["proactive"],
            "tools": [{"tool": tool, "tier": tier, "mode": self.tool_mode(tool)}
                      for tool, tier in TOOL_TIERS.items()],
            "dailyCap": stored["daily_cap"], "quietHours": stored["quiet"],
            "intervalMinutes": stored["interval_minutes"], "revision": stored["revision"],
            "updatedAt": stored["updated_at"],
        }

    def update_settings(self, body):
        only(body, {"expectedRevision", "mode", "proactive", "perTool", "dailyCap", "quietHours", "intervalMinutes"},
             required={"expectedRevision"})
        stored = self.settings
        if body["expectedRevision"] != stored["revision"]:
            raise Refused(409, STALE_SETTINGS)
        changed = dict(stored)
        if body.get("mode") is not None:
            if body["mode"] not in MODES:
                raise Refused(422, BAD_INPUT)
            changed["mode"] = body["mode"]
        if body.get("proactive") is not None:
            changed["proactive"] = body["proactive"]
        if body.get("perTool") is not None:
            switches = dict(stored["per_tool"])
            for tool, mode in body["perTool"].items():
                if tool not in TOOL_TIERS:
                    raise Refused(422, UNKNOWN_TOOL)
                if mode not in MODES:
                    raise Refused(422, BAD_INPUT)
                switches[tool] = mode
            changed["per_tool"] = switches
        if body.get("dailyCap") is not None:
            if type(body["dailyCap"]) is not int or not 1 <= body["dailyCap"] <= 50:
                raise Refused(422, BAD_INPUT)
            changed["daily_cap"] = body["dailyCap"]
        if "quietHours" in body:
            quiet = body["quietHours"]
            if quiet is not None:
                only(quiet, {"start", "end"}, required={"start", "end"})
                if quiet["start"] == quiet["end"]:
                    raise Refused(422, BAD_INPUT)
            changed["quiet"] = quiet
        if body.get("intervalMinutes") is not None:
            changed["interval_minutes"] = body["intervalMinutes"]
        if changed != stored:
            changed["revision"] = stored["revision"] + 1
            changed["updated_at"] = stamp(now())
            self.settings = changed
        return self.settings_view()

    def set_order(self, number, status):
        order = self.orders[number]
        previous = order["status"]
        order["status"] = status
        order["revision"] += 1
        return previous

    def pack(self, number, said):
        previous = self.set_order(number, "invoice_pending")
        return self.add_step("mark_packed", "포장 완료 처리", "auto", "사장님이 이번 대화에서 직접 말씀하셨어요.",
                             self.order_target(number), [said], undo=("order", number, previous))

    def response(self, run):
        return {"runId": run["id"], "status": run["status"], "answer": run["answer"], "steps": run["steps"],
                "proposals": run["proposals"], "intent": run["intent"], "mode": self.settings["mode"]}

    def run(self, body):
        only(body, {"question", "requestId", "history", "source", "background"}, required={"question"})
        question = body["question"]
        history = body.get("history", [])
        request_id = body.get("requestId")
        if not isinstance(question, str) or not 1 <= len(question) <= 1000 or len(history) > 40:
            raise Refused(422, BAD_INPUT)
        if request_id is not None and (not isinstance(request_id, str) or not 8 <= len(request_id) <= 64):
            raise Refused(422, BAD_INPUT)
        for turn in history:
            only(turn, {"role", "text"}, required={"role", "text"})
            if turn["role"] not in {"owner", "assistant"} or not 1 <= len(turn["text"]) <= 2000:
                raise Refused(422, BAD_INPUT)
        source = body.get("source", "chat")
        if source not in {"chat", "voice"}:
            raise Refused(422, BAD_INPUT)
        if request_id in self.sent:
            return self.response(self.sent[request_id])
        if "실패 시험" in question:
            raise Refused(500, "서버가 요청을 처리하지 못했어요.")
        mode = self.settings["mode"]
        if mode == "off":
            run = self.add_run(source, question, "fallback", "비서가 꺼져 있어서 답만 드려요.")
        elif body.get("background") is True:
            run = self.add_run(source, question, "queued", None)
            numbers = [int(n) for n in re.findall(r"\b10\d\d\b", question) if int(n) in self.orders]
            self.background = {"run": run, "said": question.splitlines()[0], "left": numbers}
        else:
            run = self.scripted(source, question)
        if request_id is not None:
            self.sent[request_id] = run
        if self.lose_reply:
            self.lose_reply = False
            raise Refused(503, "서버에 연결하지 못했어요.")
        return self.response(run)

    def scripted(self, source, question):
        named = re.search(r"\b10\d\d\b", question)
        number = int(named.group()) if named and int(named.group()) in self.orders else None
        tracking = re.search(r"\b\d{10,14}\b", question)
        if "송장" in question and number is not None and tracking is not None:
            previous = self.set_order(number, "in_transit")
            self.invoices[number] = tracking.group()
            step = self.add_step("register_invoice", "송장 등록", "auto", "사장님이 이번 대화에서 직접 말씀하셨어요.",
                                 self.order_target(number), [tracking.group()], undo=("order", number, previous))
            return self.add_run(source, question, "done", f"주문 {number} 송장을 말씀하신 번호 그대로 등록했어요.", [step])
        if "견적" in question and ("수락" in question or "거절" in question):
            self.quote_outcome = "accepted" if "수락" in question else "declined"
            step = self.add_step("record_quote_outcome", "출강 견적 결과 기록", "auto", "사장님이 이번 대화에서 직접 말씀하셨어요.",
                                 {"kind": "quote", "id": "quote-1", "label": "순천초등학교 출강 견적"}, [question])
            return self.add_run(source, question, "done", "순천초등학교 출강 견적 답을 적었어요.", [step])
        if "포장" in question and ("끝났" in question or "완료" in question):
            mode = self.tool_mode("mark_packed")
            if mode == "off":
                step = self.add_step("mark_packed", "포장 완료 처리", "refused", "꺼 두신 일이라 하지 않았어요.")
                return self.add_run(source, question, "done", "포장 완료 처리는 꺼 두셔서 하지 않았어요.", [step])
            if number is None:
                step = self.add_step(
                    "mark_packed", "포장 완료 처리", "clarify",
                    "포장 대기인 주문이 1040과 1042 두 건이에요. 어느 주문인지 번호로 알려 주세요.")
                return self.add_run(source, question, "done", "어느 주문 포장이 끝났는지 알려 주세요.", [step])
            if mode == "ask":
                proposal, step = self.add_proposal(
                    "mark_packed", f"주문 {number}을 포장 완료로 바꿀까요?", "‘물어보고’로 설정하셔서 제안으로 올렸어요.",
                    [("주문", f"#{number} {self.orders[number]['title']}"), ("받는 분", f"{self.orders[number]['customer']} 님")],
                    [], self.order_target(number), timedelta(hours=24), ("order", number, "invoice_pending"),
                    revision=self.orders[number]["revision"])
                return self.add_run(source, question, "done", f"주문 {number} 포장 완료를 제안으로 올렸어요. 승인하시면 바꿀게요.",
                                    [step], [proposal])
            step = self.pack(number, question)
            return self.add_run(source, question, "done", f"주문 {number}을 포장 완료로 바꿨어요. 다음은 송장 등록이에요.", [step])
        if "취소" in question:
            step = self.add_step(
                "decide_cancellation", "예약 취소 결정", "refused",
                "취소와 환불은 금액이 걸려 있어서 사장님이 취소 화면에서 직접 정하셔야 해요.",
                {"kind": "booking", "id": "booking-jieun", "label": "김지은 님 · 물레 클래스"})
            return self.add_run(source, question, "done", "예약 취소는 대신 결정하지 않았어요. 오늘 탭의 취소 메시지 붙여넣기에서 금액을 확인하고 정해 주세요.", [step])
        if "보내" in question:
            return self.add_run(source, question, "done", "손님에게 보내는 일은 비서가 하지 않아요. 보낼 문장을 초안으로 써 드릴 수 있어요.")
        return self.add_run(source, question, "done", "오늘 보낼 소포는 1040과 1042 두 건이에요.")

    def advance(self):
        """Move the background run one step on, so a test sees each state without waiting on a clock."""
        job = self.background
        if job is None:
            raise Refused(409, "stub: no background run")
        run = job["run"]
        if job["left"]:
            run["status"] = "running"
            run["steps"].append(self.pack(job["left"].pop(0), job["said"]))
        else:
            run["status"] = "done"
            run["answer"] = f"주문 {len(run['steps'])}건을 포장 완료로 바꿨어요."
            run["endedAt"] = stamp(now())
            self.background = None
        return run

    def find_run(self, run_id):
        for run in self.runs:
            if run["id"] == run_id:
                return run
        raise Refused(404, "그 실행을 찾지 못했어요.")

    def open_proposals(self):
        views = [entry["view"] for entry in self.proposals.values() if entry["view"]["state"] == "open"]
        return {"items": sorted(views, key=lambda view: view["expiresAt"])}

    def open_proposal(self, proposal_id):
        entry = self.proposals.get(proposal_id)
        if entry is None:
            raise Refused(404, NO_PROPOSAL)
        view = entry["view"]
        if view["state"] == "open" and entry["expires"] <= now():
            view["state"] = "expired"
        if view["state"] != "open":
            raise Refused(409, CLOSED[view["state"]])
        return entry

    def approve(self, proposal_id, body):
        only(body, {"expectedRevision"})
        entry = self.open_proposal(proposal_id)
        view = entry["view"]
        if body.get("expectedRevision") != view["expectedRevision"]:
            raise Refused(409, STALE_PROPOSAL)
        action = entry["action"]
        step = self.steps[view["stepId"]]
        if action[0] in {"needs_value", "file"}:
            raise Refused(409, MISSING_VALUE)
        if action[0] == "order":
            step["undo"] = ("order", action[1], self.set_order(action[1], action[2]))
        else:
            self.deposit_confirmed = True
            step["undo"] = ("deposit",)
        step["view"]["undoable"] = True
        view["state"] = "approved"
        view["step"] = step["view"]
        return view

    def dismiss(self, proposal_id):
        view = self.open_proposal(proposal_id)["view"]
        view["state"] = "dismissed"
        return view

    def undo(self, step_id):
        entry = self.steps.get(step_id)
        if entry is None:
            raise Refused(404, NO_STEP)
        view = entry["view"]
        if view["undone"]:
            raise Refused(409, ALREADY_UNDONE)
        undo = entry["undo"]
        if undo is None:
            raise Refused(409, NOT_UNDOABLE)
        if undo[0] == "order":
            self.set_order(undo[1], undo[2])
            self.invoices.pop(undo[1], None)
            summary = f"주문 {undo[1]}을 {ORDER_STATUS[undo[2]]}(으)로 되돌렸어요."
        elif undo[0] == "deposit":
            self.deposit_confirmed = False
            summary = "예약금 확인을 되돌렸어요."
        else:
            summary = "일정을 지웠어요."
        view["undone"] = True
        view["undoable"] = False
        return {"step": view, "summary": summary}

    def forget(self, memory_id):
        if not any(memory["id"] == memory_id for memory in self.memories):
            raise Refused(404, "그 메모를 찾지 못했어요.")
        self.memories = [memory for memory in self.memories if memory["id"] != memory_id]

    def checked_file(self, data, filename, content_type):
        if content_type != "application/octet-stream":
            raise Refused(422, "stub: the file goes as application/octet-stream")
        if not filename.lower().endswith((".csv", ".xlsx")):
            raise Refused(422, "CSV나 XLSX 파일만 읽을 수 있어요.")
        if not data:
            raise Refused(422, "CSV 형식이 올바르지 않아요.")
        if len(data) > 2 * 1024 * 1024:
            raise Refused(413, "파일이 너무 커요. 2MB 이하로 나눠 주세요.")

    def import_invoices(self, data, filename, content_type, query):
        only(query, {"filename"}, required={"filename"})
        self.checked_file(data, filename, content_type)
        rows = []
        for line, number, order, problems in self.file_rows:
            target = None if order is None else {
                "kind": "shipment", "id": f"shipment-order-{order}", "label": f"주문 {order}",
                "revision": self.orders[order]["revision"]}
            rows.append({
                "line": line, "number": number, "match": "one" if target else "none", "target": target,
                "candidates": [] if target is None else [target], "carrier": "CJ대한통운", "carrierStatus": "known",
                "problems": [{"code": code, "text": text} for code, text in problems],
                "confidence": 0.3 if problems or target is None else 1.0,
                "needsOwner": bool(problems) or target is None})
        ready = sum(1 for row in rows if not row["needsOwner"])
        proposal_id = None
        if ready:
            proposal, step = self.add_proposal(
                "register_invoice", FILE_STEP, f"송장 {ready}건을 한 번에 등록해요.",
                [("파일", filename), ("등록할 송장", f"{ready}건"), ("확인 필요", f"{len(rows) - ready}건")],
                [], None, timedelta(hours=24), ("file", hashlib.sha256(data).hexdigest()), revision=None)
            self.add_run("chat", f"{FILE_STEP}: {filename}", "done", None, [step], [proposal])
            proposal_id = proposal["id"]
        return {"rows": rows, "readyCount": ready, "proposalCount": 1 if ready else 0, "proposalId": proposal_id}

    def approve_invoices(self, proposal_id, data, filename, content_type, query):
        only(query, {"filename", "acceptFormat"}, required={"filename"})
        self.checked_file(data, filename, content_type)
        accepted = [part.strip() for part in query.get("acceptFormat", "").split(",") if part.strip()]
        if not all(part.isdecimal() for part in accepted):
            raise Refused(422, BAD_LINES)
        lines = {int(part) for part in accepted}
        entry = self.open_proposal(proposal_id)
        if entry["action"] != ("file", hashlib.sha256(data).hexdigest()):
            raise Refused(409, OTHER_FILE)
        chosen = [row for row in self.file_rows if row[2] is not None and (
            not row[3] or ([code for code, _ in row[3]] == ["wrong_format"] and row[0] in lines))]
        if not chosen:
            raise Refused(409, NOTHING_TO_REGISTER)
        if any(self.orders[order]["status"] != "invoice_pending" for _, _, order, _ in chosen):
            raise Refused(409, f"1건을 등록하지 못했어요. {ALREADY_SHIPPED}")
        for _, number, order, _ in chosen:
            self.set_order(order, "in_transit")
            self.invoices[order] = number
        view = entry["view"]
        view["state"] = "approved"
        view["step"] = self.steps[view["stepId"]]["view"]
        return {"registered": len(chosen), "proposal": view}


WORKSHOP = Workshop()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        return

    def reply(self, status, payload):
        data = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_request(self, method):
        url = urlsplit(self.path)
        path = url.path.rstrip("/") or "/"
        query = {key: values[0] for key, values in parse_qs(url.query, keep_blank_values=True).items()}
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        with LOCK:
            try:
                if path.startswith("/__stub/"):
                    return self.reply(200, self.control(method, path, query, raw))
                WORKSHOP.log.append({"method": method, "path": path, "query": query, "bytes": len(raw)})
                ARRIVED.notify_all()
                if WORKSHOP.down:
                    raise Refused(503, "서버에 연결하지 못했어요.")
                answer = self.route(method, path, query, raw)
                self.reply(204 if answer is None else 200, answer)
            except Refused as refused:
                self.reply(refused.status, {"detail": refused.detail})
            except ValueError:
                self.reply(422, {"detail": BAD_INPUT})

    def control(self, method, path, query, raw):
        body = json.loads(raw) if raw else {}

        def arrivals():
            return sum(1 for request in WORKSHOP.log
                       if request["method"] == query.get("method") and request["path"] == query.get("path"))

        match (method, path):
            case ("GET", "/__stub/wait"):
                if not ARRIVED.wait_for(lambda: arrivals() >= int(query.get("count", 1)), timeout=20):
                    raise Refused(504, "stub: that request never arrived")
                return {"count": arrivals()}
            case ("POST", "/__stub/reset"):
                WORKSHOP.reset(body)
                return {"ok": True}
            case ("POST", "/__stub/down"):
                WORKSHOP.down = bool(body.get("down", True))
                return {"down": WORKSHOP.down}
            case ("POST", "/__stub/advance"):
                return WORKSHOP.advance()
            case ("GET", "/__stub/log"):
                return {"requests": WORKSHOP.log}
            case ("GET", "/__stub/state"):
                return {"orders": {str(number): order["status"] for number, order in WORKSHOP.orders.items()},
                        "invoices": {str(number): text for number, text in WORKSHOP.invoices.items()},
                        "quoteOutcome": WORKSHOP.quote_outcome,
                        "depositConfirmed": WORKSHOP.deposit_confirmed, "settings": WORKSHOP.settings_view(),
                        "memories": [memory["id"] for memory in WORKSHOP.memories],
                        "questions": [run["question"] for run in WORKSHOP.runs],
                        "proposals": [{"id": entry["view"]["id"], "title": entry["view"]["title"],
                                       "state": entry["view"]["state"]} for entry in WORKSHOP.proposals.values()]}
        raise Refused(404, "stub: unknown control")

    def route(self, method, path, query, raw):
        parts = path.strip("/").split("/")
        if parts[0] != "agent":
            if method == "POST" and path == "/ask":
                return {"answer": "지금은 답만 드려요. 오늘 보낼 소포는 두 건이에요.", "items": []}
            if method != "GET":
                raise Refused(409, "stub: this write is not scripted")
            return WORKSHOP.baseline(path)
        if WORKSHOP.no_agent:
            raise Refused(404, "Not Found")
        content_type = self.headers.get("Content-Type", "")
        match (method, parts[1:]):
            case ("POST", ["invoices", "import"]):
                return WORKSHOP.import_invoices(raw, query.get("filename", ""), content_type, query)
            case ("POST", ["invoices", proposal_id, "approve"]):
                return WORKSHOP.approve_invoices(proposal_id, raw, query.get("filename", ""), content_type, query)
        body = json.loads(raw) if raw else {}
        match (method, parts[1:]):
            case ("GET", ["settings"]):
                return WORKSHOP.settings_view()
            case ("PUT", ["settings"]):
                return WORKSHOP.update_settings(body)
            case ("POST", ["run"]):
                return WORKSHOP.run(body)
            case ("GET", ["runs"]):
                limit = int(query.get("limit", 20))
                if not 1 <= limit <= 100:
                    raise Refused(422, BAD_INPUT)
                return {"items": WORKSHOP.runs[:limit]}
            case ("GET", ["runs", run_id]):
                return WORKSHOP.find_run(run_id)
            case ("GET", ["proposals"]):
                return WORKSHOP.open_proposals()
            case ("POST", ["proposals", proposal_id, "approve"]):
                return WORKSHOP.approve(proposal_id, body)
            case ("POST", ["proposals", proposal_id, "dismiss"]):
                return WORKSHOP.dismiss(proposal_id)
            case ("POST", ["steps", step_id, "undo"]):
                return WORKSHOP.undo(step_id)
            case ("GET", ["memories"]):
                return {"items": WORKSHOP.memories}
            case ("DELETE", ["memories", memory_id]):
                return WORKSHOP.forget(memory_id)
        raise Refused(404, "찾을 수 없는 항목이에요.")

    def do_GET(self):
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")

    def do_PUT(self):
        self.handle_request("PUT")

    def do_DELETE(self):
        self.handle_request("DELETE")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=18652)
    port = parser.parse_args().port
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"READY http://127.0.0.1:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
