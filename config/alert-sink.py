#!/usr/bin/env python3
"""Tiny webhook receiver for AlertManager. Logs each delivery as one
JSON line on stdout so `docker compose logs alert-sink` is the
operator's view of fired/resolved alerts. See ADR-0009."""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a, **k):
        return

    def do_POST(self):
        n = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(n).decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
            for alert in payload.get("alerts", []):
                line = {
                    "msg": "alertmanager.alert",
                    "status": alert.get("status"),
                    "alertname": alert.get("labels", {}).get("alertname"),
                    "severity": alert.get("labels", {}).get("severity"),
                    "service": alert.get("labels", {}).get("service"),
                    "summary": alert.get("annotations", {}).get("summary"),
                    "runbook_url": alert.get("annotations", {}).get("runbook_url"),
                    "starts_at": alert.get("startsAt"),
                    "ends_at": alert.get("endsAt"),
                }
                print(json.dumps(line), flush=True)
        except Exception as e:
            print(json.dumps({"msg": "alertmanager.parse_error", "error": str(e), "raw": raw}), flush=True)
        self.send_response(204)
        self.end_headers()


if __name__ == "__main__":
    port = 9000
    print(json.dumps({"msg": "alert-sink.boot", "listen": f":{port}"}), flush=True)
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
