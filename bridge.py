import asyncio
import os
import time
from pathlib import Path
from typing import Dict

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    UploadFile,
    File,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from telegram import (
    Update,
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    WebAppInfo,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    PicklePersistence,
    filters,
)
from telegram.constants import ChatAction
from letsgo import CORE_COMMANDS, COMMAND_MAP
import uvicorn

PROMPT = ">>"

MAIN_COMMANDS = [cmd for cmd in ("/status", "/time", "/help") if cmd in CORE_COMMANDS]


def build_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(cmd.lstrip("/"), callback_data=cmd)
                for cmd in MAIN_COMMANDS
            ]
        ]
    )


RUN_COMMAND = 0


class LetsGoProcess:
    """Manage a persistent letsgo.py subprocess."""

    def __init__(self) -> None:
        self.proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            "python",
            "letsgo.py",
            "--no-color",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )
        await self._read_until_prompt()

    async def _read_until_prompt(self) -> None:
        if not self.proc or not self.proc.stdout:
            return
        prompt_bytes = (PROMPT + " ").encode()
        buffer = b""
        while not buffer.endswith(prompt_bytes):
            chunk = await self.proc.stdout.read(1)
            if not chunk:
                break
            buffer += chunk

    async def run(self, cmd: str) -> str:
        if not self.proc or not self.proc.stdin or not self.proc.stdout:
            raise RuntimeError("process not started")
        async with self._lock:
            self.proc.stdin.write((cmd + "\n").encode())
            await self.proc.stdin.drain()
            prompt_bytes = (PROMPT + " ").encode()
            buffer = b""
            while not buffer.endswith(prompt_bytes):
                chunk = await self.proc.stdout.read(1)
                if not chunk:
                    break
                buffer += chunk
            text = buffer.decode()
            if text.endswith(PROMPT + " "):
                text = text[: -len(PROMPT) - 1]
            if text.startswith(PROMPT + " "):
                text = text[len(PROMPT) + 1 :]
            return text.strip()

    async def stop(self) -> None:
        if self.proc and self.proc.stdin:
            self.proc.stdin.close()
        if self.proc:
            self.proc.terminate()
            await self.proc.wait()
            self.proc = None


letsgo = LetsGoProcess()
sessions: Dict[str, LetsGoProcess] = {}
user_sessions: Dict[int, LetsGoProcess] = {}
_user_last_active: Dict[int, float] = {}
SESSION_TIMEOUT = float(os.getenv("USER_SESSION_TIMEOUT", "300"))
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
security = HTTPBasic()
API_TOKEN = os.getenv("API_TOKEN", "change-me")
RATE_LIMIT = float(os.getenv("RATE_LIMIT_SEC", "1"))
_last_call: Dict[str, float] = {}
UPLOAD_DIR = "/arianna_core/upload"


HISTORY_ROOT = Path.home() / ".letsgo"


def _history_path(user_id: int) -> Path:
    return HISTORY_ROOT / str(user_id) / "history"


def _append_history(user_id: int, cmd: str) -> None:
    path = _history_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(cmd + "\n")


def _read_history(user_id: int) -> list[str]:
    path = _history_path(user_id)
    try:
        with path.open(encoding="utf-8") as fh:
            return [line.rstrip() for line in fh]
    except FileNotFoundError:
        return []


def _check_rate(client: str) -> None:
    now = time.time()
    if now - _last_call.get(client, 0) < RATE_LIMIT:
        raise HTTPException(status_code=429, detail="rate limit exceeded")
    _last_call[client] = now


async def _get_user_proc(user_id: int) -> LetsGoProcess:
    proc = user_sessions.get(user_id)
    if not proc:
        proc = LetsGoProcess()
        await proc.start()
        user_sessions[user_id] = proc
    _user_last_active[user_id] = time.time()
    return proc


async def cleanup_user_sessions() -> None:
    try:
        while True:
            await asyncio.sleep(60)
            now = time.time()
            stale = [
                uid
                for uid, last in _user_last_active.items()
                if now - last > SESSION_TIMEOUT
            ]
            for uid in stale:
                proc = user_sessions.pop(uid, None)
                _user_last_active.pop(uid, None)
                if proc:
                    await proc.stop()
    except asyncio.CancelledError:
        pass


@app.post("/run")
async def run_command(
    cmd: str, credentials: HTTPBasicCredentials = Depends(security)
) -> Dict[str, str]:
    if credentials.password != API_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")
    _check_rate(credentials.username)
    output = await letsgo.run(cmd)
    return {"output": output}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token")
    sid = websocket.query_params.get("sid")
    if token != API_TOKEN or not sid:
        await websocket.close(code=1008)
        return
    proc = sessions.get(sid)
    if not proc:
        proc = LetsGoProcess()
        await proc.start()
        sessions[sid] = proc
    await websocket.accept()
    try:
        while True:
            cmd = await websocket.receive_text()
            if cmd == "__close__":
                break
            output = await proc.run(cmd)
            await websocket.send_text(output)
    except WebSocketDisconnect:
        pass
    finally:
        await proc.stop()
        sessions.pop(sid, None)


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    credentials: HTTPBasicCredentials = Depends(security),
) -> Dict[str, str]:
    if credentials.password != API_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")
    _check_rate(credentials.username)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    dest = os.path.join(UPLOAD_DIR, file.filename)
    with open(dest, "wb") as fh:
        fh.write(await file.read())
    return {"filename": file.filename}


