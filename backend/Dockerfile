FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY alembic.ini .
COPY migrations ./migrations

# Idempotent: safe to run on every deploy. Migrations apply schema + RLS
# policies; seeding only inserts demo tenants that don't already exist.
CMD ["sh", "-c", "alembic upgrade head && python -m scripts.seed_demo_data && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
