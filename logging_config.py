from app_config import LOG_FILE


UVICORN_LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        },
        "access": {
            "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        },
    },
    "handlers": {
        "default": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stdout",
        },
        "access": {
            "class": "logging.StreamHandler",
            "formatter": "access",
            "stream": "ext://sys.stdout",
        },
        "file_default": {
            "class": "logging.FileHandler",
            "formatter": "default",
            "filename": LOG_FILE,
            "encoding": "utf-8",
        },
        "file_access": {
            "class": "logging.FileHandler",
            "formatter": "access",
            "filename": LOG_FILE,
            "encoding": "utf-8",
        },
    },
    "loggers": {
        "uvicorn": {
            "handlers": ["default", "file_default"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn.error": {
            "handlers": ["default", "file_default"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn.access": {
            "handlers": ["access", "file_access"],
            "level": "INFO",
            "propagate": False,
        },
        "kepapi": {
            "handlers": ["default", "file_default"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
