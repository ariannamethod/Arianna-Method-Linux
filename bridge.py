import asyncio
import os
import time
from typing import Dict, AsyncIterator

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
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
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from letsgo import CORE_COMMANDS
import uvicorn

PROMPT = ">>"

MAIN_COMMANDS = ["/status", "/time", "/help"]
INLINE_KEYBOARD = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("status", callback_data="/status"),
            InlineKeyboardButton("time", callback_data="/time"),
            InlineKeyboardButton("help", callback_data="/help"),
        ]
    ]
)


class LetsGoProcess:
    """Manage a persistent letsgo.py subprocess."""

    def __init__(self) -> None:
        self.proc: asyncio.subprocess.Process | None = None

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
        if not self.proc:
            return
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                break
            if line.decode().strip() == PROMPT:
                break

    async def run(self, cmd: str) -> AsyncIterator[str]:
        """Yield output lines from the letsgo process."""
        if not self.proc:
            raise RuntimeError("process not started")
        assert self.proc.stdin
        self.proc.stdin.write((cmd + "\n").encode())
        await self.proc.stdin.drain()
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                break
            text = line.decode()
            if text.strip() == PROMPT:
                break
            if text.startswith(PROMPT + " "):
                prefix_len = len(PROMPT) + 1
                text = text[prefix_len:]
            yield text.rstrip("\n")


letsgo = LetsGoProcess()
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
    lines = [line async for line in letsgo.run(cmd)]
    output = "\n".join(lines).strip()
    return {"output": output}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token")
    if token != API_TOKEN:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            cmd = await websocket.receive_text()
            async for line in letsgo.run(cmd):
                await websocket.send_text(line)
    except WebSocketDisconnect:
        pass


async def handle_telegram(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    cmd = update.message.text if update.message else ""
    if not cmd:
        return
    first = True
    async for line in letsgo.run(cmd):
        if first and cmd in MAIN_COMMANDS:
            await update.message.reply_text(line, reply_markup=INLINE_KEYBOARD)
            first = False
        else:
            await update.message.reply_text(line)


async def handle_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    if not query:
        return
    cmd = query.data or ""
    lines = [line async for line in letsgo.run(cmd)]
    output = "\n".join(lines).strip()
    await query.answer()
    await query.message.reply_text(output, reply_markup=INLINE_KEYBOARD)


async def start_bot() -> None:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        return
    application = ApplicationBuilder().token(token).build()
    commands = []
    for cmd, (_, desc) in CORE_COMMANDS.items():
        commands.append(BotCommand(cmd[1:], desc))
    await application.bot.set_my_commands(commands)

    application.add_handler(MessageHandler(filters.TEXT, handle_telegram))
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
