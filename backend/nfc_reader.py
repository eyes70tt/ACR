"""
ACR122U NFC Reader module for pyscard interaction.
"""
import asyncio
import logging
from typing import Optional, Callable

logger = logging.getLogger(__name__)

try:
    from smartcard.System import readers as get_readers
    from smartcard.util import toHexString
    HAS_PYSCARD = True
except ImportError:
    HAS_PYSCARD = False

APDU_GET_FIRMWARE = [0xFF, 0x00, 0x48, 0x00, 0x00]
APDU_GET_UID = [0xFF, 0xCA, 0x00, 0x00, 0x00]

def _hex_str_to_bytes(hex_str: str) -> list:
    cleaned = hex_str.replace(":", "").replace(" ", "").replace("-", "")
    return [int(cleaned[i:i+2], 16) for i in range(0, len(cleaned), 2)]

class ACR122Reader:
    def __init__(self):
        self._connection = None
        self._reader_name = None
        self._card_info = {}
        self._card_present = False
        self._poll_task = None
        self._on_card_event = None

    def detect_readers(self) -> list:
        if not HAS_PYSCARD:
            return []
        try:
            return [str(r) for r in get_readers()]
        except Exception as e:
            logger.warning("detect_readers failed: %s", e)
            return []

    def is_pyscard_available(self) -> bool:
        return HAS_PYSCARD

    def connect(self, reader_index: int = 0) -> bool:
        if not HAS_PYSCARD:
            return False
        try:
            all_readers = get_readers()
            if reader_index >= len(all_readers):
                return False
            reader = all_readers[reader_index]
            self._connection = reader.createConnection()
            self._connection.connect()
            self._reader_name = str(reader)
            return True
        except Exception as e:
            logger.error("connect failed: %s", e)
            self._connection = None
            return False

    def disconnect(self):
        if self._connection:
            try:
                self._connection.disconnect()
            except Exception:
                pass
        self._connection = None
        self._reader_name = None
        self._card_present = False
        self._card_info = {}

    @property
    def connected(self) -> bool:
        return self._connection is not None
    @property
    def reader_name(self) -> Optional[str]:
        return self._reader_name
    @property
    def card_present(self) -> bool:
        return self._card_present
    @property
    def card_info(self) -> dict:
        return self._card_info

    def _transmit(self, apdu: list) -> tuple:
        if not self._connection:
            raise RuntimeError("Not connected")
        data, sw1, sw2 = self._connection.transmit(apdu)
        return data, sw1, sw2

    def get_firmware(self) -> Optional[str]:
        try:
            data, sw1, sw2 = self._transmit(APDU_GET_FIRMWARE)
            if sw1 == 0x90 and sw2 == 0x00:
                return toHexString(data).replace(" ", "")
        except Exception:
            pass
        return None

    def read_card_uid(self) -> Optional[str]:
        try:
            data, sw1, sw2 = self._transmit(APDU_GET_UID)
            if sw1 == 0x90 and sw2 == 0x00:
                return toHexString(data).replace(" ", "")
        except Exception:
            pass
        return None

    def get_card_info(self) -> dict:
        uid = self.read_card_uid()
        if uid:
            self._card_present = True
            self._card_info = {"uid": uid, "card_type": "MIFARE Classic 1K", "sectors": 16}
        else:
            self._card_present = False
            self._card_info = {}
        return self._card_info

    def dump_to_bytes(self) -> Optional[bytes]:
        return None

    async def start_card_polling(self, callback: Callable, interval: float = 0.5):
        self._on_card_event = callback
        async def _poll():
            prev_uid = None
            loop = asyncio.get_event_loop()
            while True:
                try:
                    uid = await loop.run_in_executor(None, self.read_card_uid)
                    if uid and uid != prev_uid:
                        info = {"uid": uid, "event": "card_arrived"}
                        if self._on_card_event:
                            self._on_card_event(info)
                        prev_uid = uid
                        self._card_present = True
                    elif not uid and prev_uid is not None:
                        self._card_present = False
                        self._card_info = {}
                        if self._on_card_event:
                            self._on_card_event({"event": "card_removed"})
                        prev_uid = None
                except Exception:
                    if prev_uid is not None:
                        self._card_present = False
                        if self._on_card_event:
                            self._on_card_event({"event": "card_removed"})
                        prev_uid = None
                await asyncio.sleep(interval)
        self._poll_task = asyncio.create_task(_poll())

    async def stop_card_polling(self):
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

def hex_to_ascii(hex_str: str) -> str:
    parts = hex_str.replace("-", ":").split(":")
    chars = []
    for p in parts:
        try:
            b = int(p, 16)
            chars.append(chr(b) if 32 <= b < 127 else ".")
        except ValueError:
            chars.append(".")
    return "".join(chars)
