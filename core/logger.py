import logging
import os
from logging.handlers import RotatingFileHandler

def get_logger(name):
    logger = logging.getLogger(name)
    # Ha már vannak handler-ek, ne adjunk hozzá újakat (duplikáció elkerülése reloadkor)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # 1. Konzolos kimenet
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 2. Fájl kimenet (külön fájl minden modulnak a logs/ mappában)
    os.makedirs("logs", exist_ok=True)
    file_handler = RotatingFileHandler(
        f"logs/{name}.log", 
        maxBytes=5*1024*1024, 
        backupCount=3, 
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger
