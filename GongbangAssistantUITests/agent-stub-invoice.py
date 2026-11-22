#!/usr/bin/env python3
"""Scripted stand-in for the 공도리 server, used only by AgentInvoiceUITests.

It extends agent-stub.py beside it: a longer carrier export, requests that fail on demand, and background runs
that end early. Its invoice rows use the problem codes and sentences of Server/agent_invoice_types.py.

Files are approved once: POST /agent/invoices/{proposalId}/approve?filename=<name>&acceptFormat=<lines>, with the
same bytes, all rows or none, answered {registered, proposal}.

Run: python3 agent-stub-invoice.py --port 18653
Control, besides agent-stub.py's: POST /__stub/fail, /__stub/mend, /__stub/ship and
/__stub/finish.
"""

import argparse
import importlib.util
import json
from http.server import ThreadingHTTPServer
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("agent_stub", Path(__file__).with_name("agent-stub.py"))
base = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base)
Refused = base.Refused

PROBLEM_TEXT = {
    "duplicate_in_text": "붙여 넣은 글에 같은 송장번호나 주문이 겹쳐요.",
    "already_used": "이 번호는 벌써 다른 주문에 들어가 있어요.",
    "already_shipped": "벌써 보낸 택배예요.",
    "not_packed": "포장이 아직이라 송장을 못 넣어요.",
    "wrong_format": "보통 송장번호보다 자릿수가 길거나 짧아요. 번호를 한 번 더 봐 주세요.",
    "recipient_mismatch": "주문서와 받는 분 이름이 달라요.",
    "columns_swapped": "두 번호가 칸을 바꿔 들어간 듯해요. 주문번호와 송장번호를 봐 주세요.",
}
CHANGED = "올리신 뒤 송장 내용이 바뀌었어요. 파일을 새로 불러와 주세요."
CJ = "CJ대한통운"
# line, number, order, match, carrier, carrier status, problems
ROWS = (
    (2, "682100042841", 1044, "one", CJ, "known", ()),
    (3, "682100042852", 1045, "one", CJ, "known", ()),
    (4, "682100042863", 1046, "one", CJ, "known", ()),
    (5, "68210004", 1047, "one", CJ, "known", ("wrong_format",)),
    (6, "68210005", 1048, "one", CJ, "known", ("wrong_format",)),
    (7, "682100042874", 1049, "one", "한진택배", "guessed", ()),
    (8, "682100042885", 1050, "one", CJ, "known", ("columns_swapped",)),
    (9, "682100042896", 1038, "one", CJ, "known", ("already_shipped",)),
    (10, "682100042907", 1040, "one", CJ, "known", ("not_packed",)),
    (11, "682100042918", 1051, "one", CJ, "known", ("duplicate_in_text",)),
    (12, "682100042929", 1052, "one", CJ, "known", ("already_used",)),
    (13, "682100042930", 1053, "one", CJ, "known", ("recipient_mismatch",)),
    (14, "682100042941", None, "none", CJ, "known", ()),
    (15, "682100042952", None, "several", CJ, "known", ()),
    (16, "9900112233", 1054, "one", None, "unknown", ()),
)


