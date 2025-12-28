from ..utils import *
from nonebot import get_bot as nb_get_bot


config = Config('webchat')
logger = get_logger("WebChat")
file_db = get_file_db("data/webchat/db.json", logger)


WEB_MSG_ID_START = 10**12
WEB_USER_ID_START = 10**12
WEB_GROUP_ID_START = 10**12
WEB_FORWARD_ID_PREFIX = "webchat_forward_"
WEB_FILE_PREFIX = "webchat_file://"


class BotWrapper:
    """
    Bot wrapper 用于封装 AdapterBot 对象，并且提供网页端伪造 Bot 功能
    """
    def __init__(self, bot: Bot):
        self._bot: Bot = bot
        self.self_id: str = bot.self_id
    
    async def get_msg(self, message_id: int):
        if message_id < WEB_MSG_ID_START:
            return await self._bot.get_msg(message_id)
        # TODO 获取网页msg
        raise NotImplementedError()

    async def call_api(self, api: str, **data: Any):
        match api:
            case 'get_msg':
                return await self.get_msg(data['message_id'])
            
            case 'get_forward_msg':
                if str(data['forward_id']).startswith(WEB_FORWARD_ID_PREFIX):
                    # TODO 获取网页端合并转发消息
                    raise NotImplementedError()

            case 'get_group_list':
                group_list: list[dict] = await self._bot.call_api(api, **data)
                # TODO 添加网页端群组
                return group_list
            
            case 'get_group_member_list':
                if data['group_id'] >= WEB_GROUP_ID_START:
                    # TODO 获取网页端群成员列表
                    raise NotImplementedError()
            
            case 'get_stranger_info':
                if data['user_id'] >= WEB_USER_ID_START:
                    # TODO 获取网页端用户信息
                    raise NotImplementedError()

            case 'get_group_info':
                if data['group_id'] >= WEB_GROUP_ID_START:
                    # TODO 获取网页端群信息
                    raise NotImplementedError()

            case 'get_image':
                if str(data['file']).startswith(WEB_FILE_PREFIX):
                    # TODO 获取网页端图片
                    raise NotImplementedError()
                
            case 'get_file':
                if str(data['file']).startswith(WEB_FILE_PREFIX):
                    # TODO 获取网页端文件
                    raise NotImplementedError()
                
            case 'get_record':
                if str(data['file']).startswith(WEB_FILE_PREFIX):
                    # TODO 获取网页端语音
                    raise NotImplementedError()
                
            case 'upload_group_file':
                if data['group_id'] >= WEB_GROUP_ID_START:
                    # TODO 上传网页端图片
                    raise NotImplementedError()

        # 默认调用原 Bot 方法
        return await self._bot.call_api(api, **data)


# 覆盖 get_bot 方法
def get_bot_wrapper() -> BotWrapper:
    bot = nb_get_bot()
    return BotWrapper(bot)
get_bot = get_bot_wrapper

