"""
FastAPI + Socket.IO server for NFC Web Manager.
"""
import asyncio
import json
import logging
import os
import socket
import sys
import subprocess
import time
from pathlib import Path
from contextlib import asynccontextmanager

import socketio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel

from nfc_reader import ACR122Reader, hex_to_ascii
from crack_engine import CrackEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("server")

SUDO_PW_FILE = "/home/pi/.nfc_sudo_pw"

SUDO_PW = ""
if os.path.exists(SUDO_PW_FILE):
    with open(SUDO_PW_FILE) as f:
        SUDO_PW = f.read().strip()

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
DUMP_DIR = Path("/tmp/nfc_dumps")
DUMP_DIR.mkdir(parents=True, exist_ok=True)

reader = ACR122Reader()
crack_engine = CrackEngine()
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

@sio.event
async def connect(sid, environ):
    await sio.emit("reader_status", _get_reader_status(), to=sid)

@sio.event
async def disconnect(sid):
    pass

def _get_reader_status() -> dict:
    readers = []
    card_present = False
    try:
        readers = reader.detect_readers()
        if reader.connected:
            atr_data = reader._connection.getATR()
            card_present = atr_data is not None and len(atr_data) > 0
            if card_present and not reader.card_present:
                reader._card_info = {"uid": "present", "atr": "".join(f"{b:02X}" for b in atr_data)}
                reader._card_present = True
            elif not card_present:
                reader._card_present = False
                reader._card_info = {}
    except Exception:
        pass
    return {
        "pyscard_available": reader.is_pyscard_available(),
        "readers": readers,
        "connected": reader.connected,
        "reader_name": reader.reader_name,
        "card_present": reader.card_present,
        "card_info": reader.card_info if reader.card_present else {},
        "firmware": None,
    }

async def _crack_update_callback(update: dict):
    await sio.emit("crack_update", update)

async def _crack_error_callback(error: str):
    await sio.emit("crack_update", {"type": "error", "message": error})

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting NFC Web Manager...")
    if reader.connect(0):
        reader._card_present = True
        try:
            atr = reader._connection.getATR()
            if atr and len(atr) > 0:
                reader._card_present = True
                reader._card_info = {"uid": "present", "atr": "".join(f"{b:02X}" for b in atr)}
        except Exception:
            pass
    else:
        logger.warning("No reader found - check pcscd and USB")
    yield
    logger.info("Shutting down...")
    await crack_engine.stop()
    reader.disconnect()

app = FastAPI(lifespan=lifespan)
sio_app = socketio.ASGIApp(sio, other_asgi_app=app)

@app.get("/api/status")
async def api_status():
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(loop.run_in_executor(None, _get_reader_status), timeout=3.0)
    except asyncio.TimeoutError:
        return {"error": "reader timeout", "readers": []}

@app.get("/api/card/info")
async def api_card_info():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, reader.get_card_info)

class KeyLoadRequest(BaseModel):
    key: str

@app.post("/api/key/load")
async def api_load_key(req: KeyLoadRequest):
    return {"status": "ok"}

def mfoc_dump(output_file="/tmp/mfoc_dump.mfd"):
    if not SUDO_PW:
        return None
    subprocess.run(["sudo", "-S", "systemctl", "stop", "pcscd.service", "pcscd.socket"],
                   input=(SUDO_PW + "\n").encode(), capture_output=True, timeout=10)
    time.sleep(1)
    try:
        res = subprocess.run(["timeout", "120", "mfoc", "-O", output_file],
                             capture_output=True, text=True, timeout=125)
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            with open(output_file, "rb") as f:
                return f.read()
        return None
    finally:
        subprocess.run(["sudo", "-S", "systemctl", "start", "pcscd.service"],
                       input=(SUDO_PW + "\n").encode(), capture_output=True, timeout=10)
        time.sleep(2)
        try:
            reader.disconnect()
            reader.connect(0)
            reader._card_present = True
        except Exception:
            pass

