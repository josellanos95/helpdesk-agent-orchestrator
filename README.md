# Helpdesk Agent Orchestrator

Multi-tenant AI agent orchestrator for IT helpdesk support — tool use / function calling, Redis-coordinated session state, idempotent execution, and human-in-the-loop escalation. Built with FastAPI + OpenAI.

🚧 Work in progress. Full README with architecture, demo link, and design decisions coming as the project reaches completion.

## Local development

```bash
docker compose up -d        # Postgres + Redis

cd backend
python -m venv .venv && .venv/Scripts/activate  # or source .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt
uvicorn app.main:app --reload

cd ../frontend
npm install
npm run dev
```
