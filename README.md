<h1> 🚀 &nbsp;BOT TELEGRAM PROXMOX </h1>

<h4> 1. Install venv jika belum </h4>
apt install python3-venv -y

<h4> 2. Buat virtual environment </h4>
python3 -m venv env

<h4> 3. Aktifkan environment </h4>
source env/bin/activate

<h4> 4. Install requirements </h4>
pip install -r requirements.txt

<h2> Jadikan Bot Layanan Otomatis (Systemd) </h2>

sudo nano /etc/systemd/system/proxmoxbot.service

<h2> ISIAN DATA </h2>

[Unit]
Description=BOT Telegram Proxmox
After=network.target

[Service]
WorkingDirectory=/root/bot/
ExecStart=/root/bot/env/bin/python3 /root/bot/bot.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target

# Sesuaikan Folder Bot Anda #

sudo systemctl daemon-reexec
sudo systemctl daemon-reload
sudo systemctl enable proxmoxbot
sudo systemctl start proxmoxbot
sudo systemctl status proxmoxbot

Monitor Log Bot
journalctl -u proxmoxbot -f

