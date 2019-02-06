import os
import sys
import logging

from config import config
LOG_PATH = config["LOG_PATH"]

log_format = logging.Formatter("%(asctime)s [%(levelname)s]: %(message)s")

error_file_handler = logging.FileHandler(os.path.join(LOG_PATH, "error_stormgift.log"))
error_file_handler.setFormatter(log_format)
error_logger = logging.getLogger("error")
error_logger.setLevel(logging.ERROR)
error_logger.addHandler(error_file_handler)

console = logging.StreamHandler(sys.stdout)
console.setFormatter(log_format)
stormgift_file_handler = logging.FileHandler(os.path.join(LOG_PATH, "stormgift.log"))
stormgift_file_handler.setFormatter(log_format)

listener_file_handler = logging.FileHandler(os.path.join(LOG_PATH, "listener_stormgift.log"))
listener_file_handler.setFormatter(log_format)
listener_logger = logging.getLogger("listener")
listener_logger.setLevel(logging.DEBUG)
listener_logger.addHandler(console)
listener_logger.addHandler(listener_file_handler)
listener_logger.addHandler(stormgift_file_handler)
_ = listener_logger.error
def f(*args, **kw):
    error_logger.error(*args, **kw)
    _(*args, **kw)
listener_logger.error = f


acceptor_file_handler = logging.FileHandler(os.path.join(LOG_PATH, "acceptor_stormgift.log"))
acceptor_file_handler.setFormatter(log_format)
acceptor_logger = logging.getLogger("acceptor")
acceptor_logger.setLevel(logging.DEBUG)
acceptor_logger.addHandler(console)
acceptor_logger.addHandler(acceptor_file_handler)
acceptor_logger.addHandler(stormgift_file_handler)
_ = acceptor_logger.error
def f(*args, **kw):
    error_logger.error(*args, **kw)
    _(*args, **kw)
acceptor_logger.error = f


api_file_handler = logging.FileHandler(os.path.join(LOG_PATH, "api_stormgift.log"))
api_file_handler.setFormatter(log_format)
api_logger = logging.getLogger("api")
api_logger.setLevel(logging.DEBUG)
api_logger.addHandler(console)
api_logger.addHandler(api_file_handler)
api_logger.addHandler(stormgift_file_handler)
_ = api_logger.error
def f(*args, **kw):
    error_logger.error(*args, **kw)
    _(*args, **kw)
api_logger.error = f


status_file_handler = logging.FileHandler(os.path.join(LOG_PATH, "clients_status.log"))
status_file_handler.setFormatter(log_format)
status_logger = logging.getLogger("clients_status")
status_logger.setLevel(logging.DEBUG)
status_logger.addHandler(console)
status_logger.addHandler(status_file_handler)
status_logger.addHandler(stormgift_file_handler)
__all__ = (
    "listener_logger",
    "acceptor_logger",
    "status_logger",
    "api_logger",
)