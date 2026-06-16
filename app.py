import base64
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import jwt
import requests
from dotenv import load_dotenv
from fastapi import (
    Body,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from supabase import create_client

load_dotenv()

HF_API_TOKEN = os.getenv("HF_API_TOKEN", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
JWT_SECRET = os.getenv("JWT_SECRET", "omurama-secret")
API_KEYS = [key.strip() for key in os.getenv("API_KEYS", "demo-key").split(",") if key.strip()]

MODEL_CATALOG = {
    "chat": [
        "mistralai/Mistral-7B-v0.1",
        "meta-llama/Llama-2-7b-chat-hf",
        "tiiuae/falcon-7b-instruct",
    ],
    "vision": [
        "Qwen/Qwen-Visual-1.0",
        "Salesforce/blip-image-captioning-large",
    ],
    "asr": [
        "openai/whisper-small",
    ],
    "tts": [
        "espnet/kan-bayashi_ljspeech_vits",
    ],
}

RATE_LIMIT_WINDOW = 60
RATE_LIMIT_REQUESTS = 120
RATE_LIMIT_STATE: Dict[str, List[float]] = {}

app = FastAPI(title="Omurama AI Cloud Assistant")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory="static"), name="static")

api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)

SUPABASE_CLIENT = None
if SUPABASE_URL and SUPABASE_KEY:
    SUPABASE_CLIENT = create_client(SUPABASE_URL, SUPABASE_KEY)

HF_HEADERS = {
    "Authorization": f"Bearer {HF_API_TOKEN}" if HF_API_TOKEN else "",
    "Accept": "application/json",
}


