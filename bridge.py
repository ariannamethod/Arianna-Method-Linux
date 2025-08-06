import asyncio
import os
import time
from typing import Dict

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse
from pathlib import Path
from telegram import (
    Update,
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from letsgo import CORE_COMMANDS
import uvicorn

PROMPT = ">>"

WEBAPP_URL = os.getenv("WEBAPP_URL", "http://localhost:8000/webapp")
INLINE_KEYBOARD = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("status", callback_data="/status"),
            InlineKeyboardButton("time", callback_data="/time"),
            InlineKeyboardButton("help", callback_data="/help"),
        ],
        [InlineKeyboardButton("Open WebApp", web_app={"url": WEBAPP_URL})],
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


@app.get("/webapp", response_class=HTMLResponse)
async def webapp_page() -> HTMLResponse:
    html_path = Path(__file__).with_name("arianna_terminal.html")
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


def _check_rate(client: str) -> None:
    now = time.time()
    if now - _last_call.get(client, 0) < RATE_LIMIT:
        raise HTTPException(status_code=429, detail="rate limit exceeded")
    _last_call[client] = now


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
            output = await proc.run(cmd)
            await websocket.send_text(output)
    except WebSocketDisconnect:
        pass
    finally:
        await proc.stop()
        sessions.pop(sid, None)


async def handle_telegram(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cmd = update.message.text if update.message else ""
    if not cmd:
        return
    try:
        output = await letsgo.run(cmd)
    except Exception as exc:  # noqa: BLE001 - send error to user
        await update.message.reply_text(f"Error: {exc}")
        return
    await update.message.reply_text(output, reply_markup=INLINE_KEYBOARD)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    commands = "\n".join(f"{cmd} - {desc}" for cmd, (_, desc) in CORE_COMMANDS.items())
    await update.message.reply_text(
        "Welcome! Available commands:\n" + commands,
        reply_markup=INLINE_KEYBOARD,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_telegram(update, context)


async def run_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Send the command to run.", reply_markup=INLINE_KEYBOARD
    )
    return RUN_COMMAND


async def run_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cmd = update.message.text if update.message else ""
    if not cmd:
        await update.message.reply_text("No command provided.")
        return ConversationHandler.END
    try:
        output = await letsgo.run(cmd)
        await update.message.reply_text(output, reply_markup=INLINE_KEYBOARD)
    except Exception as exc:  # noqa: BLE001 - send error to user
        await update.message.reply_text(f"Error: {exc}")
    return ConversationHandler.END


async def run_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Cancelled.", reply_markup=INLINE_KEYBOARD)
    return ConversationHandler.END


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    cmd = query.data or ""
    output = await letsgo.run(cmd)
    await query.answer()
    await query.message.reply_text(output, reply_markup=INLINE_KEYBOARD)


async def start_bot() -> None:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        return
    application = ApplicationBuilder().token(token).build()
    commands = [BotCommand(cmd[1:], desc) for cmd, (_, desc) in CORE_COMMANDS.items()]
    await application.bot.set_my_commands(commands)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    run_conv = ConversationHandler(
        entry_points=[CommandHandler("run", run_start)],
        states={
            RUN_COMMAND: [MessageHandler(filters.TEXT & ~filters.COMMAND, run_execute)]
        },
        fallbacks=[CommandHandler("cancel", run_cancel)],
    )
    application.add_handler(run_conv)
    application.add_handler(MessageHandler(filters.COMMAND, handle_telegram))
    application.add_handler(CallbackQueryHandler(handle_callback))
    await application.run_polling()


async def main() -> None:
    await letsgo.start()
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="0.0.0.0",
            port=int(os.getenv("PORT", "8000")),
        )
    )
    await asyncio.gather(server.serve(), start_bot())


if __name__ == "__main__":
    asyncio.run(main())