@app.get("/api/dump/download")
async def api_dump_download():
    if not reader.card_present:
        raise HTTPException(400, "No card present")
    loop = asyncio.get_event_loop()
    try:
        data = await asyncio.wait_for(loop.run_in_executor(None, reader.dump_to_bytes), timeout=15.0)
        if data:
            return Response(content=data, media_type="application/octet-stream",
                           headers={"Content-Disposition": "attachment; filename=card_dump.bin"})
    except Exception:
        pass
    data = await loop.run_in_executor(None, mfoc_dump)
    if data is None:
        raise HTTPException(500, "Dump failed")
    return Response(content=data, media_type="application/octet-stream",
                   headers={"Content-Disposition": "attachment; filename=card_dump.bin"})

@app.post("/api/dump/upload_file")
async def api_upload_dump_file(request: Request):
    import uuid
    file_bytes = await request.body()
    if len(file_bytes) == 0:
        raise HTTPException(400, "Empty file")
    fname = f"upload_{uuid.uuid4().hex[:8]}.bin"
    fpath = DUMP_DIR / fname
    fpath.write_bytes(file_bytes)
    return {"status": "ok", "filename": fname, "size": len(file_bytes)}

@app.get("/api/dump/list")
async def api_dump_list():
    files = []
    if DUMP_DIR.exists():
        for f in sorted(DUMP_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.is_file():
                files.append({"name": f.name, "size": f.stat().st_size, "mtime": f.stat().st_mtime})
    return {"files": files}

def _nfc_write_file(dump_path: str):
    if not SUDO_PW:
        return False
    subprocess.run(["sudo", "-S", "systemctl", "stop", "pcscd.service", "pcscd.socket"],
                   input=(SUDO_PW + "\n").encode(), capture_output=True, timeout=10)
    time.sleep(1)
    try:
        cmd = ["nfc-mfclassic", "w", "a", "u", dump_path]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return res.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    finally:
        subprocess.run(["sudo", "-S", "systemctl", "start", "pcscd.service"],
                       input=(SUDO_PW + "\n").encode(), capture_output=True, timeout=10)
        time.sleep(2)
        try:
            reader.disconnect()
            reader.connect(0)
            reader._card_present = True
        except Exception:
            pass

@app.post("/api/dump/upload")
async def api_dump_upload(filename: str):
    filepath = DUMP_DIR / filename
    if not filepath.exists() or not filepath.is_file():
        raise HTTPException(404, f"Dump not found: {filename}")
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, lambda: _nfc_write_file(str(filepath)))
    if ok:
        return {"status": "ok", "message": "写入成功"}
    raise HTTPException(500, "写入失败 - 请确认目标卡已放好")

@app.post("/api/crack/mfoc")
async def api_crack_mfoc(keys: list[str] = []):
    if crack_engine.running:
        raise HTTPException(400, "Already running")
    out_file = str(DUMP_DIR / "mfoc_result.mfd")
    ok = await crack_engine.start_mfoc(output_file=out_file, known_keys=keys or None,
                                        on_update=_crack_update_callback, on_error=_crack_error_callback)
    if ok:
        return {"status": "started", "tool": "mfoc"}
    raise HTTPException(500, "Failed to start mfoc")

@app.post("/api/crack/mfcuk")
async def api_crack_mfcuk(sector: int = 0, key_type: str = "A", known_key: str = ""):
    if crack_engine.running:
        raise HTTPException(400, "Already running")
    ok = await crack_engine.start_mfcuk(target_sector=sector, key_type=key_type,
                                         known_key=known_key or None, timeout=300,
                                         on_update=_crack_update_callback, on_error=_crack_error_callback)
    if ok:
        return {"status": "started", "tool": "mfcuk"}
    raise HTTPException(500, "Failed to start mfcuk")

@app.post("/api/crack/stop")
async def api_crack_stop():
    await crack_engine.stop()
    return {"status": "stopped"}

@app.get("/api/crack/status")
async def api_crack_status():
    return {"running": crack_engine.running, "state": crack_engine.state,
            "log": crack_engine.stdout_log[-200:]}

@app.get("/")
async def index():
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Frontend not found</h1>", status_code=404)

def main():
    import uvicorn
    host = "0.0.0.0"
    port = int(os.environ.get("NFC_PORT", "8000"))
    print(f"NFC Web Manager on http://{get_local_ip()}:{port}")
    uvicorn.run(sio_app, host=host, port=port, log_level="info")

if __name__ == "__main__":
    main()
