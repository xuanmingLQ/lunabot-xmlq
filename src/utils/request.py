import aiohttp,os
from dotenv import load_dotenv
from urllib.parse import urlencode
from ..plugins.utils import loads_json,get_logger,HttpError
load_dotenv()
base_url=os.getenv('API_BASE_PATH')

api_logger = get_logger("Api")

async def server(path:str, method:str, json:dict|None=None, params:dict|None=None)->dict:
    global base_url
    url = f"{base_url}{path}"
    if params:
        url = f"{url}?{parse_query(params)}"
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
                return await resp.json()
    except aiohttp.ClientConnectionError as e:
        raise Exception(f"连接后端API失败，请稍后再试")
    pass
def parse_query(params:dict|None):
    if params is None:
        return ''
    querys = {}
    for key,val in params.items():
        if val is None:
            continue
        if isinstance(val,list):
            querys[key] = ','.join(val)
        else:
            querys[key]=val
    return urlencode(querys)
