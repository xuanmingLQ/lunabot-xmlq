from ...llm.api_provider import *
from openai import AsyncOpenAI
import asyncio
import json
import os
import aiohttp


class SiliconflowApiProvider(ApiProvider):
    def __init__(self):
        super().__init__(name="siliconflow", code="sf")

    def get_client(self) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=self.get_api_key(),
            base_url=self.get_base_url(),
        )
        
    async def sync_quota(self):
        async with aiohttp.ClientSession() as session:
            url = self.config.get("user_info_url")
            headers = {"Authorization": f"Bearer {self.get_api_key()}"}
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    raise Exception(f"获取SiliconFlow剩余额度失败: {resp.status} {resp.reason}")
                data = await resp.json()
                return float(data['data']['totalBalance'])

