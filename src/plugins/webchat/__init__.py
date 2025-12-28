from ..utils import handler as handler_module
from ..utils import *
from nonebot import get_bot as nb_get_bot


config = Config('webchat')
logger = get_logger("WebChat")
file_db = get_file_db("data/webchat/db.json", logger)


# =================== Nonebot框架 Adapter =================== # 

WEB_MSG_ID_START = 10**12
WEB_USER_ID_START = 10**12
WEB_GROUP_ID_START = 10**12
WEB_FORWARD_ID_PREFIX = "wcforward"
WEB_FILE_PREFIX = "wcfile://"


class BotWrapper:
    def __init__(self, bot: Bot | None):
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

@dataclass
class HandlerContextWrapper(HandlerContext):
    def asend_msg(self, msg: str):
        if self.group_id and self.group_id >= WEB_GROUP_ID_START:
            # TODO 发送网页端群消息
            raise NotImplementedError()
        return super().asend_msg(msg)

    def asend_reply_msg(self, msg: str):
        if self.group_id and self.group_id >= WEB_GROUP_ID_START:
            # TODO 发送网页端群回复消息
            raise NotImplementedError()
        return super().asend_reply_msg(msg)

    def asend_at_msg(self, msg: str):
        if self.group_id and self.group_id >= WEB_GROUP_ID_START:
            # TODO 发送网页端群at消息
            raise NotImplementedError()
        return super().asend_at_msg(msg)


# 覆盖 get_bot 方法
def get_bot_wrapper() -> BotWrapper:
    bot = nb_get_bot()
    return BotWrapper(bot)
handler_module.get_bot = get_bot_wrapper

# 覆盖 HandlerContext 类型
handler_module.HandlerContext = HandlerContextWrapper


def process_msg(event: GroupMessageEvent):
    """
    处理群消息事件，进行指令匹配和处理
    """
    text = event.message.extract_plain_text()
    to_me = event.is_tome()
    logger.debug(f"指令匹配: group_id={event.group_id}, user_id={event.user_id}, to_me={to_me}, text={text}")
    for handler in CmdHandler.cmd_handlers:
        if handler.only_to_me and not to_me:
            continue
        for cmd in handler.commands:
            if text.startswith(cmd):
                logger.info(f"指令匹配成功: command={cmd}")
                handler.handler_func(bot=BotWrapper(None), event=event)
            
