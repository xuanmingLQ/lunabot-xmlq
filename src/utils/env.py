import os
from dotenv import load_dotenv
load_dotenv()
API_BASE_PATH=os.getenv('API_BASE_PATH')
ASSETS_BASE_PATH=os.getenv('ASSETS_BASE_PATH')
CONFIG_DIR=os.getenv('CONFIG_DIR') or "config/"
DATA_DIR=os.getenv('DATA_DIR') or "data/"
DECK_RECOMMEND_BASE_PATH=os.getenv('DECK_RECOMMEND_BASE_PATH')