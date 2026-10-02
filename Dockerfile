FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    PORTFOLIO_HOST=0.0.0.0 \
    PORT=8000 \
    COOKIE_SECURE=true

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 app

COPY --chown=app:app . .
USER app
EXPOSE 8000
CMD ["python", "app.py"]
