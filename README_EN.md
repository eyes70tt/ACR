# NFC Web Manager

A web-based NFC/RFID read/write and cracking management system running on **Raspberry Pi**.

## Features

- **Real-time card detection**: WebSocket-based instant notification when card is placed/removed
- **UID reading**: Read card UID, type (S50/S70), capacity, ATQA/SAK
- **Full card backup**: One-click dump download as `.bin` file
- **Import & write**: Upload a dump file and write to a blank card
- **Sector read/write**: Authenticate and read/write individual data blocks
- **Key recovery**: Nested attack (mfoc) and Darkside attack (mfcuk)
- **Real-time progress**: Crack progress streamed to frontend sector grid via WebSocket

## Hardware Requirements

| Device | Description |
|--------|-------------|
| Raspberry Pi (3B+/4B/5) | Running Debian / Raspberry Pi OS (arm64) |
| ACR122U | ACS or compatible PN532-based reader |

> **Note**: Some ACR122U clone readers may not support MIFARE Classic authentication (returning 0x63 0x00). A genuine ACR122U or ACR1252U is recommended for full functionality.

## Quick Start

```bash
git clone https://github.com/eyes70tt/ACR.git
cd ACR
sudo bash bootstrap.sh
```

Then visit `http://<raspberry-pi-ip>:8000` in your browser.

## Manual Installation

1. Install system dependencies

```bash
sudo apt-get install -y pcscd pcsc-tools libpcsclite-dev python3 python3-pip python3-venv
sudo apt-get install -y libnfc-bin libnfc-dev autoconf automake libtool pkg-config
```

2. Blacklist kernel NFC drivers (avoid conflict with ACR122U)

```bash
echo -e "blacklist nfc\nblacklist pn533\nblacklist pn533_usb" | sudo tee /etc/modprobe.d/blacklist-libnfc.conf
```

3. Create Python virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn[standard] python-socketio pyscard pydantic
```

4. Configure sudo password (needed to stop/start pcscd for mfoc access)

```bash
echo -n "YOUR_SUDO_PASSWORD" > ~/.nfc_sudo_pw
chmod 600 ~/.nfc_sudo_pw
```

5. Start the service

```bash
bash start.sh
```

Open `http://<raspberry-pi-ip>:8000` in your browser.

## Project Structure

```
nfc-web-manager/
├── backend/
│   ├── server.py         # FastAPI + Socket.IO backend
│   ├── nfc_reader.py     # pyscard reader interaction
│   └── crack_engine.py   # mfoc/mfcuk subprocess manager
├── frontend/
│   └── index.html        # Responsive web UI (Chinese)
├── configs/
│   ├── libnfc.conf.default
│   ├── 99-nfc-pi.rules   # polkit rules for pi user
│   └── blacklist-libnfc.conf
├── bootstrap.sh           # One-click installer
├── start.sh               # Startup script
├── README.md              # Chinese documentation
└── README_EN.md           # English documentation
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/status | Reader and card status |
| GET | /api/dump/download | Download full card dump |
| POST | /api/dump/upload_file | Upload a dump file |
| POST | /api/dump/upload?filename= | Write dump to card |
| POST | /api/crack/mfoc | Start Nested attack |
| POST | /api/crack/mfcuk | Start Darkside attack |
| POST | /api/crack/stop | Stop cracking |

## PCB / Wiring (PN532 on custom board)

If you're using a standalone PN532 module instead of ACR122U, connect it via SPI/UART/I2C to the Raspberry Pi GPIO pins. The `libnfc` library supports all these interfaces.

## Known Issues

- ACR122U-A10 clone firmware may not support `FF 82`/`FF 86` APDU authentication commands
- Some clone readers report "No tag found" via libnfc's `InListPassiveTarget` while still being detected via pcsc
- **Solution**: Use a genuine ACR122U/ACR1252U, or compile libnfc from source with `acr122_usb` driver enabled

## License

MIT
