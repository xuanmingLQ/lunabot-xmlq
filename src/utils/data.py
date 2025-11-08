from .env import DATA_DIR, SEKAI_USER_DATA_DIR
from os.path import join
def get_data_path(path:str)->str:
    return join(DATA_DIR, path)
def get_sekai_user_data_path(path:str)->str:
    return join(SEKAI_USER_DATA_DIR, path)