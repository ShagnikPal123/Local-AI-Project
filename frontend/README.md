# Nyx Pulse frontend

This React/Vite application preserves the Nyx Pulse workspace layout from the
Stitch export while remaining independent of the Python backend. It sends
future requests only to `/api/health` and `/api/chat`; it does not contain API
keys or call a cloud provider from the browser.

## Run locally

```powershell
cd frontend/nyx-pulse
npm install
npm run dev
```

The Vite development server proxies `/api` requests to `http://127.0.0.1:8000`.
The FastAPI package will be connected later.
