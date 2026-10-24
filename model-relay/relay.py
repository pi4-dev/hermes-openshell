"""OpenAI-compatible relay in front of the real model backend.

The sandbox only knows this relay's address and the model alias. The relay adds the real
API key, swaps the alias for the real model name and strips what identifies the backend
from responses (model names, provider fields, SSE comments).
"""
import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_URL = os.environ["MODEL_BASE_URL"].rstrip("/")
API_KEY = os.environ["MODEL_API_KEY"]
MODEL = os.environ["MODEL_NAME"]
ALIAS = "assistant"  # the model name in hermes/config.yaml
# Only inference calls reach the backend; anything else (probes like /props) gets a neutral 404,
# so backend-specific answers and error pages never reach the sandbox.
FORWARDED_PATHS = {"/v1/chat/completions", "/v1/completions", "/v1/embeddings", "/v1/responses"}
# Request headers passed upstream; client credentials and attribution headers are dropped.
FORWARD_HEADERS = ("content-type", "accept")
PROVIDER_KEYS = {"provider", "provider_name"}


def scrub(value):
    """Replace model names with the alias and drop provider details, recursively."""
    if isinstance(value, dict):
        return {
            key: ALIAS if key == "model" and isinstance(item, str) else scrub(item)
            for key, item in value.items()
            if key not in PROVIDER_KEYS and not (key == "metadata" and "message" in value)
        }
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return value


class Relay(BaseHTTPRequestHandler):
    # One request per connection, so a streamed response simply ends at close.
    protocol_version = "HTTP/1.0"

    def do_GET(self):
        if self.path.split("?")[0].rstrip("/") == "/v1/models":
            model = {"id": ALIAS, "object": "model", "owned_by": "local"}
            self._json(200, {"object": "list", "data": [model]})
        else:
            self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        if self.path.split("?")[0] in FORWARDED_PATHS:
            self._forward()
        else:
            self._json(404, {"error": {"message": "not found"}})

    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _forward(self):
        body = self.rfile.read(int(self.headers.get("content-length") or 0))
        if body and "json" in (self.headers.get("content-type") or ""):
            payload = json.loads(body)
            if isinstance(payload, dict) and "model" in payload:
                payload["model"] = MODEL
                body = json.dumps(payload).encode()
        headers = {name: self.headers[name] for name in FORWARD_HEADERS if self.headers.get(name)}
        headers["Authorization"] = f"Bearer {API_KEY}"
        request = urllib.request.Request(BASE_URL + self.path[len("/v1"):], data=body or None,
                                         headers=headers, method=self.command)
        try:
            upstream = urllib.request.urlopen(request, timeout=600)
        except urllib.error.HTTPError as error:
            upstream = error
        except OSError:
            return self._json(502, {"error": {"message": "model backend unreachable"}})
        with upstream:
            content_type = upstream.headers.get("content-type", "")
            if "text/event-stream" in content_type:
                self.send_response(upstream.getcode())
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                for line in upstream:
                    if line.startswith(b":"):  # SSE comments, e.g. keep-alives naming the backend
                        continue
                    if line.startswith(b"data: {"):
                        try:
                            line = b"data: " + json.dumps(scrub(json.loads(line[6:]))).encode() + b"\n"
                        except ValueError:
                            pass
                    self.wfile.write(line)
                    self.wfile.flush()
                return
            data = upstream.read()
            if "json" in content_type:
                try:
                    data = json.dumps(scrub(json.loads(data))).encode()
                except ValueError:
                    pass
            self.send_response(upstream.getcode())
            self.send_header("Content-Type", content_type or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)


server = ThreadingHTTPServer(("0.0.0.0", 8000), Relay)
server.daemon_threads = True
server.serve_forever()
