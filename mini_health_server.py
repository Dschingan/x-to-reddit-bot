from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
import uvicorn
import os

app = FastAPI(title="Mini Health Server")

@app.get("/", response_class=PlainTextResponse)
def root():
    return "OK"

@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
