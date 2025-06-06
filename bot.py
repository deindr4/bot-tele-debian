# BOT Telegram Proxmox v1.1 (Build: 2025-06-05 16:22:57)

import os
import logging
import io
import time
import subprocess
import matplotlib.pyplot as plt
import psutil
from speedtest import Speedtest
from dotenv import load_dotenv
from proxmoxer import ProxmoxAPI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, constants
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Load env
load_dotenv()

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Auth
allowed_users = set(map(int, os.getenv("ALLOWED_USERS", "").split(",")))
allowed_groups = set(map(int, os.getenv("ALLOWED_GROUPS", "").split(",")))

def is_authorized(user_id: int, chat_id: int) -> bool:
    return user_id in allowed_users or chat_id in allowed_groups

# Proxmox connection
proxmox = ProxmoxAPI(
    os.getenv("PROXMOX_HOST"),
    user=os.getenv("PROXMOX_USER"),
    password=os.getenv("PROXMOX_PASS"),
    verify_ssl=os.getenv("PROXMOX_VERIFY_SSL", "False") == "True"
)

vm_status_cache = {}
def list_vms():
    all_vms = []
    for node in proxmox.nodes.get():
        node_name = node['node']
        try:
            qemu_vms = proxmox.nodes(node_name).qemu.get()
            for vm in qemu_vms:
                vm['type'] = 'qemu'
                vm['node'] = node_name
            all_vms.extend(qemu_vms)

            lxc_vms = proxmox.nodes(node_name).lxc.get()
            for vm in lxc_vms:
                vm['type'] = 'lxc'
                vm['node'] = node_name
            all_vms.extend(lxc_vms)
        except Exception as e:
            logger.warning(f"Gagal ambil VM dari node {node_name}: {e}")
    return all_vms

def get_vm_detail(vm):
    vmid = vm['vmid']
    node = vm['node']
    type_ = vm['type']
    status = proxmox.nodes(node).__getattr__(type_)(vmid).status.current.get()
    ip = status.get('ip', 'N/A')
    cpu = status.get('cpu', 0.0) * 100
    maxmem = status.get('maxmem', 1)
    mem = status.get('mem', 0)
    ram_percent = (mem / maxmem * 100) if maxmem else 0
    return (
        f"\n🖥 Name: {vm['name']}\n🆔 VMID: {vmid}\n📍 Node: {node}"
        f"\n📶 Status: {status.get('status', 'N/A')}\n💾 RAM: {ram_percent:.1f}%"
        f"\n🧠 CPU: {cpu:.1f}%\n🌐 IP: {ip}"
    )

def control_vm(vmid, action, type_, node):
    vm_api = proxmox.nodes(node).__getattr__(type_)(vmid)
    return getattr(vm_api.status, action).post()

def get_htop():
    return subprocess.getoutput("top -b -n 1")[:4000]

def ping(target):
    return subprocess.getoutput(f"ping -c 4 {target}")

def traceroute(target):
    try:
        return subprocess.getoutput(f"traceroute -n -w 2 -q 1 {target}")
    except Exception as e:
        return f"Gagal menjalankan traceroute: {e}"

def get_fan_status():
    try:
        return subprocess.getoutput("sensors")
    except Exception as e:
        return f"Gagal membaca sensor: {str(e)}"

def generate_cpu_ram_image():
    cpu = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory().percent
    fig, ax = plt.subplots()
    ax.bar(["CPU", "RAM"], [cpu, ram], color=["skyblue", "lightgreen"])
    ax.set_ylim(0, 100)
    ax.set_ylabel("Usage (%)")
    ax.set_title("CPU & RAM Usage")
    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    plt.close()
    return buf

def run_speedtest_image():
    st = Speedtest()
    st.get_best_server()
    ping_ms = st.results.ping
    download = st.download() / 1_000_000
    upload = st.upload() / 1_000_000
    fig, ax = plt.subplots()
    ax.bar(["Ping (ms)", "Download", "Upload"], [ping_ms, download, upload], color=["blue", "orange", "purple"])
    ax.set_ylabel("Mbps / ms")
    ax.set_title("Speedtest Result")
    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    plt.close()
    return buf

