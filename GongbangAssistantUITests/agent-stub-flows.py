#!/usr/bin/env python3
"""agent-stub.py plus the controls AgentFlowsUITests needs; the scripted workshop itself is unchanged.

Added controls, all POST:
/__stub/drop {"drop": bool}      every app request is cut off without an answer, as with no connection
/__stub/lose                     the next /agent/run is carried out, then its answer is cut off
/__stub/expire {"id": ...}       the server's clock passes a proposal's time; the app was not told
/__stub/raise {"seconds": n}     a proposal to mark order 1042 packed, open for n seconds

Run: python3 agent-stub-flows.py --port 18672
"""

import argparse
import importlib.util
import json
import socket
import sys
from datetime import timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

# The folder is synchronized into the test target, so no __pycache__ may appear in it.
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("agent_stub", Path(__file__).with_name("agent-stub.py"))
stub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stub)


class Link:
    dropped = False
    loses_next_run = False


class Handler(stub.Handler):
    def cut(self):
        self.close_connection = True
        self.connection.shutdown(socket.SHUT_RDWR)

    def handle_request(self, method):
        path = urlsplit(self.path).path
        if not Link.dropped or path.startswith("/__stub/"):
            return super().handle_request(method)
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        with stub.LOCK:
            stub.WORKSHOP.log.append({"method": method, "path": path, "query": {}, "bytes": len(raw)})
            stub.ARRIVED.notify_all()
        self.cut()

    def reply(self, status, payload):
        if Link.loses_next_run and self.command == "POST" and urlsplit(self.path).path == "/agent/run":
            Link.loses_next_run = False
            return self.cut()
        super().reply(status, payload)

    def control(self, method, path, query, raw):
        body = json.loads(raw) if raw else {}
        match (method, path):
            case ("POST", "/__stub/reset"):
                Link.dropped = False
                Link.loses_next_run = False
            case ("POST", "/__stub/drop"):
                Link.dropped = body["drop"]
                return {"dropped": Link.dropped}
            case ("POST", "/__stub/lose"):
                Link.loses_next_run = True
                return {"ok": True}
            case ("POST", "/__stub/expire"):
                stub.WORKSHOP.proposals[body["id"]]["expires"] = stub.now() - timedelta(seconds=1)
                return {"ok": True}
            case ("POST", "/__stub/raise"):
                order = stub.WORKSHOP.orders[1042]
                stub.WORKSHOP.add_proposal(
                    "mark_packed", "주문 1042를 포장 완료로 바꿀까요?", "오늘 수거인데 아직 포장 대기예요.",
                    [("주문", f"#1042 {order['title']}"), ("받는 분", f"{order['customer']} 님")], ["사장님 승인"],
                    stub.WORKSHOP.order_target(1042), timedelta(seconds=body["seconds"]),
                    ("order", 1042, "invoice_pending"), revision=order["revision"])
                return list(stub.WORKSHOP.proposals.values())[-1]["view"]
        return super().control(method, path, query, raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=18672)
    port = parser.parse_args().port
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"READY http://127.0.0.1:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
