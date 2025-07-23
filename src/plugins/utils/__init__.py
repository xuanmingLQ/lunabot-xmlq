from .process_pool import is_main_process
if is_main_process():
    from .utils import *