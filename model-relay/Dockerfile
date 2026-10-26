FROM python:3.12-slim
COPY relay.py /relay.py
# 8000: the API for the sandboxes; 9000: /health and /metrics.
EXPOSE 8000 9000
USER nobody
ENTRYPOINT ["python", "-u", "/relay.py"]