def get_uptime():
    return subprocess.getoutput("uptime -p")
async def notify_vm_changes(context: ContextTypes.DEFAULT_TYPE):
    try:
        vms = list_vms()
        for vm in vms:
            vmid = vm['vmid']
            status = vm['status']
            if vmid in vm_status_cache and vm_status_cache[vmid] != status:
                msg = f"⚠️ VM {vm['name']} ({vmid}) berubah status: {status.upper()}"
                for uid in allowed_users:
                    await context.bot.send_message(chat_id=uid, text=msg)
            vm_status_cache[vmid] = status
    except Exception as e:
        logger.error(f"[Monitor Error] {e}")

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [
         InlineKeyboardButton("📋 VM/CT", callback_data='list'),
         InlineKeyboardButton("📈 HTOP", callback_data='htop'),
         InlineKeyboardButton("📊 Monitor", callback_data='monitor'),
        ],
        [
         InlineKeyboardButton("📶 Ping", callback_data='ping'),
         InlineKeyboardButton("📍 Traceroute", callback_data='traceroute'),
         InlineKeyboardButton("🌐 Speedtest", callback_data='speedtest')
        ],
        [
         InlineKeyboardButton("🌬 FAN", callback_data='fan'),
         InlineKeyboardButton("⏱ Uptime", callback_data='uptime')
        ],
        [InlineKeyboardButton("ℹ️ Versi", callback_data='version')]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id, update.effective_chat.id):
        return await update.message.reply_text("❌ Tidak diizinkan.")
    await update.message.reply_text("🤖 BOT Telegram Proxmox v1.1\nPilih menu:", reply_markup=main_menu_keyboard())

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if not is_authorized(query.from_user.id, query.message.chat.id):
        return await query.edit_message_text("❌ Tidak diizinkan.")

    if data == 'start':
        return await query.edit_message_text("Pilih menu utama:", reply_markup=main_menu_keyboard())

    elif data == 'list':
        vms = list_vms()
        buttons = [[InlineKeyboardButton(f"{vm['name']} ({vm['vmid']})", callback_data=f"vm_{vm['vmid']}_{vm['type']}")] for vm in vms]
        buttons.append([InlineKeyboardButton("⬅ Menu Utama", callback_data="start")])
        return await query.edit_message_text("📋 Daftar VM/CT:", reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("vm_"):
        _, vmid, type_ = data.split("_")
        vm = next((v for v in list_vms() if str(v['vmid']) == vmid and v['type'] == type_), None)
        if not vm:
            return await query.edit_message_text("⚠️ VM tidak ditemukan.")
        detail = get_vm_detail(vm)
        buttons = [
            [InlineKeyboardButton("▶ Start", callback_data=f"start_{vmid}_{type_}"),
             InlineKeyboardButton("🔁 Reboot", callback_data=f"reboot_{vmid}_{type_}"),
             InlineKeyboardButton("⏹ Stop", callback_data=f"stop_{vmid}_{type_}")],
            [InlineKeyboardButton("📄 Status", callback_data=f"vm_{vmid}_{type_}")],
            [InlineKeyboardButton("⬅ Menu Utama", callback_data="start")]
        ]
        return await query.edit_message_text(f"Kontrol VM:{detail}", reply_markup=InlineKeyboardMarkup(buttons), parse_mode=constants.ParseMode.HTML)

    elif data.startswith(("start_", "reboot_", "stop_")):
        action, vmid, type_ = data.split("_")
        vm = next((v for v in list_vms() if str(v['vmid']) == vmid and v['type'] == type_), None)
        if vm:
            control_vm(vmid, action, type_, vm['node'])
            await query.edit_message_text(f"✅ {action.upper()} VM {vm['name']} berhasil.", reply_markup=main_menu_keyboard())

    elif data == 'htop':
        output = get_htop()
        await query.edit_message_text(f"<pre>{output}</pre>", parse_mode=constants.ParseMode.HTML, reply_markup=main_menu_keyboard())

    elif data == 'monitor':
        buf = generate_cpu_ram_image()
        await query.message.reply_photo(photo=buf, caption="📊 CPU & RAM Monitor", reply_markup=main_menu_keyboard())

    elif data == 'fan':
        status = get_fan_status()
        await query.edit_message_text(f"<pre>{status}</pre>", parse_mode=constants.ParseMode.HTML, reply_markup=main_menu_keyboard())

    elif data == 'speedtest':
        buf = run_speedtest_image()
        await query.message.reply_photo(photo=buf, caption="🌐 Speedtest Result", reply_markup=main_menu_keyboard())

    elif data == 'uptime':
        uptime = get_uptime()
        await query.edit_message_text(f"⏱ {uptime}", reply_markup=main_menu_keyboard())

    elif data == 'version':
        await query.edit_message_text("🤖 BOT Telegram Proxmox v1.1", reply_markup=main_menu_keyboard())

    elif data == 'ping':
        keyboard = [
            [InlineKeyboardButton("🔵 Google", callback_data="ping_google"),
             InlineKeyboardButton("🟣 Cloudflare", callback_data="ping_cf")],
            [InlineKeyboardButton("⚪ Custom", callback_data="ping_custom")],
            [InlineKeyboardButton("⬅ Menu Utama", callback_data="start")]
        ]
        await query.edit_message_text("Pilih target ping:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("ping_"):
        if data == "ping_custom":
            context.user_data["awaiting_ping"] = True
            return await query.edit_message_text("Masukkan IP atau domain tujuan:", reply_markup=main_menu_keyboard())
        target_map = {"ping_google": "8.8.8.8", "ping_cf": "1.1.1.1"}
        result = ping(target_map[data])
        return await query.edit_message_text(f"<pre>{result}</pre>", parse_mode=constants.ParseMode.HTML, reply_markup=main_menu_keyboard())

    elif data == 'traceroute':
        keyboard = [
            [InlineKeyboardButton("🔵 Google", callback_data="trace_google"),
             InlineKeyboardButton("🟣 Cloudflare", callback_data="trace_cf")],
            [InlineKeyboardButton("⚪ Custom", callback_data="trace_custom")],
            [InlineKeyboardButton("⬅ Menu Utama", callback_data="start")]
        ]
        await query.edit_message_text("Traceroute ke mana?", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("trace_"):
        if data == "trace_custom":
            context.user_data["awaiting_trace"] = True
            return await query.edit_message_text("Masukkan IP/domain tujuan:", reply_markup=main_menu_keyboard())
        target_map = {"trace_google": "8.8.8.8", "trace_cf": "1.1.1.1"}
        result = traceroute(target_map[data])
        await query.edit_message_text(f"<pre>{result}</pre>", parse_mode=constants.ParseMode.HTML, reply_markup=main_menu_keyboard())

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting_ping"):
        target = update.message.text.strip()
        result = ping(target)
        context.user_data["awaiting_ping"] = False
        await update.message.reply_text(f"<pre>{result}</pre>", parse_mode=constants.ParseMode.HTML, reply_markup=main_menu_keyboard())

    elif context.user_data.get("awaiting_trace"):
        target = update.message.text.strip()
        result = traceroute(target)
        context.user_data["awaiting_trace"] = False
        await update.message.reply_text(f"<pre>{result}</pre>", parse_mode=constants.ParseMode.HTML, reply_markup=main_menu_keyboard())

# Init & run
async def post_init(app):
    app.job_queue.run_repeating(notify_vm_changes, interval=20)

app = Application.builder().token(os.getenv("TELEGRAM_TOKEN")).post_init(post_init).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

if __name__ == '__main__':
    app.run_polling()
