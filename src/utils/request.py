import aiohttp
from urllib.parse import urlencode
from .utils import loads_json,get_logger,HttpError
from .env import API_BASE_PATH, ASSETS_BASE_PATH, DECK_RECOMMEND_BASE_PATH

api_logger = get_logger("Api")
download_logger = get_logger("Assets")
class ApiError(Exception):
    def __init__(self, path, msg, *args):
        self.path=path
        self.msg = msg
        super().__init__(*args)
    pass
# Api请求
async def server(path:str, method:str, json:dict|None=None, query:dict|None=None)->dict:
    url = f"{API_BASE_PATH}{path}"
    if query:
        url = f"{url}?{parse_query(query)}"
    api_logger.info(url)
    #headers
    try:
        async with aiohttp.ClientSession() as session:
            async with session.request(method,url,json=json) as resp:
                if resp.status != 200:
                    try:
                        detail = await resp.text()
                        detail = loads_json(detail)['detail']
                    except Exception:
                        pass
                    api_logger.error(f"请求后端API {url} 失败: {resp.status} {detail}")
                    raise HttpError(resp.status, detail)
                res = await resp.json()
                if res["code"]!=0:
                    raise ApiError(path, res["msg"])
                return res["data"]
    except aiohttp.ClientConnectionError as e:
        raise Exception(f"连接后端API失败，请稍后再试")
    pass
# 下载资源
async def download_data(path:str, params:list|None=None, query:dict|None=None):
    url = f"{ASSETS_BASE_PATH}{path}"
    if params: url = "/".join([url]+params)
    if query:
        url=f"{url}?{parse_query(query)}"
    download_logger.info(url)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.request("get",url) as resp:
                if resp.status != 200:
                    try:
                        detail = await resp.text()
                        detail = loads_json(detail)['detail']
                    except Exception:
                        pass
                    download_logger.error(f"下载资源 {url} 失败: {resp.status} {detail}")
                    raise HttpError(resp.status, detail)
                return await resp.read()
    except aiohttp.ClientConnectionError as e:
        raise Exception(f"连接资源Api失败，请稍后再试")
    pass
async def deck_server(path:str, method:str='post', json:dict|None=None):
    url = f'{DECK_RECOMMEND_BASE_PATH}{path}'
    try:
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, json=json) as resp:
                if resp.status!=200:
                    try:
                        detail = await resp.text()
                        detail = loads_json(detail)['detail']
                    except Exception:
                        pass
                    raise HttpError(resp.status, detail)
                data = await resp.json()
                if data['status'] != 'success':
                    raise ApiError(path, data['exception'])
                return data
    except aiohttp.ClientConnectionError as e:
        raise Exception(f"连接组卡服务失败，请稍后再试")
    pass
            
# 把查询参数转换为查询字符串
def parse_query(query:dict|None):
    if query is None:
        return ''
    queryCopy = {}
    for key,val in query.items():
        if val is None:
            continue
        if isinstance(val,list):
            queryCopy[key] = ','.join(val)
        else:
            queryCopy[key]=val
    return urlencode(queryCopy)
