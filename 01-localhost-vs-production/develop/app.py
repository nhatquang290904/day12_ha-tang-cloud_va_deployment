"""
Basic AI agent example for local development.

This version is intentionally simple, but it is adjusted so it can also run
behind a tunnel or a basic cloud service by reading PORT from the environment.
"""
import os
import sys
from typing import Optional

from fastapi import Body, FastAPI, HTTPException, Query
import uvicorn

from utils.mock_llm import ask

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

app = FastAPI(title="My Agent")

OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"
DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"

DEBUG = True
MAX_TOKENS = 500


@app.get("/")
def home():
    return {"message": "Hello! Agent is running on my machine :)"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ask")
def ask_agent(
    question: Optional[str] = Query(default=None),
    body: Optional[dict] = Body(default=None),
):
    question = question or (body or {}).get("question")
    if not question:
        raise HTTPException(
            status_code=400,
            detail="Missing question. Use ?question=... or JSON body {'question': '...'}",
        )

    print(f"[DEBUG] Got question: {question}")
    print(f"[DEBUG] Using key: {OPENAI_API_KEY}")

    response = ask(question)

    print(f"[DEBUG] Response: {response}")
    return {"answer": response}


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("DEBUG", "true").lower() == "true"
    print(f"Starting agent on 0.0.0.0:{port}...")
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=reload)
