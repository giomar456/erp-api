FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

WORKDIR /app

COPY requirements-api.txt /app/requirements-api.txt
RUN pip install --no-cache-dir -r requirements-api.txt

COPY api.py /app/api.py
COPY plataform_sunat_client.py /app/plataform_sunat_client.py
COPY plataform_sunat_server.py /app/plataform_sunat_server.py
COPY plataform_sunat_panel.html /app/plataform_sunat_panel.html
COPY webapp /app/webapp

EXPOSE 8000

CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --timeout-keep-alive 65 --limit-concurrency 40 --limit-max-requests 800"]
