"""OpenAI-compatible relay in front of the real model backend.

The sandbox only knows this relay's address and the model alias. The relay adds the real
API key, swaps the alias for the real model name and strips what identifies the backend
from responses (model names, provider fields, SSE comments, non-JSON error pages). It names
no server software, and everything outside the API gets the same empty 404.

/health and /metrics (Prometheus) are served on a separate port that the sandboxes cannot
reach (OPS_PORT, published on the host's loopback in docker-compose.yml).
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_URL = os.environ["MODEL_BASE_URL"].rstrip("/")
API_KEY = os.environ["MODEL_API_KEY"]
MODEL = os.environ["MODEL_NAME"]
ALIAS = "assistant"  # the model name in hermes/config.yaml
API_PORT, OPS_PORT = 8000, 9000
# Only inference calls reach the backend; anything else (probes like /props) gets the empty 404,
# so backend-specific answers and error pages never reach the sandbox.
FORWARDED_PATHS = {"/v1/chat/completions", "/v1/completions", "/v1/embeddings", "/v1/responses"}
# Request headers passed upstream; client credentials and attribution headers are dropped.
FORWARD_HEADERS = ("content-type", "accept")
PROVIDER_KEYS = {"provider", "provider_name"}
DURATION_BUCKETS = (0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600)


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


def usage_of(payload):
    """Token usage of a response or stream event: chat/completions/embeddings or Responses API."""
    if not isinstance(payload, dict):
        return None
    usage = payload.get("usage")
    if not isinstance(usage, dict) and isinstance(payload.get("response"), dict):
        usage = payload["response"].get("usage")
    return usage if isinstance(usage, dict) else None


class Histogram:
    def __init__(self):
        self.buckets, self.sum, self.count = [0] * len(DURATION_BUCKETS), 0.0, 0

    def observe(self, value):
        for i, bound in enumerate(DURATION_BUCKETS):
            if value <= bound:
                self.buckets[i] += 1
        self.sum += value
        self.count += 1


class Metrics:
    """Counters for /metrics, in the Prometheus text format. Labels carry no model or backend names."""

    def __init__(self):
        self.lock = threading.Lock()
        self.started = time.time()
        self.requests = {}  # (path, code) -> count
        self.duration = {}  # path -> Histogram, whole forwarded request including the stream
        self.first_byte = {}  # path -> Histogram, until the backend's response headers
        self.tokens = {"input": 0, "output": 0}
        self.in_flight = 0

    def request(self, path, code):
        with self.lock:
            self.requests[path, code] = self.requests.get((path, code), 0) + 1

    def observe(self, histograms, path, seconds):
        with self.lock:
            histograms.setdefault(path, Histogram()).observe(seconds)

    def count_tokens(self, usage):
        if not usage:
            return
        counts = {"input": usage.get("prompt_tokens", usage.get("input_tokens")),
                  "output": usage.get("completion_tokens", usage.get("output_tokens"))}
        with self.lock:
            for kind, value in counts.items():
                if isinstance(value, int):
                    self.tokens[kind] += value

    @contextmanager
    def forwarding(self):
        with self.lock:
            self.in_flight += 1
        try:
            yield
        finally:
            with self.lock:
                self.in_flight -= 1

    def render(self):
        def histogram(name, help_text, histograms):
            out = [f"# HELP {name} {help_text}", f"# TYPE {name} histogram"]
            for path, h in sorted(histograms.items()):
                for bound, count in zip(DURATION_BUCKETS, h.buckets):
                    out.append(f'{name}_bucket{{path="{path}",le="{float(bound)}"}} {count}')
                out += [f'{name}_bucket{{path="{path}",le="+Inf"}} {h.count}',
                        f'{name}_sum{{path="{path}"}} {h.sum}', f'{name}_count{{path="{path}"}} {h.count}']
            return out

        with self.lock:
            lines = ["# HELP model_relay_requests_total Requests from the agents, by API path and response status.",
                     "# TYPE model_relay_requests_total counter"]
            lines += [f'model_relay_requests_total{{path="{path}",code="{code}"}} {count}'
                      for (path, code), count in sorted(self.requests.items())]
            lines += histogram("model_relay_request_duration_seconds",
                               "Duration of forwarded requests, streamed responses included.", self.duration)
            lines += histogram("model_relay_time_to_first_byte_seconds",
                               "Time until the model backend's response headers.", self.first_byte)
            lines += ["# HELP model_relay_tokens_total Tokens reported by the model backend.",
                      "# TYPE model_relay_tokens_total counter"]
            lines += [f'model_relay_tokens_total{{type="{kind}"}} {count}' for kind, count in self.tokens.items()]
            lines += ["# HELP model_relay_in_flight_requests Forwarded requests in progress.",
                      "# TYPE model_relay_in_flight_requests gauge", f"model_relay_in_flight_requests {self.in_flight}",
                      "# HELP process_start_time_seconds Start time of the relay since the Unix epoch.",
                      "# TYPE process_start_time_seconds gauge", f"process_start_time_seconds {self.started}"]
        return "\n".join(lines) + "\n"


METRICS = Metrics()


class Handler(BaseHTTPRequestHandler):
    # One request per connection, so a streamed response simply ends at close.
    protocol_version = "HTTP/1.0"
    status = None

    def send_response(self, code, message=None):
        # Like the base class, minus the Server header that names Python's http.server.
        self.status = code
        self.log_request(code)
        self.send_response_only(code, message)
        self.send_header("Date", self.date_time_string())

    def send_error(self, code, message=None, explain=None):
        # No HTML error page; an unknown method (501) gets the same 404 as an unknown path.
        self.send_response(404 if code == 501 else code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_body(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Relay(Handler):
    route = "other"  # metrics label: the API path that handled the request

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True  # the agent hung up; leaving closes the backend connection too
        finally:
            if self.status is not None:
                METRICS.request(self.route, self.status)
            self.status, self.route = None, "other"

    def do_GET(self):
        if self.path.split("?")[0].rstrip("/") == "/v1/models":
            self.route = "/v1/models"
            model = {"id": ALIAS, "object": "model", "owned_by": "local"}
            self.send_body(200, "application/json", json.dumps({"object": "list", "data": [model]}).encode())
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path.split("?")[0] in FORWARDED_PATHS:
            self.route = self.path.split("?")[0]
            with METRICS.forwarding():
                self._forward(self.route, time.monotonic())
        else:
            self.send_error(404)

    def _forward(self, path, started):
        body = self.rfile.read(int(self.headers.get("content-length") or 0))
        if body and "json" in (self.headers.get("content-type") or ""):
            try:
                payload = json.loads(body)
            except ValueError:
                return self.send_error(400)
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
            return self.send_body(502, "application/json", b'{"error": {"message": "model backend unreachable"}}')
        METRICS.observe(METRICS.first_byte, path, time.monotonic() - started)
        try:
            with upstream:
                self._relay_response(upstream)
        finally:
            METRICS.observe(METRICS.duration, path, time.monotonic() - started)

    def _relay_response(self, upstream):
        status, content_type = upstream.getcode(), upstream.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            self.send_response(status)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            usage = None
            try:
                for line in upstream:
                    if line.startswith(b":"):  # SSE comments, e.g. keep-alives naming the backend
                        continue
                    if line.startswith(b"data: {"):
                        try:
                            event = json.loads(line[6:])
                        except ValueError:
                            pass
                        else:
                            # Some backends repeat cumulative usage in every chunk: keep the last one.
                            usage = usage_of(event) or usage
                            line = b"data: " + json.dumps(scrub(event)).encode() + b"\n"
                    self.wfile.write(line)
                    self.wfile.flush()
            finally:
                METRICS.count_tokens(usage)
            return
        data = upstream.read()
        try:
            payload = json.loads(data) if "json" in content_type else None
        except ValueError:
            payload = None
        if payload is not None:
            METRICS.count_tokens(usage_of(payload))
            data, content_type = json.dumps(scrub(payload)).encode(), "application/json"
        elif status >= 400:  # an error page could name the backend or its proxy
            data, content_type = b'{"error": {"message": "model backend error"}}', "application/json"
        self.send_body(status, content_type or "application/octet-stream", data)


class Ops(Handler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            self.send_body(200, "application/json", b'{"status": "ok"}')
        elif path == "/metrics":
            self.send_body(200, "text/plain; version=0.0.4; charset=utf-8", METRICS.render().encode())
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        pass  # healthchecks and scrapes would flood the log


ops = ThreadingHTTPServer(("0.0.0.0", OPS_PORT), Ops)
api = ThreadingHTTPServer(("0.0.0.0", API_PORT), Relay)
ops.daemon_threads = api.daemon_threads = True
threading.Thread(target=ops.serve_forever, daemon=True).start()
api.serve_forever()