class InvoiceWorkshop(base.Workshop):
    def reset(self, options):
        super().reset(options)
        self.faults = []
        self.rows = {"none": (), "blocked": ROWS[7:], "warned": ROWS[3:5]}.get(options.get("rows"), ROWS)
        self.file_proposal = None
        self.shown = []
        for number in range(1047, 1055):
            self.orders[number] = {"title": "오롯 종지", "customer": "손님", "status": "invoice_pending", "revision": 4}
        if options.get("onlyChat") is True:
            self.runs = [run for run in self.runs if run["source"] == "chat"]

    def fault(self, method, path):
        for fault in self.faults:
            if fault["method"] == method and path.startswith(fault["path"]):
                raise Refused(fault["status"], fault["detail"])

    def advance(self):
        job = self.background
        if job is not None and self.settings["mode"] == "off":
            return self.finish("stopped")
        return super().advance()

    def finish(self, status):
        if self.background is None:
            raise Refused(409, "stub: no background run")
        run = self.background["run"]
        run["status"] = status
        run["endedAt"] = base.stamp(base.now())
        self.background = None
        return run

    def target(self, number):
        return {"kind": "shipment", "id": f"shipment-order-{number}", "label": f"#{number}",
                "revision": self.orders[number]["revision"]}

    def row_view(self, row):
        line, number, order, match, carrier, status, problems = row
        target = None if order is None else self.target(order)
        candidates = [self.target(1051), self.target(1052)] if match == "several" else [target] if target else []
        sure = match == "one" and status == "known" and not problems
        return {"line": line, "number": number, "match": match, "target": target, "candidates": candidates,
                "carrier": carrier, "carrierStatus": status,
                "problems": [{"code": code, "text": PROBLEM_TEXT[code]} for code in problems],
                "confidence": 1.0 if sure else 0.3, "needsOwner": not sure}

    def import_invoices(self, data, filename, content_type, query):
        base.only(query, {"filename"}, required={"filename"})
        self.checked_file(data, filename, content_type)
        self.imported = (filename, data)
        views = [self.row_view(row) for row in self.rows]
        self.shown = self.clean_lines()
        ready = len(self.shown)
        openable = ready or any(row[6] == ("wrong_format",) for row in self.rows)
        self.file_proposal = self.add_proposal(
            "register_invoice", "송장 파일로 한 번에 넣기", f"송장 {ready}건을 한 번에 등록해요.",
            [("파일", filename), ("넣을 송장", f"{ready}건")], [], None,
            base.timedelta(hours=24), ("file",), revision=None)[0] if openable else None
        return {"rows": views, "readyCount": ready, "proposalCount": 1 if openable else 0,
                "proposalId": self.file_proposal["id"] if openable else None}

    def clean_lines(self):
        """The rows one approval covers now; a parcel sent meanwhile is not among them."""
        return [row[0] for row in self.rows
                if not self.row_view(row)["needsOwner"] and self.orders[row[2]]["status"] == "invoice_pending"]

    def approve_file(self, proposal_id, data, filename, content_type, query):
        self.checked_file(data, filename, content_type)
        base.only(query, {"filename", "acceptFormat"}, required={"filename"})
        view = self.open_proposal(proposal_id)["view"]
        if self.imported != (filename, data):
            raise Refused(409, "아까와 다른 파일이에요. 처음에 쓰신 그 파일로 올려 주세요.")
        if self.clean_lines() != self.shown:
            raise Refused(409, CHANGED)
        accepted = {int(part) for part in query.get("acceptFormat", "").split(",") if part.strip()}
        chosen = [row for row in self.rows if row[0] in self.shown
                  or (row[0] in accepted and row[6] == ("wrong_format",))]
        if not chosen:
            raise Refused(409, "넣을 송장이 하나도 안 남았어요. 어느 줄을 보셨는지 알려 주세요.")
        steps = []
        for _, number, order, *_ in chosen:
            previous = self.set_order(order, "in_transit")
            steps.append(self.add_step(
                "register_invoice", "송장 등록", "proposed", "파일을 수락하셔서 송장을 넣었어요.",
                {"kind": "shipment", "id": f"shipment-order-{order}", "label": f"#{order}"},
                undo=("order", order, previous)))
        view["state"] = "approved"
        view["step"] = self.steps[view["stepId"]]["view"]
        self.add_run("chat", f"송장 파일 {filename}", "done", f"송장 {len(chosen)}건을 등록했어요.", steps)
        return {"registered": len(chosen), "proposal": view, "steps": steps}


class InvoiceHandler(base.Handler):
    def control(self, method, path, query, raw):
        body = json.loads(raw) if raw else {}
        workshop = base.WORKSHOP
        match (method, path):
            case ("POST", "/__stub/fail"):
                workshop.faults.append({"method": body["method"], "path": body["path"], "status": body["status"],
                                        "detail": body["detail"]})
                return {"faults": len(workshop.faults)}
            case ("POST", "/__stub/mend"):
                workshop.faults = []
                return {"faults": 0}
            case ("POST", "/__stub/ship"):
                workshop.set_order(body["order"], "in_transit")
                return {"order": body["order"]}
            case ("POST", "/__stub/finish"):
                return workshop.finish(body["status"])
        answer = super().control(method, path, query, raw)
        if path == "/__stub/state":
            answer["runs"] = [{"id": run["id"], "status": run["status"], "question": run["question"]}
                              for run in workshop.runs]
        return answer

    def route(self, method, path, query, raw):
        workshop = base.WORKSHOP
        workshop.fault(method, path)
        parts = path.strip("/").split("/")
        if method == "POST" and parts[:2] == ["agent", "invoices"] and parts[-1] == "approve":
            if len(parts) != 4:
                raise Refused(404, "Not Found")
            return workshop.approve_file(parts[2], raw, query.get("filename", ""),
                                         self.headers.get("Content-Type", ""), query)
        return super().route(method, path, query, raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=18653)
    port = parser.parse_args().port
    base.WORKSHOP = InvoiceWorkshop()
    server = ThreadingHTTPServer(("127.0.0.1", port), InvoiceHandler)
    print(f"READY http://127.0.0.1:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
