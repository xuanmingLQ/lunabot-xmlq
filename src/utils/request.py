import aiohttp
session = aiohttp.ClientSession()
async def server(path:str, method:str, json:dict|None=None, query:dict|None=None):
    
    pass