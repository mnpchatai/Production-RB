FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir \
      "django>=5.0,<6" "djangorestframework>=3.15" "psycopg[binary]>=3.1" \
      "django-cors-headers>=4.4" "gunicorn>=22" "pytest>=8" "pytest-django>=4.8"

COPY . .
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
