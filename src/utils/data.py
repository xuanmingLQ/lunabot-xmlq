from .config import global_config
from os.path import join
# 获取数据文件地址
def get_data_path(path:str)->str:
    return join(global_config.get("data_dir", "data/"), path)