@app.websocket("/upload")
async def upload_ws(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token")
    name = websocket.query_params.get("name")
    if token != API_TOKEN or not name:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    path = os.path.join(UPLOAD_DIR, name)
    try:
        with open(path, "wb") as fh:
            while True:
                data = await websocket.receive_bytes()
                fh.write(data)
    except WebSocketDisconnect:
        pass


async def handle_telegram(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cmd = update.message.text if update.message else ""
    user = update.effective_user
    if not cmd or not user:
        return
    history = context.user_data.setdefault("history", [])
    history.append(cmd)
    try:
        proc = await _get_user_proc(user.id)
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=ChatAction.TYPING,
        )
        output = await proc.run(cmd)
        if cmd.split()[0] != "/history":
            _append_history(user.id, cmd)
    except Exception as exc:  # noqa: BLE001 - send error to user
        await update.message.reply_text(f"Error: {exc}")
        return
    if not output:
        return
    base = cmd.split()[0]
    if base in MAIN_COMMANDS:
        await update.message.reply_text(output, reply_markup=build_main_keyboard())
    else:
        if len(output) > 4000:
            for i in range(0, len(output), 4000):
                chunk = output[i : i + 4000]
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"```\n{chunk}\n```",
                    parse_mode="Markdown",
                )
        else:
            await update.message.reply_text(output)


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    document = update.message.document
    photo = update.message.photo[-1] if update.message.photo else None
    tg_file = None
    name = None
    if document:
        tg_file = await document.get_file()
        name = document.file_name or document.file_unique_id
    elif photo:
        tg_file = await photo.get_file()
        name = f"{photo.file_unique_id}.jpg"
    if not tg_file or not name:
        return
    dest = Path(name)
    await tg_file.download_to_drive(custom_path=str(dest))
    await update.message.reply_text(f"file {name} uploaded")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = [f"{cmd} - {desc}" for cmd, (_, desc) in sorted(COMMAND_MAP.items())]
    commands = "\n".join(lines)
    await update.message.reply_text(
        "Welcome! Available commands:\n" + commands,
        reply_markup=build_main_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args:
        cmd = "/help " + " ".join(context.args)
        if update.message:
            update.message.text = cmd
        await handle_telegram(update, context)
    else:
        await start(update, context)


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.message:
        return
    history = _read_history(user.id)
    if history:
        await update.message.reply_text("\n".join(history))
    else:
        await update.message.reply_text("No history yet.")


async def run_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Send the command to run.")
    return RUN_COMMAND


async def run_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cmd = update.message.text if update.message else ""
    user = update.effective_user
    if not cmd or not user:
        await update.message.reply_text("No command provided.")
        return ConversationHandler.END
    history = context.user_data.setdefault("history", [])
    history.append(cmd)
    try:
        proc = await _get_user_proc(user.id)
        output = await proc.run(cmd)
        _append_history(user.id, cmd)
        await update.message.reply_text(output)
    except Exception as exc:  # noqa: BLE001 - send error to user
        await update.message.reply_text(f"Error: {exc}")
    return ConversationHandler.END


async def run_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    cmd = query.data or ""
    user = update.effective_user
    if not user:
        return
    history = context.user_data.setdefault("history", [])
    history.append(cmd)
    proc = await _get_user_proc(user.id)
    output = await proc.run(cmd)
    _append_history(user.id, cmd)
    await query.answer()
    await query.message.reply_text(output, reply_markup=build_main_keyboard())


async def start_bot() -> None:
    token = os.getenv("TELEGRAM_TOKEN", "").strip()
    if not token:
        return
    persistence_path = os.getenv("TELEGRAM_PERSISTENCE", "telegram_state.pkl")
    persistence = PicklePersistence(filepath=persistence_path)
    application = ApplicationBuilder().token(token).persistence(persistence).build()
    webhook_info = await application.bot.get_webhook_info()
    if webhook_info.url:
        await application.bot.delete_webhook(drop_pending_updates=True)
    commands = [
        BotCommand(cmd[1:], desc.lower()) for cmd, (_, desc) in CORE_COMMANDS.items()
    ]
    commands.append(BotCommand("history", "show command history"))
    await application.bot.set_my_commands(commands)
    terminal_url = os.getenv("WEB_TERMINAL_URL", "").strip()
    if terminal_url:
        await application.bot.set_chat_menu_button(
            MenuButtonWebApp(text="Terminal", web_app=WebAppInfo(url=terminal_url))
        )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("history", history_command))
    run_conv = ConversationHandler(
        entry_points=[CommandHandler("run", run_start)],
        states={
            RUN_COMMAND: [MessageHandler(filters.TEXT & ~filters.COMMAND, run_execute)]
        },
        fallbacks=[CommandHandler("cancel", run_cancel)],
    )
    application.add_handler(run_conv)
    application.add_handler(MessageHandler(filters.ATTACHMENT, handle_file))
    application.add_handler(MessageHandler(filters.COMMAND, handle_telegram))
    application.add_handler(CallbackQueryHandler(handle_callback))
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    try:
        await asyncio.Future()
    finally:
        await application.updater.stop()
        await application.update_persistence()
        await application.stop()
        await application.shutdown()


async def main() -> None:
    await letsgo.start()
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="0.0.0.0",
            port=int(os.getenv("PORT", "8000")),
        )
    )
    await asyncio.gather(server.serve(), start_bot(), cleanup_user_sessions())


if __name__ == "__main__":
    asyncio.run(main())
