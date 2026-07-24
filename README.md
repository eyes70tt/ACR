<<<<<<< HEAD
# ACR
=======
# NFC Web Manager

基于树莓派（Raspberry Pi）的 Web 端 NFC/RFID 读写与破解管理系统。

## 功能

- **实时卡片检测**：WebSocket 实时推送卡片放入/取出事件
- **UID 读取**：读取卡片 UID、类型（S50/S70）、容量、ATQA/SAK
- **整卡备份下载**：一键备份整卡为 `.bin` 文件
- **文件导入写入**：上传本地备份文件写入空白 IC 卡
- **扇区读写**：认证后读写指定 Data Block
- **密钥破译**：调用 mfoc（Nested Attack）和 mfcuk（Darkside Attack）
- **实时进度**：破译进度通过 WebSocket 推送到前端网格

## 硬件要求

| 设备 | 说明 |
|------|------|
| Raspberry Pi (3B+/4B/5) | 运行 Debian/Raspberry Pi OS (arm64) |
| ACR122U | ACS 或兼容的 PN532 读卡器 |

> **注意**：部分 ACR122U 克隆版固件可能不支持 Mifare Classic 认证（返回 0x63 0x00）。建议使用正版 ACR122U 或 ACR1252U。

## 快速安装

```bash
git clone https://github.com/YOUR_USERNAME/nfc-web-manager.git
cd nfc-web-manager
sudo bash bootstrap.sh
```

## 手动安装

1. 安装依赖

```bash
sudo apt-get install -y pcscd pcsc-tools libpcsclite-dev python3 python3-pip python3-venv
sudo apt-get install -y libnfc-bin libnfc-dev autoconf automake libtool pkg-config
```

2. 屏蔽内核 NFC 驱动

```bash
echo -e "blacklist nfc\nblacklist pn533\nblacklist pn533_usb" | sudo tee /etc/modprobe.d/blacklist-libnfc.conf
```

3. 创建 Python 虚拟环境并安装依赖

```bash
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn[standard] python-socketio pyscard pydantic
```

4. 配置密码文件

```bash
echo -n "你的sudo密码" > ~/.nfc_sudo_pw
chmod 600 ~/.nfc_sudo_pw
```

5. 启动服务

```bash
bash start.sh
```

然后访问 `http://<树莓派IP>:8000`

## 项目结构

```
nfc-web-manager/
├── backend/
│   ├── server.py         # FastAPI + Socket.IO 后端
│   ├── nfc_reader.py     # pyscard 读卡器交互
│   └── crack_engine.py   # mfoc/mfcuk 子进程管理
├── frontend/
│   └── index.html        # 响应式 Web 前端
├── configs/
│   ├── libnfc.conf.default
│   ├── 99-nfc-pi.rules   # polkit 规则
│   └── blacklist-libnfc.conf
├── bootstrap.sh           # 一键安装脚本
├── start.sh               # 启动脚本
└── README.md
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/status | 读卡器和卡片状态 |
| GET | /api/dump/download | 下载整卡备份 |
| POST | /api/dump/upload_file | 上传备份文件 |
| POST | /api/dump/upload?filename= | 将备份写入卡片 |
| POST | /api/crack/mfoc | 启动 Nested 攻击 |
| POST | /api/crack/mfcuk | 启动 Darkside 攻击 |
| POST | /api/crack/stop | 停止破解 |

## 已知问题

- ACR122U-A10 克隆版固件可能不支持 `FF 82`/`FF 86` APDU 认证
- 部分读卡器的 PN532 `InListPassiveTarget` 返回 `63 00`
- 解决方案：使用正版 ACR122U/ACR1252U，或通过 libnfc 源码编译

## 许可证

MIT
>>>>>>> ca7e239 (Initial commit: NFC Web Manager for Raspberry Pi)
