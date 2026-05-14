FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN echo "=== Build timestamp: $(date) ===" && ls -la /app/templates/ && ls -la /app/static/

EXPOSE 5000

CMD gunicorn app:app --bind 0.0.0.0:${PORT:-5000} --workers 2 --timeout 120
