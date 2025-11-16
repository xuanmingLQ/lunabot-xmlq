from os import getenv
from dotenv import load_dotenv

load_dotenv()

CONFIG_DIR=getenv('CONFIG_DIR') or "config/"