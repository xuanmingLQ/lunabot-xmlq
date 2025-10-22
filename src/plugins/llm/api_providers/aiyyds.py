from ...llm.api_provider import *
from openai import AsyncOpenAI
import asyncio
import json
import os


class AiyydsApiProvider(ApiProvider):
    def __init__(self):
        super().__init__(name="ai-yyds", code="ay")
        self.cookies_save_path = "data/llm/aiyyds_quota_check_cookies.json"

    def get_client(self) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=self.get_api_key(),
            base_url=self.get_base_url(),
        )
        
    async def _update_sync_quota_web_cookies(self):
        def get_cookies():
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            import time
            options = Options()
            options.add_argument('--headless')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            driver = webdriver.Chrome(options=options)
            try:
                login_url = self.config.get("login_url")
                driver.get(login_url)
                time.sleep(1)
                driver.find_element(by='name', value='username').send_keys(self.config.get("username"))
                driver.find_element(by='name', value='password').send_keys(self.config.get("password"))
                driver.find_element(by='xpath', value='//button[text()="登录"]').click()
                time.sleep(1)
                cookies = driver.get_cookies()
                for c in cookies:
                    if c['name'] == 'session':
                        return { "session": c['value'] }
                raise Exception("No cookie found")
            except Exception as e:
                logger.print_exc(f"获取cookies失败: {e}")  
                return None
            finally:
                driver.quit()
        cookies = await asyncio.get_event_loop().run_in_executor(None, get_cookies)
        if not cookies:
            raise Exception("获取AI-YYDScookies失败")
        os.makedirs(os.path.dirname(self.cookies_save_path), exist_ok=True)
        with open(self.cookies_save_path, "w") as f:
            json.dump(cookies, f)
        return cookies

    async def sync_quota(self):
        api_url = self.config.get("quota_url")
        while True:
            # 读取本地cookies，如果读取失败则重新获取
            try:
                with open(self.cookies_save_path, "r") as f:
                    cookies = json.load(f)
            except:
                logger.warning("未找到本地AI-YYDScookies文件, 重新获取")
                cookies = await self._update_sync_quota_web_cookies()

            # 查询额度
            import aiohttp
            async with aiohttp.ClientSession(cookies=cookies) as session:
                async with session.get(api_url) as response:
                    if response.status == 401:
                        logger.info("AI-YYDS登录失效, 删除并重新获取cookies")
                        os.remove(self.cookies_save_path)
                        continue
                    if response.status != 200:
                        raise Exception(f"请求失败: {response.status}")
                    res = await response.json()
                    quota = res['data']['quota'] / 500000
                    return quota