class ModelManager:
    def __init__(self, catalog: Dict[str, List[str]]):
        self.catalog = catalog
        self.cache: Dict[str, Dict[str, Any]] = {}

    def _build_url(self, model_id: str) -> str:
        return f"https://api-inference.huggingface.co/models/{model_id}"

    def check_model(self, model_id: str) -> bool:
        now = time.time()
        cached = self.cache.get(model_id)
        if cached and now - cached["checked"] < 300:
            return cached["alive"]

        try:
            response = requests.get(self._build_url(model_id), headers=HF_HEADERS, timeout=15)
            alive = response.status_code == 200
        except requests.RequestException:
            alive = False

        self.cache[model_id] = {"checked": now, "alive": alive}
        return alive

    def select(self, category: str, override: Optional[str] = None) -> Optional[str]:
        candidates = []
        if override:
            candidates.append(override)
        candidates.extend(self.catalog.get(category, []))
        for model_id in candidates:
            if self.check_model(model_id):
                return model_id
        return candidates[0] if candidates else None

    def infer(
        self,
        model_id: str,
        payload: Dict[str, Any],
        files: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        url = self._build_url(model_id)
        headers = {k: v for k, v in HF_HEADERS.items() if v}
        if files:
            response = requests.post(url, headers=headers, json=payload, files=files, timeout=120)
        else:
            headers["Content-Type"] = "application/json"
            response = requests.post(url, headers=headers, json=payload, timeout=120)
        return response


MODEL_MANAGER = ModelManager(MODEL_CATALOG)


class SupabaseStore:
    def __init__(self):
        self.client = SUPABASE_CLIENT

    def insert(self, table: str, data: Dict[str, Any]) -> Optional[Any]:
        if not self.client:
            return None
        return self.client.table(table).insert(data).execute().data

    def upload_file(self, bucket: str, path: str, payload: bytes, content_type: str) -> Optional[str]:
        if not self.client:
            return None
        storage = self.client.storage.from_(bucket)
        result = storage.upload(path, payload, content_type=content_type)
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(result["error"])
        public_url = storage.get_public_url(path)
        return public_url


SUPABASE_STORE = SupabaseStore()


def rate_limit(request: Request) -> None:
    key = request.headers.get("x-api-key") or request.client.host
    now = time.time()
    window = RATE_LIMIT_STATE.setdefault(key, [])
    window[:] = [timestamp for timestamp in window if now - timestamp < RATE_LIMIT_WINDOW]
    if len(window) >= RATE_LIMIT_REQUESTS:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    window.append(now)


async def authenticate(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    api_key: Optional[str] = Depends(api_key_header),
) -> Dict[str, Any]:
    if api_key and api_key in API_KEYS:
        return {"type": "api_key", "key": api_key}

    if credentials and credentials.scheme.lower() == "bearer":
        try:
            payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
            return {"type": "jwt", "payload": payload}
        except jwt.PyJWTError:
            raise HTTPException(status_code=401, detail="Invalid JWT token")

    raise HTTPException(status_code=401, detail="Missing authentication")


def format_messages(messages: List[Dict[str, str]]) -> str:
    prompt_lines: List[str] = []
    for message in messages:
        role = message.get("role", "user").lower()
        content = message.get("content", "")
        prefix = "User" if role == "user" else "Assistant"
        prompt_lines.append(f"{prefix}: {content}")
    prompt_lines.append("Assistant:")
    return "\n".join(prompt_lines)


def parse_response(response: requests.Response) -> Any:
    content_type = response.headers.get("Content-Type", "")
    if "application/json" in content_type:
        payload = response.json()
        if isinstance(payload, list) and payload:
            first = payload[0]
            if isinstance(first, dict):
                text = first.get("generated_text") or first.get("text") or first.get("answer")
                return text or payload
        if isinstance(payload, dict):
            if "generated_text" in payload:
                return payload["generated_text"]
            if "text" in payload:
                return payload["text"]
            return payload
    return response.content.decode(errors="ignore")


def save_chat_history(user_id: Optional[str], messages: List[Dict[str, str]], response_text: str, model_id: str) -> None:
    if not SUPABASE_CLIENT:
        return
    SUPABASE_STORE.insert(
        "chat_history",
        {
            "user_id": user_id,
            "model_id": model_id,
            "messages": messages,
            "response": response_text,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    )


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "models": {category: MODEL_MANAGER.select(category) for category in MODEL_CATALOG},
        "supabase": bool(SUPABASE_CLIENT),
    }


@app.get("/chatbot.js")
async def chatbot_js() -> FileResponse:
    return FileResponse(Path("static") / "widget.js", media_type="application/javascript")


@app.get("/widget.css")
async def widget_css() -> FileResponse:
    return FileResponse(Path("static") / "widget.css", media_type="text/css")


@app.get("/")
async def index() -> HTMLResponse:
    html = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Omurama AI Cloud Assistant</title>
  <link rel="stylesheet" href="/widget.css" />
</head>
<body>
  <div class="doc-shell">
    <h1>Omurama AI Cloud Assistant</h1>
    <p>Use this space as a live backend and frontend host for the embeddable AI assistant.</p>
    <h2>Embed Code</h2>
    <pre><code>&lt;script&gt;
window.OMURAMA_CHATBOT_URL = "https://your-huggingface-space-url";
window.OMURAMA_CHATBOT_API_KEY = "YOUR_PUBLIC_API_KEY";
&lt;/script&gt;
&lt;script src="https://your-huggingface-space-url/chatbot.js"&gt;&lt;/script&gt;
</code></pre>
    <h2>API</h2>
    <ul>
      <li>POST /chat</li>
      <li>POST /vision</li>
      <li>POST /voice</li>
      <li>POST /upload</li>
      <li>GET /health</li>
    </ul>
    <p>Read the repository README for deployment and secret setup.</p>
  </div>
</body>
</html>
"""
    return HTMLResponse(html)


@app.post("/chat")
async def chat(
    request: Request,
    auth: Dict[str, Any] = Depends(authenticate),
    _: None = Depends(rate_limit),
) -> JSONResponse:
    body = await request.json()
    messages = body.get("messages") or []
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="messages must be a list")

    model_override = body.get("model")
    model_id = MODEL_MANAGER.select("chat", model_override)
    if not model_id:
        raise HTTPException(status_code=503, detail="No chat model is available")

    prompt = format_messages(messages)
    payload = {"inputs": prompt, "options": {"wait_for_model": True}}
    response = MODEL_MANAGER.infer(model_id, payload)
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    answer = parse_response(response)
    save_chat_history(auth.get("payload", {}).get("sub"), messages, str(answer), model_id)
    return JSONResponse({"model": model_id, "answer": answer})


@app.post("/vision")
async def vision(
    image: UploadFile = File(...),
    question: Optional[str] = Form(None),
    auth: Dict[str, Any] = Depends(authenticate),
    _: None = Depends(rate_limit),
) -> JSONResponse:
    model_id = MODEL_MANAGER.select("vision")
    if not model_id:
        raise HTTPException(status_code=503, detail="No vision model is available")

    image_bytes = await image.read()
    files = {"file": (image.filename, image_bytes, image.content_type)}
    payload = {"inputs": question or "Describe the image and answer any questions."}
    response = MODEL_MANAGER.infer(model_id, payload, files=files)
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    result = parse_response(response)
    if SUPABASE_CLIENT:
        SUPABASE_STORE.insert(
            "files",
            {
                "user_id": auth.get("payload", {}).get("sub"),
                "file_name": image.filename,
                "file_type": image.content_type,
                "purpose": "vision",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
    return JSONResponse({"model": model_id, "result": result})


@app.post("/voice")
async def voice(
    mode: str = Form("transcribe"),
    audio: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    auth: Dict[str, Any] = Depends(authenticate),
    _: None = Depends(rate_limit),
) -> JSONResponse:
    if mode == "transcribe":
        if not audio:
            raise HTTPException(status_code=400, detail="Audio file required for transcription")
        model_id = MODEL_MANAGER.select("asr")
        if not model_id:
            raise HTTPException(status_code=503, detail="No ASR model is available")
        audio_bytes = await audio.read()
        files = {"file": (audio.filename, audio_bytes, audio.content_type)}
        response = MODEL_MANAGER.infer(model_id, {"task": "transcribe"}, files=files)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        transcription = parse_response(response)
        return JSONResponse({"model": model_id, "transcription": transcription})

    if mode == "tts":
        if not text:
            raise HTTPException(status_code=400, detail="Text required for TTS")
        model_id = MODEL_MANAGER.select("tts")
        if not model_id:
            raise HTTPException(status_code=503, detail="No TTS model is available")
        response = MODEL_MANAGER.infer(model_id, {"inputs": text})
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)

        payload = base64.b64encode(response.content).decode()
        content_type = response.headers.get("Content-Type", "audio/wav")
        return JSONResponse({"model": model_id, "audio_base64": payload, "content_type": content_type})

    raise HTTPException(status_code=400, detail="Invalid mode for voice endpoint")


@app.post("/upload")
async def upload(
    file: UploadFile = File(...),
    description: Optional[str] = Form(None),
    auth: Dict[str, Any] = Depends(authenticate),
    _: None = Depends(rate_limit),
) -> JSONResponse:
    file_bytes = await file.read()
    timestamp = int(time.time())
    object_name = f"uploads/{timestamp}-{file.filename}"
    public_url = None
    if SUPABASE_CLIENT:
        try:
            public_url = SUPABASE_STORE.upload_file("uploads", object_name, file_bytes, file.content_type or "application/octet-stream")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Storage upload failed: {exc}")

    record = {
        "user_id": auth.get("payload", {}).get("sub"),
        "file_name": file.filename,
        "content_type": file.content_type,
        "description": description,
        "url": public_url,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if SUPABASE_CLIENT:
        SUPABASE_STORE.insert("files", record)
    return JSONResponse({"uploaded": True, "file": record})


@app.get("/docs-info")
async def docs_info() -> Dict[str, Any]:
    return {
        "widget_script": "/chatbot.js",
        "widget_css": "/widget.css",
    }
