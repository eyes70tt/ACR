"""
Cracking engine - manages mfoc/mfcuk subprocesses with real-time output parsing.
"""
import asyncio
import logging
import re
import os
from typing import Optional, Callable

logger = logging.getLogger(__name__)

def _find_tool(name: str) -> Optional[str]:
    for d in ["/usr/local/bin", "/usr/bin", "/usr/local/sbin", "/usr/sbin"]:
        p = os.path.join(d, name)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    import shutil
    return shutil.which(name)

_SECTOR_FOUND_RE = re.compile(r"Sector\s+(\d+)\s*-\s*Key\s+([AB])\s+Found\s*\[?([0-9A-Fa-f:]+)\]?")
_SECTOR_NOT_FOUND_RE = re.compile(r"Sector\s+(\d+)\s*-\s*(Key\s+[AB]\s+not\s+found)")
_FOUND_SUMMARY_RE = re.compile(r"Found\s+(\d+)\s+sectors?\s+out\s+of\s+(\d+)")
_UID_RE = re.compile(r"UID[:\s]*([0-9A-Fa-f:]+)")
_CARD_TYPE_RE = re.compile(r"(Mifare\s+\w+)")

def parse_mfoc_line(line: str, state: dict) -> Optional[dict]:
    line_s = line.strip()
    m = _UID_RE.search(line_s)
    if m:
        state["uid"] = m.group(1).strip().rstrip(":")
        return {"type": "card_info", "uid": state["uid"]}
    m = _CARD_TYPE_RE.search(line_s)
    if m:
        state["card_type"] = m.group(1)
        return {"type": "card_info", "card_type": state["card_type"]}
    m = _SECTOR_FOUND_RE.search(line_s)
    if m:
        sector = int(m.group(1))
        key_type = m.group(2)
        key_val = m.group(3).strip().rstrip("]").lstrip("[").strip()
        if sector not in state["sectors"]:
            state["sectors"][sector] = {}
        state["sectors"][sector][f"key_{key_type.lower()}"] = key_val
        state["sectors"][sector]["found"] = True
        return {"type": "sector_found", "sector": sector, "key_type": key_type, "key": key_val}
    m = _SECTOR_NOT_FOUND_RE.search(line_s)
    if m:
        sector = int(m.group(1))
        if sector not in state["sectors"]:
            state["sectors"][sector] = {}
        state["sectors"][sector]["found"] = False
        return {"type": "sector_not_found", "sector": sector}
    m = _FOUND_SUMMARY_RE.search(line_s)
    if m:
        found = int(m.group(1))
        total = int(m.group(2))
        state["found_count"] = found
        state["total_sectors"] = total
        return {"type": "summary", "found": found, "total": total}
    if line_s:
        return {"type": "info", "message": line_s}
    return None

_MFCUK_KEY_FOUND_RE = re.compile(r"\|\s*x\s*\|\s*sector\s+(\d+)\s+key\s+([AB])\s+found")
_MFCUK_KEY_NOT_FOUND_RE = re.compile(r"\|\s*o\s*\|\s*sector\s+(\d+)\s+key\s+([AB])\s+not\s+found")
_MFCUK_ATTACK_RE = re.compile(r"Running\s+(\w+)\s+attack")

def parse_mfcuk_line(line: str, state: dict) -> Optional[dict]:
    line_s = line.strip()
    m = _MFCUK_ATTACK_RE.search(line_s)
    if m:
        state["attack_type"] = m.group(1)
        return {"type": "attack_start", "attack": state["attack_type"]}
    m = _MFCUK_KEY_FOUND_RE.search(line_s)
    if m:
        sector = int(m.group(1))
        key_type = m.group(2)
        state["sectors"][sector] = state["sectors"].get(sector, {})
        state["sectors"][sector][f"key_{key_type.lower()}"] = None
        state["sectors"][sector]["found"] = True
        return {"type": "sector_found", "sector": sector, "key_type": key_type}
    m = _MFCUK_KEY_NOT_FOUND_RE.search(line_s)
    if m:
        sector = int(m.group(1))
        state["attempts"] = state.get("attempts", 0) + 1
        return {"type": "attempt", "sector": sector, "key_type": key_type, "count": state["attempts"]}
    if line_s:
        return {"type": "info", "message": line_s}
    return None

class CrackEngine:
    def __init__(self):
        self._process: Optional[asyncio.subprocess.Process] = None
        self._task: Optional[asyncio.Task] = None
        self._state: dict = {}
        self._on_update: Optional[Callable] = None
        self._on_error: Optional[Callable] = None
        self._stdout_buffer: list[str] = []

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def state(self) -> dict:
        return self._state

    @property
    def stdout_log(self) -> list:
        return list(self._stdout_buffer)

    async def start_mfoc(self, output_file="/tmp/mfoc_dump.mfd", known_keys=None,
                         on_update=None, on_error=None) -> bool:
        tool = _find_tool("mfoc")
        if not tool:
            return False
        self._on_update = on_update
        self._on_error = on_error
        self._state = {"tool": "mfoc", "sectors": {}, "found_count": 0, "total_sectors": 16}
        self._stdout_buffer = []
        args = [tool, "-O", output_file]
        if known_keys:
            for key in known_keys:
                cleaned = key.replace(":", "").replace(" ", "")
                if len(cleaned) == 12:
                    args.extend(["-k", cleaned])
        return await self._start_process(args)

    async def start_mfcuk(self, target_sector=0, key_type="A", known_key=None,
                          timeout=300, on_update=None, on_error=None) -> bool:
        tool = _find_tool("mfcuk")
        if not tool:
            return False
        self._on_update = on_update
        self._on_error = on_error
        self._state = {"tool": "mfcuk", "sectors": {}, "attempts": 0, "attack_type": None}
        self._stdout_buffer = []
        args = [tool, "-C", "-R", f"{target_sector}:{key_type.upper()}"]
        if known_key:
            args.extend(["-k", known_key.replace(":", "").replace(" ", "")])
        return await self._start_process(args, timeout)

    async def _start_process(self, args: list, timeout: int = 0) -> bool:
        logger.info("Starting: %s", " ".join(args))
        try:
            self._process = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        except FileNotFoundError:
            return False
        self._task = asyncio.create_task(self._read_output(self._process, timeout))
        return True

    async def _read_output(self, proc, timeout):
        parser = parse_mfoc_line if self._state.get("tool") == "mfoc" else parse_mfcuk_line
        try:
            async with asyncio.timeout(timeout if timeout > 0 else None):
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    decoded = line.decode("utf-8", errors="replace").rstrip("\n\r")
                    self._stdout_buffer.append(decoded)
                    if len(self._stdout_buffer) > 5000:
                        self._stdout_buffer = self._stdout_buffer[-5000:]
                    update = parser(decoded, self._state)
                    if update and self._on_update:
                        try:
                            self._on_update(update)
                        except Exception:
                            pass
            await proc.wait()
        except asyncio.TimeoutError:
            if self._on_error:
                self._on_error("timeout")
        except Exception as e:
            if self._on_error:
                self._on_error(str(e))
        finally:
            if proc.returncode is None:
                try:
                    proc.kill()
                    await proc.wait()
                except ProcessLookupError:
                    pass

    async def stop(self):
        if self._process and self._process.returncode is None:
            try:
                self._process.kill()
                await self._process.wait()
            except ProcessLookupError:
                pass
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._process = None
