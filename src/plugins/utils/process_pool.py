import nonebot
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
import asyncio

def func(f, *args, **kwargs):
    nonebot.init()
    return f(*args, **kwargs)

class ProcessPool:
    def __init__(self, max_workers):
        executor = ProcessPoolExecutor(max_workers=max_workers, mp_context=mp.get_context('spawn'))
        self.executor = executor

    def submit(self, fn, *args, **kwargs):
        return asyncio.get_event_loop().run_in_executor(self.executor, func, fn, *args, **kwargs)

def is_main_process():
    return mp.current_process().name == 'MainProcess'

