"""Central logging via structlog — ponytail: JSON in prod, console in dev."""
import logging
import logging.config
import os


def configure_logging() -> None:
    level = os.environ.get("SICK_LOG_LEVEL", "INFO").upper()
    fmt = os.environ.get("SICK_LOG_FORMAT", "json")
    try:
        import structlog  # type: ignore

        processors = [
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer() if fmt == "json" else structlog.dev.ConsoleRenderer(),
        ]
        structlog.configure(
            processors=processors,  # type: ignore
            wrapper_class=structlog.stdlib.BoundLogger,  # type: ignore
            logger_factory=structlog.stdlib.LoggerFactory(),  # type: ignore
            cache_logger_on_first_use=True,
        )
        logging.config.dictConfig(
            {
                "version": 1,
                "disable_existing_loggers": False,
                "formatters": {
                    "plain": {
                        "()": structlog.stdlib.ProcessorFormatter,  # type: ignore
                        "processor": processors[-1],
                        "foreign_pre_chain": processors[:-1],
                    }
                },
                "handlers": {
                    "default": {
                        "class": "logging.StreamHandler",
                        "formatter": "plain",
                        "stream": "ext://sys.stderr",
                    }
                },
                "root": {"handlers": ["default"], "level": level},
            }
        )
    except Exception:
        logging.basicConfig(level=getattr(logging, level, logging.INFO))
