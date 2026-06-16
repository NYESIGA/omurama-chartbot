sdk: docker
app_file: app.py

# OMURAMA AI CLOUD ASSISTANT

A fully cloud-hosted multimodal AI chatbot platform built for GitHub and Hugging Face Spaces.

## Features

- Public FastAPI backend with CORS enabled
- Chat, vision, voice, upload, and health endpoints
- Hugging Face Inference API integration for open models
- Supabase PostgreSQL + Storage support for user data and files
- Embeddable widget via a single script
- Docker deployment for Hugging Face Spaces
- GitHub Actions CI + optional HF deploy

## Deployment

1. Create a GitHub repository and push this code.
2. Create a Hugging Face Space with `sdk: docker` and link it to the repo.
3. Configure secrets in GitHub:
   - `HF_API_TOKEN`
   - `HF_SPACE_NAME`
   - `SUPABASE_URL`
   - `SUPABASE_KEY`
   - `JWT_SECRET`
   - `API_KEYS`
4. Configure Hugging Face Space secrets too (HF Spaces settings):
   - `HF_API_TOKEN`
   - `SUPABASE_URL`
   - `SUPABASE_KEY`
   - `JWT_SECRET`
   - `API_KEYS`

## Environment Variables

- `HF_API_TOKEN` – Hugging Face Inference API token
- `SUPABASE_URL` – Supabase project URL
- `SUPABASE_KEY` – Supabase service role or anon key
- `JWT_SECRET` – secret used to sign JWTs
- `API_KEYS` – comma-separated allowed API keys

## How to connect a website

Add this to any HTML page:

```html
<script>
window.OMURAMA_CHATBOT_URL = "https://your-hf-space-url";
window.OMURAMA_CHATBOT_API_KEY = "YOUR_PUBLIC_API_KEY";
</script>
<script src="https://your-hf-space-url/chatbot.js"></script>
```

The widget loads automatically and connects to the deployed assistant.

## API Endpoints

- `POST /chat`
- `POST /vision`
- `POST /voice`
- `POST /upload`
- `GET /health`

## Notes

This project is built for free cloud-hosted AI using Hugging Face and Supabase. Secrets are never stored in code.
