#!/usr/bin/env python3
"""Mock Google Workspace MCP for local testing"""

from fastapi import FastAPI
import os

app = FastAPI(title="Google Workspace MCP (Test)")

@app.get("/health")
async def health():
    return {"status": "ok", "service": "google-workspace-mcp-test"}

@app.get("/")
async def root():
    return {
        "service": "Google Workspace MCP",
        "version": "1.0.0-test",
        "tools_available": [
            "docs", "sheets", "slides", "drive", "gmail", "calendar"
        ],
        "note": "Mock server - full version requires OAuth setup"
    }

@app.post("/docs")
async def list_docs():
    return {
        "success": False,
        "message": "Requires GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET",
        "error": "Not configured for mock testing"
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("MCP_HTTP_PORT", "8000"))
    host = os.getenv("MCP_HOST", "0.0.0.0")
    print(f"Starting Google Workspace MCP (mock) on {host}:{port}")
    uvicorn.run(app, host=host, port=port)
