import uvicorn

from logging_config import UVICORN_LOG_CONFIG
from webapp import app


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8001,
        access_log=True,
        log_config=UVICORN_LOG_CONFIG,
    )
