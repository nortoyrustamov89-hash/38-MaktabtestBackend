# 38-MaktabtestBackend

Gemini API backend for the 38-Maktab Informatika olimpiada quiz.

## Render deploy

This repository includes a Render Blueprint. In Render, create a Blueprint from this repository and provide the `GEMINI_API_KEY` secret when prompted. The blueprint deploys the Python API and exposes `/health` for health checks.

Environment variables:

- `GEMINI_API_KEY` — Gemini API key; store it only as a Render secret.
- `GEMINI_MODEL` — model ID (default: `gemini-3.8-flash`).
- `ALLOWED_ORIGINS` — exact frontend origins, comma-separated. The default Render frontend origin is configured in `render.yaml`.

The API endpoint is `POST /api/questions` with JSON body `{"grade":"9"}`, `{"grade":"10"}`, or `{"grade":"11"}`. The API returns 30 validated questions, answer keys, and explanations.

## Local run

Set `GEMINI_API_KEY` in the process environment (or a private, untracked `.env` file), then run `python backend.py`. The default local address is `http://127.0.0.1:8000`; health check: `/health`.

Never commit API keys to this repository.
