from .utils import *
from nonebot import on_command, get_bot
from nonebot.rule import to_me as rule_to_me
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Bot, MessageEvent
from nonebot.adapters.onebot.v11.message import Message as OutMessage
from argparse import ArgumentParser
import requests


# ============================ 消息处理 ============================ #

# 获取加入的所有群id
async def get_group_id_list(bot):
    group_list = await bot.call_api('get_group_list')
    return [group['group_id'] for group in group_list]

# 获取加入的所有群
async def get_group_list(bot):
    return await bot.call_api('get_group_list')

# 为图片消息添加file_unique
def add_file_unique_for_image(msg):
    for seg in msg:
        if seg['type'] == 'image':
            if not 'file_unique' in seg['data']:
                url: str = seg['data'].get('url', '')
                start_idx = url.find('fileid=') + len('fileid=')
                if start_idx == -1: continue
                end_idx = url.find('&', start_idx)
                if end_idx == -1: end_idx = len(url)
                file_unique = url[start_idx:end_idx]
                seg['data']['file_unique'] = file_unique

# 获取完整消息对象
async def get_msg_obj(bot, message_id):
    msg_obj = await bot.call_api('get_msg', **{'message_id': int(message_id)})
    add_file_unique_for_image(msg_obj['message'])
    return msg_obj

# 获取消息段
async def get_msg(bot, message_id):
    return (await get_msg_obj(bot, message_id))['message']

# 获取陌生人信息
async def get_stranger_info(bot, user_id):
    return await bot.call_api('get_stranger_info', **{'user_id': int(user_id)})

# 获取头像url
def get_avatar_url(user_id):
    return f"http://q1.qlogo.cn/g?b=qq&nk={user_id}&s=100"

# 获取高清头像url
def get_avatar_url_large(user_id):
    return f"http://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"

# 下载头像（非异步）
def download_avatar(user_id, circle=False) -> Image.Image:
    url = get_avatar_url(user_id)
    response = requests.get(url)
    img = Image.open(io.BytesIO(response.content))
    if circle:
        r = img.width // 2
        circle_img = Image.new('L', (img.width, img.height), 0)
        draw = ImageDraw.Draw(circle_img)
        draw.ellipse((0, 0, r * 2, r * 2), fill=255)
        img.putalpha(circle_img)
    return img

# 获取群聊中的用户名 如果有群名片则返回群名片 否则返回昵称
async def get_group_member_name(bot, group_id, user_id):
    info = await bot.call_api('get_group_member_info', **{'group_id': int(group_id), 'user_id': int(user_id)})
    if 'card' in info and info['card']:
        return info['card']
    else:
        return info['nickname']

# 获取群聊中所有用户
async def get_group_users(bot, group_id):
    return await bot.call_api('get_group_member_list', **{'group_id': int(group_id)})

# 获取群聊名
async def get_group_name(bot, group_id):
    group_info = await bot.call_api('get_group_info', **{'group_id': int(group_id)})
    return group_info['group_name']

# 获取群聊信息
async def get_group(bot, group_id):
    return await bot.call_api('get_group_info', **{'group_id': int(group_id)})

# 解析消息段中的所有CQ码 返回格式为 ret["类型"]=[{CQ码1的字典}{CQ码2的字典}...]
def extract_cq_code(msg):
    ret = {}
    for seg in msg:
        if seg['type'] not in ret: ret[seg['type']] = []
        ret[seg['type']].append(seg['data'])
    return ret

# 是否包含图片
def has_image(msg):
    cqs = extract_cq_code(msg)
    return "image" in cqs and len(cqs["image"]) > 0

# 从消息段中提取所有图片链接
def extract_image_url(msg):
    cqs = extract_cq_code(msg)
    if "image" not in cqs or len(cqs["image"]) == 0: return []
    return [cq["url"] for cq in cqs["image"] if "url" in cq]

# 从消息段中提取所有图片id
def extract_image_id(msg):
    cqs = extract_cq_code(msg)
    if "image" not in cqs or len(cqs["image"]) == 0: return []
    return [cq["file"] for cq in cqs["image"] if "file" in cq]

# 从消息段提取所有@qq
def extract_at_qq(msg) -> List[int]:
    cqs = extract_cq_code(msg)
    if "at" not in cqs or len(cqs["at"]) == 0: return []
    return [int(cq["qq"]) for cq in cqs["at"] if "qq" in cq]

# 从消息段中提取文本
def extract_text(msg):
    cqs = extract_cq_code(msg)
    if "text" not in cqs or len(cqs["text"]) == 0: return ""
    return ' '.join([cq['text'] for cq in cqs["text"]])

# 从消息段提取带有特殊消息的文本
async def extract_special_text(msg, group_id=None):
    bot = get_bot()
    text = ""
    for seg in msg:
        if seg['type'] == 'text':
            text += seg['data']['text']
        elif seg['type'] == 'at':
            if group_id:
                name = await get_group_member_name(bot, group_id, seg['data']['qq'])
            else:
                name = await get_stranger_info(bot, seg['data']['qq'])['nickname']
            if text: text += " "
            text += f"@{name} "
        elif seg['type'] == 'image':
            text += f"[图片]"
        elif seg['type'] == 'face':
            text += f"[表情]"
        elif seg['type'] == 'video':
            text += f"[视频]"
        elif seg['type'] == 'file':
            text += f"[文件]"
        elif seg['type'] =='record':
            text += f"[语音]"
        elif seg['type'] =='mface':
            text += f"[表情]"
    return text
    
# 获取折叠消息
async def get_forward_msg(bot, forward_id):
    return await bot.call_api('get_forward_msg', **{'id': str(forward_id)})

# 从消息段获取回复的消息，如果没有回复则返回None
async def get_reply_msg(bot, msg):
    cqs = extract_cq_code(msg)
    if "reply" not in cqs or len(cqs["reply"]) == 0: return None
    reply_id = cqs["reply"][0]["id"]
    return await get_msg(bot, reply_id)

# 从消息段获取完整的回复消息对象，如果没有回复则返回None
async def get_reply_msg_obj(bot, msg):
    cqs = extract_cq_code(msg)
    if "reply" not in cqs or len(cqs["reply"]) == 0: return None
    reply_id = cqs["reply"][0]["id"]
    return await get_msg_obj(bot, reply_id)


# 获取图片的cq码用于发送
async def get_image_cq(
    image: Union[str, Image.Image, bytes],
    allow_error: bool = False, 
    logger: Logger = None, 
    low_quality: bool = False, 
    quality: int = 75,
):
    args = (allow_error, logger, low_quality, quality)
    try:
        # 如果是远程图片
        if isinstance(image, str) and image.startswith("http"):
            image = await download_image(image)
            return await get_image_cq(image, *args)
        # 如果是bytes
        if isinstance(image, bytes):
            image = Image.open(io.BytesIO(image))
            return await get_image_cq(image, *args)
        # 如果是本地路径
        if isinstance(image, str):
            if not os.path.exists(image):
                raise Exception(f'图片文件不存在: {image}')
            image = open_image(image)
            return await get_image_cq(image, *args)

        is_gif_img = is_gif(image) or image.mode == 'P'
        ext = 'gif' if is_gif_img else ('jpg' if low_quality else 'png')
        with TempFilePath(ext) as tmp_path:
            if ext == 'gif':
                save_transparent_gif(get_frames_from_gif(image), get_gif_duration(image), tmp_path)
            elif ext == 'jpg':
                image = image.convert('RGB')
                image.save(tmp_path, format='JPEG', quality=quality, optimize=True, subsampling=1, progressive=True)
            else:
                image.save(tmp_path)
            
            with open(tmp_path, 'rb') as f:
                return f'[CQ:image,file=base64://{base64.b64encode(f.read()).decode()}]'

    except Exception as e:
        if allow_error: 
            (logger or utils_logger).print_exc(f'图片加载失败: {e}')
            return f"[图片加载失败:{truncate(str(e), 16)}]"
        raise e

# 获取音频的cq码用于发送
def get_audio_cq(audio_path):
    with open(audio_path, 'rb') as f:
        return f'[CQ:record,file=base64://{base64.b64encode(f.read()).decode()}]'


async def download_napcat_file(ftype: str, file: str) -> str:
    """
    下载napcat文件，返回本地路径
    """
    bot = get_bot()
    if ftype == 'image':
        ret = await bot.call_api('get_image', **{'file': file})
    elif ftype == 'record':
        ret = await bot.call_api('get_record', **{'file': file, 'out_format': 'wav'})
    else:
        ret = await bot.call_api('get_file', **{'file': file})
    return ret['file']

class TempNapcatFilePath:
    def __init__(self, ftype: str, file: str):
        self.ftype = ftype
        self.file = file
        self.ext = file.split('.')[-1]

    async def __aenter__(self) -> str:
        path = await download_napcat_file(self.ftype, self.file)
        self.path = path
        return path
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        remove_file(self.path)



# ============================ 聊天检查 ============================ #
        
# 是否是群聊消息
def is_group_msg(event):
    return hasattr(event, 'group_id') and event.group_id is not None

# 检查是否加入了某个群
async def check_in_group(bot, group_id):
    return int(group_id) in await get_group_id_list(bot)

# 用户是否在黑名单
def check_in_blacklist(user_id):
    blacklist = utils_file_db.get('blacklist', [])
    return int(user_id) in blacklist

# 检查群聊是否被全局禁用
def check_group_disabled(group_id):
    enabled_groups = utils_file_db.get('enabled_groups', [])
    return int(group_id) not in enabled_groups

# 通过event检查群聊是否被全局禁用
def check_group_disabled_by_event(event):
    if is_group_msg(event) and check_group_disabled(event.group_id):
        utils_logger.warning(f'取消发送消息到被全局禁用的群 {event.group_id}')
        return True
    return False

# 设置群聊全局启用状态
def set_group_enable(group_id, enable):
    enabled_groups = utils_file_db.get('enabled_groups', [])
    if enable:
        if int(group_id) not in enabled_groups:
            enabled_groups.append(int(group_id))
    else:
        if int(group_id) in enabled_groups:
            enabled_groups.remove(int(group_id))
    utils_file_db.set('enabled_groups', enabled_groups)
    utils_logger.info(f'设置群聊 {group_id} 全局启用状态为 {enable}')

# 检查是否是bot自身
def check_self(event):
    return event.user_id == event.self_id

# 检查是否是超级用户
def check_superuser(event, superuser=SUPERUSER):
    if superuser is None: return False
    return event.user_id in superuser

# 检查是否是自身对指令的回复
def check_self_reply(event):
    return int(event.message_id) in bot_reply_msg_ids



# ============================ 消息发送 ============================ #

SEND_MSG_DAILY_LIMIT = 4000

# 检查是否超过全局发送消息上限
def check_send_msg_daily_limit() -> bool:
    date = datetime.now().strftime("%Y-%m-%d")
    send_msg_count = utils_file_db.get('send_msg_count', {})
    count = send_msg_count.get('count', 0)
    if send_msg_count.get('date', '') != date:
        send_msg_count = {'date': date, 'count': 0}
        utils_file_db.set('send_msg_count', send_msg_count)
        count = 0
    return count < SEND_MSG_DAILY_LIMIT

# 记录消息发送
def record_daily_msg_send():
    date = datetime.now().strftime("%Y-%m-%d")
    send_msg_count = utils_file_db.get('send_msg_count', {})
    count = send_msg_count.get('count', 0)
    if send_msg_count.get('date', '') != date:
        send_msg_count = {'date': date, 'count': 0}
        utils_file_db.set('send_msg_count', send_msg_count)
        count = 0
    count += 1
    send_msg_count['count'] = count
    utils_file_db.set('send_msg_count', send_msg_count)
    if count == SEND_MSG_DAILY_LIMIT:
        utils_logger.warning(f'达到每日发送消息上限 {SEND_MSG_DAILY_LIMIT}')

# 获取当日发送消息数量
def get_send_msg_daily_count() -> int:
    date = datetime.now().strftime("%Y-%m-%d")
    send_msg_count = utils_file_db.get('send_msg_count', {})
    count = send_msg_count.get('count', 0)
    if send_msg_count.get('date', '') != date:
        send_msg_count = {'date': date, 'count': 0}
        utils_file_db.set('send_msg_count', send_msg_count)
        count = 0
    return count


bot_reply_msg_ids = set()
MSG_RATE_LIMIT_PER_SECOND = get_config()['msg_rate_limit_per_second']
current_msg_count = 0
current_msg_second = -1
send_msg_failed_last_mail_time = datetime.fromtimestamp(0)
send_msg_failed_mail_interval = timedelta(minutes=10)

# 发送消息装饰器
def send_msg_func(func):
    async def wrapper(*args, **kwargs):
        # 检查消息发送次数限制
        cur_ts = int(datetime.now().timestamp())
        global current_msg_count, current_msg_second
        if cur_ts != current_msg_second:
            current_msg_count = 0
            current_msg_second = cur_ts
        if current_msg_count >= MSG_RATE_LIMIT_PER_SECOND:
            utils_logger.warning(f'消息达到发送频率，取消消息发送')
            return
        current_msg_count += 1
        
        try:
            ret = await func(*args, **kwargs)
        except Exception as e:
            # 失败发送邮件通知
            global send_msg_failed_last_mail_time
            if datetime.now() - send_msg_failed_last_mail_time > send_msg_failed_mail_interval:
                send_msg_failed_last_mail_time = datetime.now()
                asyncio.create_task(asend_exception_mail("消息发送失败", traceback.format_exc(), utils_logger))
            raise

        # 记录自身对指令的回复消息id集合
        try:
            if ret:
                global bot_reply_msg_ids
                bot_reply_msg_ids.add(int(ret["message_id"]))
        except Exception as e:
            utils_logger.print_exc(f'记录发送消息的id失败')

        # 记录消息发送次数
        record_daily_msg_send()
            
        return ret
        
    return wrapper
    
# 发送消息
@send_msg_func
async def send_msg(handler, event, message):
    if check_group_disabled_by_event(event): return None
    return await handler.send(OutMessage(message))

# 发送回复消息
@send_msg_func
async def send_reply_msg(handler, event, message):
    if check_group_disabled_by_event(event): return None
    return await handler.send(OutMessage(f'[CQ:reply,id={event.message_id}]{message}'))

# 发送at消息
@send_msg_func
async def send_at_msg(handler, event, message):
    if check_group_disabled_by_event(event): return None
    return await handler.send(OutMessage(f'[CQ:at,qq={event.user_id}]{message}'))

# 发送折叠消息失败的fallback
async def fold_msg_fallback(bot, group_id, contents, e, method):
    utils_logger.warning(f'发送折叠消息失败，fallback为发送普通消息: {get_exc_desc(e)}')
    if method == 'seperate':
        contents[0] = "（发送折叠消息失败）\n" + contents[0]
        for content in contents:
            ret = await send_group_msg_by_bot(bot, group_id, content)
    elif method == 'join_newline':
        contents = ["（发送折叠消息失败）"] + contents
        msg = "\n".join(contents)
        ret = await send_group_msg_by_bot(bot, group_id, msg)
    elif method == 'join':
        contents = ["（发送折叠消息失败）\n"] + contents
        msg = "".join(contents)
        ret = await send_group_msg_by_bot(bot, group_id, msg)
    elif method == 'none':
        ret = await send_group_msg_by_bot(bot, group_id, "发送折叠消息失败")
    else:
        raise Exception(f'未知折叠消息fallback方法 {method}')
    return ret

# 发送群聊折叠消息 其中contents是text的列表
@send_msg_func
async def send_group_fold_msg(bot, group_id, contents, fallback_method='none'):
    if check_group_disabled(group_id):
        utils_logger.warning(f'取消发送消息到被全局禁用的群 {group_id}')
        return
    msg_list = [{
        "type": "node",
        "data": {
            "user_id": bot.self_id,
            "nickname": BOT_NAME,
            "content": content
        }
    } for content in contents]
    try:
        return await bot.send_group_forward_msg(group_id=group_id, messages=msg_list)
    except Exception as e:
        return await fold_msg_fallback(bot, group_id, contents, e, fallback_method)

# 发送多条消息折叠消息
@send_msg_func
async def send_multiple_fold_msg(bot, event, contents, fallback_method='none'):
    if check_group_disabled_by_event(event): return None
    msg_list = [{
        "type": "node",
        "data": {
            "user_id": bot.self_id,
            "nickname": BOT_NAME,
            "content": content
        }
    } for content in contents if content]
    if is_group_msg(event):
        try:
            return await bot.send_group_forward_msg(group_id=event.group_id, messages=msg_list)
        except Exception as e:
            return await fold_msg_fallback(bot, event.group_id, contents, e, fallback_method)
    else:
        return await bot.send_private_forward_msg(user_id=event.user_id, messages=msg_list)
    
# 在event外发送群聊消息
@send_msg_func
async def send_group_msg_by_bot(bot, group_id, message):
    if check_group_disabled(group_id):
        utils_logger.warning(f'取消发送消息到被全局禁用的群 {group_id}')
        return
    if not await check_in_group(bot, group_id):
        utils_logger.warning(f'取消发送消息到未加入的群 {group_id}')
        return
    return await bot.send_group_msg(group_id=int(group_id), message=message)

# 在event外发送私聊消息
@send_msg_func
async def send_private_msg_by_bot(bot, user_id, message):
    return await bot.send_private_msg(user_id=int(user_id), message=message)

# 在event外发送多条消息折叠消息
@send_msg_func
async def send_multiple_fold_msg_by_bot(bot, group_id, contents, fallback_method='none'):
    if check_group_disabled(group_id):
        utils_logger.warning(f'取消发送消息到被全局禁用的群 {group_id}')
        return
    msg_list = [{
        "type": "node",
        "data": {
            "user_id": bot.self_id,
            "nickname": BOT_NAME,
            "content": content
        }
    } for content in contents if content]
    try:
        return await bot.send_group_forward_msg(group_id=group_id, messages=msg_list)
    except Exception as e:
        return await fold_msg_fallback(bot, group_id, contents, e, fallback_method)

# 根据消息长度以及是否是群聊消息来判断是否需要折叠消息
async def send_fold_msg_adaptive(bot, handler, event, message, threshold=200, need_reply=True, text_len=None, fallback_method='none'):
    if text_len is None: 
        text_len = get_str_display_length(message)
    if is_group_msg(event) and text_len > threshold:
        return await send_group_fold_msg(bot, event.group_id, [event.get_plaintext(), message], fallback_method)
    if need_reply:
        return await send_reply_msg(handler, event, message)
    return await send_msg(handler, event, message)



# ============================ 聊天控制 ============================ #

CD_VERBOSE_INTERVAL = get_config()['cd_verbose_interval']

# 冷却时间
class ColdDown:
    def __init__(self, db, logger, default_interval, superuser=SUPERUSER, cold_down_name=None, group_seperate=False):
        self.default_interval = default_interval
        self.superuser = superuser
        self.db = db
        self.logger = logger
        self.group_seperate = group_seperate
        self.cold_down_name = f'cold_down' if cold_down_name is None else f'cold_down_{cold_down_name}'
    
    async def check(self, event, interval=None, allow_super=True, verbose=True):
        if allow_super and check_superuser(event, self.superuser):
            self.logger.debug(f'{self.cold_down_name}检查: 超级用户{event.user_id}')
            return True
        if interval is None: interval = self.default_interval
        key = str(event.user_id)
        if isinstance(event, GroupMessageEvent) and self.group_seperate:
            key = f'{event.group_id}-{key}'
        last_use = self.db.get(self.cold_down_name, {})
        now = datetime.now().timestamp()
        if key not in last_use:
            last_use[key] = now
            self.db.set(self.cold_down_name, last_use)
            self.logger.debug(f'{self.cold_down_name}检查: {key} 未使用过')
            return True
        if now - last_use[key] < interval:
            self.logger.debug(f'{self.cold_down_name}检查: {key} CD中')
            if verbose:
                try:
                    verbose_key = f'verbose_{key}'
                    if verbose_key not in last_use:
                        last_use[verbose_key] = 0
                    if now - last_use[verbose_key] > CD_VERBOSE_INTERVAL:
                        last_use[verbose_key] = now
                        self.db.set(self.cold_down_name, last_use)
                        rest_time = timedelta(seconds=interval - (now - last_use[key]))
                        verbose_msg = f'冷却中, 剩余时间: {get_readable_timedelta(rest_time)}'
                        if hasattr(event, 'message_id'):
                            if hasattr(event, 'group_id'):
                                await send_group_msg_by_bot(get_bot(), event.group_id, f'[CQ:reply,id={event.message_id}] {verbose_msg}')
                            else:
                                await send_private_msg_by_bot(get_bot(), event.user_id, f'[CQ:reply,id={event.message_id}] {verbose_msg}')
                except Exception as e:
                    self.logger.print_exc(f'{self.cold_down_name}检查: {key} CD中, 发送冷却中消息失败')
            return False
        last_use[key] = now
        self.db.set(self.cold_down_name, last_use)
        self.logger.debug(f'{self.cold_down_name}检查: {key} 通过')
        return True

    def get_last_use(self, user_id, group_id=None):
        key = f'{group_id}-{user_id}' if group_id else str(user_id)
        last_use = self.db.get(self.cold_down_name, {})
        if key not in last_use:
            return None
        return datetime.fromtimestamp(last_use[key])


# 频率限制
class RateLimit:
    def __init__(self, db, logger, limit, period_type, superuser=SUPERUSER, rate_limit_name=None, group_seperate=False):
        """
        period_type: "minute", "hour", "day" or "m", "h", "d"
        """
        self.limit = limit
        self.period_type = period_type[:1]
        if self.period_type not in ['m', 'h', 'd']:
            raise Exception(f'未知的时间段类型 {self.period_type}')
        self.superuser = superuser
        self.db = db
        self.logger = logger
        self.group_seperate = group_seperate
        self.rate_limit_name = f'default' if rate_limit_name is None else f'{rate_limit_name}'

    def get_period_time(self, t):
        if self.period_type == "m":
            return t.replace(second=0, microsecond=0)
        if self.period_type == "h":
            return t.replace(minute=0, second=0, microsecond=0)
        if self.period_type == "d":
            return t.replace(hour=0, minute=0, second=0, microsecond=0)
        raise Exception(f'未知的时间段类型 {self.period_type}')

    async def check(self, event, allow_super=True, verbose=True):
        if allow_super and check_superuser(event, self.superuser):
            self.logger.debug(f'{self.rate_limit_name}检查: 超级用户{event.user_id}')
            return True
        key = str(event.user_id)
        if isinstance(event, GroupMessageEvent) and self.group_seperate:
            key = f'{event.group_id}-{key}'
        last_check_time_key = f'last_check_time_{self.rate_limit_name}'
        count_key = f"rate_limit_count_{self.rate_limit_name}"
        last_check_time = datetime.fromtimestamp(self.db.get(last_check_time_key, 0))
        count = self.db.get(count_key, {})
        if self.get_period_time(datetime.now()) > self.get_period_time(last_check_time):
            count = {}
            self.logger.debug(f'{self.rate_limit_name}检查: 额度已重置')
        if count.get(key, 0) >= self.limit:
            self.logger.debug(f'{self.rate_limit_name}检查: {key} 频率超限')
            if verbose:
                reply_msg = "达到{period}使用次数限制({limit})"
                if self.period_type == "m":
                    reply_msg = reply_msg.format(period="分钟", limit=self.limit)
                elif self.period_type == "h":
                    reply_msg = reply_msg.format(period="小时", limit=self.limit)
                elif self.period_type == "d":
                    reply_msg = reply_msg.format(period="天", limit=self.limit)
                try:
                    if hasattr(event, 'message_id'):
                        if hasattr(event, 'group_id'):
                            await send_group_msg_by_bot(get_bot(), event.group_id, f'[CQ:reply,id={event.message_id}] {reply_msg}')
                        else:
                            await send_private_msg_by_bot(get_bot(), event.user_id, f'[CQ:reply,id={event.message_id}] {reply_msg}')
                except Exception as e:
                    self.logger.print_exc(f'{self.rate_limit_name}检查: {key} 频率超限, 发送频率超限消息失败')
            ok = False
        else:
            count[key] = count.get(key, 0) + 1
            self.logger.debug(f'{self.rate_limit_name}检查: {key} 通过 当前次数 {count[key]}/{self.limit}')
            ok = True
        self.db.set(count_key, count)
        self.db.set(last_check_time_key, datetime.now().timestamp())
        return ok
        

# 群白名单：默认关闭
class GroupWhiteList:
    def __init__(self, db, logger, name, superuser=SUPERUSER, on_func=None, off_func=None):
        self.superuser = superuser
        self.name = name
        self.logger = logger
        self.db = db
        self.white_list_name = f'group_white_list_{name}'
        self.on_func = on_func
        self.off_func = off_func

        # 开启命令
        switch_on = on_command(f'/{name}_on', block=False, priority=100)
        @switch_on.handle()
        async def _(event: GroupMessageEvent, superuser=self.superuser, name=self.name, 
                    white_list_name=self.white_list_name):
            if not check_superuser(event, superuser):
                logger.log(f'{event.user_id} 无权限开启 {name}')
                return
            group_id = event.group_id
            white_list = db.get(white_list_name, [])
            if group_id in white_list:
                return await send_reply_msg(switch_on, event, f'{name}已经是开启状态')
            white_list.append(group_id)
            db.set(white_list_name, white_list)
            if self.on_func is not None: await self.on_func(event.group_id)
            return await send_reply_msg(switch_on, event, f'{name}已开启')
        
        # 关闭命令
        switch_off = on_command(f'/{name}_off', block=False, priority=100)
        @switch_off.handle()
        async def _(event: GroupMessageEvent, superuser=self.superuser, name=self.name, 
                    white_list_name=self.white_list_name):
            if not check_superuser(event, superuser):
                logger.info(f'{event.user_id} 无权限关闭 {name}')
                return
            group_id = event.group_id
            white_list = db.get(white_list_name, [])
            if group_id not in white_list:
                return await send_reply_msg(switch_off, event, f'{name}已经是关闭状态')
            white_list.remove(group_id)
            db.set(white_list_name, white_list)
            if self.off_func is not None:  await self.off_func(event.group_id)
            return await send_reply_msg(switch_off, event, f'{name}已关闭')
            
        # 查询命令
        switch_query = on_command(f'/{name}_status', block=False, priority=100)
        @switch_query.handle()
        async def _(event: GroupMessageEvent, superuser=self.superuser, name=self.name, 
                    white_list_name=self.white_list_name):
            if not check_superuser(event, superuser):
                logger.info(f'{event.user_id} 无权限查询 {name}')
                return
            group_id = event.group_id
            white_list = db.get(white_list_name, [])
            if group_id in white_list:
                return await send_reply_msg(switch_query, event, f'{name}开启中')
            else:
                return await send_reply_msg(switch_query, event, f'{name}关闭中')
            

    def get(self):
        return self.db.get(self.white_list_name, [])
    
    def add(self, group_id):
        white_list = self.db.get(self.white_list_name, [])
        if group_id in white_list:
            return False
        white_list.append(group_id)
        self.db.set(self.white_list_name, white_list)
        self.logger.info(f'添加群 {group_id} 到 {self.white_list_name}')
        if self.on_func is not None: self.on_func(group_id)
        return True
    
    def remove(self, group_id):
        white_list = self.db.get(self.white_list_name, [])
        if group_id not in white_list:
            return False
        white_list.remove(group_id)
        self.db.set(self.white_list_name, white_list)
        self.logger.info(f'从 {self.white_list_name} 删除群 {group_id}')
        if self.off_func is not None: self.off_func(group_id)
        return True
            
    def check_id(self, group_id):
        white_list = self.db.get(self.white_list_name, [])
        self.logger.debug(f'白名单{self.white_list_name}检查{group_id}: {"允许通过" if group_id in white_list else "不允许通过"}')
        return group_id in white_list

    def check(self, event, allow_private=False, allow_super=False):
        if is_group_msg(event):
            if allow_super and check_superuser(event, self.superuser): 
                self.logger.debug(f'白名单{self.white_list_name}检查: 允许超级用户{event.user_id}')
                return True
            return self.check_id(event.group_id)
        self.logger.debug(f'白名单{self.white_list_name}检查: {"允许私聊" if allow_private else "不允许私聊"}')
        return allow_private
    
    
# 群黑名单：默认开启
class GroupBlackList:
    def __init__(self, db, logger, name, superuser=SUPERUSER, on_func=None, off_func=None):
        self.superuser = superuser
        self.name = name
        self.logger = logger
        self.db = db
        self.black_list_name = f'group_black_list_{name}'
        self.on_func = on_func
        self.off_func = off_func

        # 关闭命令
        off = on_command(f'/{name}_off', block=False, priority=100)
        @off.handle()
        async def _(event: GroupMessageEvent, superuser=self.superuser, name=self.name, 
                    black_list_name=self.black_list_name):
            if not check_superuser(event, superuser):
                logger.info(f'{event.user_id} 无权限关闭 {name}')
                return
            group_id = event.group_id
            black_list = db.get(black_list_name, [])
            if group_id in black_list:
                return await send_reply_msg(off, event, f'{name}已经是关闭状态')
            black_list.append(group_id)
            db.set(black_list_name, black_list)
            if self.off_func is not None: await self.off_func(event.group_id)
            return await send_reply_msg(off, event, f'{name}已关闭')
        
        # 开启命令
        on = on_command(f'/{name}_on', block=False, priority=100)
        @on.handle()
        async def _(event: GroupMessageEvent, superuser=self.superuser, name=self.name, 
                    black_list_name=self.black_list_name):
            if not check_superuser(event, superuser):
                logger.info(f'{event.user_id} 无权限开启 {name}')
                return
            group_id = event.group_id
            black_list = db.get(black_list_name, [])
            if group_id not in black_list:
                return await send_reply_msg(on, event, f'{name}已经是开启状态')
            black_list.remove(group_id)
            db.set(black_list_name, black_list)
            if self.on_func is not None: await self.on_func(event.group_id)
            return await send_reply_msg(on, event, f'{name}已开启')
            
        # 查询命令
        query = on_command(f'/{name}_status', block=False, priority=100)
        @query.handle()
        async def _(event: GroupMessageEvent, superuser=self.superuser, name=self.name, 
                    black_list_name=self.black_list_name):
            if not check_superuser(event, superuser):
                logger.info(f'{event.user_id} 无权限查询 {name}')
                return
            group_id = event.group_id
            black_list = db.get(black_list_name, [])
            if group_id in black_list:
                return await send_reply_msg(query, event, f'{name}关闭中')
            else:
                return await send_reply_msg(query, event, f'{name}开启中')
        
    def get(self):
        return self.db.get(self.black_list_name, [])
    
    def add(self, group_id):
        black_list = self.db.get(self.black_list_name, [])
        if group_id in black_list:
            return False
        black_list.append(group_id)
        self.db.set(self.black_list_name, black_list)
        self.logger.info(f'添加群 {group_id} 到 {self.black_list_name}')
        if self.off_func is not None: self.off_func(group_id)
        return True
    
    def remove(self, group_id):
        black_list = self.db.get(self.black_list_name, [])
        if group_id not in black_list:
            return False
        black_list.remove(group_id)
        self.db.set(self.black_list_name, black_list)
        self.logger.info(f'从 {self.black_list_name} 删除群 {group_id}')
        if self.on_func is not None: self.on_func(group_id)
        return True
    
    def check_id(self, group_id):
        black_list = self.db.get(self.black_list_name, [])
        self.logger.debug(f'黑名单{self.black_list_name}检查{group_id}: {"允许通过" if group_id not in black_list else "不允许通过"}')
        return group_id not in black_list
    
    def check(self, event, allow_private=False, allow_super=False):
        if is_group_msg(event):
            if allow_super and check_superuser(event, self.superuser): 
                self.logger.debug(f'黑名单{self.black_list_name}检查: 允许超级用户{event.user_id}')
                return True
            self.logger.debug(f'黑名单{self.black_list_name}检查: {"允许通过" if self.check_id(event.group_id) else "不允许通过"}')
            return self.check_id(event.group_id)
        self.logger.debug(f'黑名单{self.black_list_name}检查: {"允许私聊" if allow_private else "不允许私聊"}')
        return allow_private
    

_gwls: Dict[str, GroupWhiteList] = {}
def get_group_white_list(db, logger, name, superuser=SUPERUSER, on_func=None, off_func=None, is_service=True) -> GroupWhiteList:
    if is_service:
        global _gwls
        if name not in _gwls:
            _gwls[name] = GroupWhiteList(db, logger, name, superuser, on_func, off_func)
        return _gwls[name]
    return GroupWhiteList(db, logger, name, superuser, on_func, off_func)

_gbls: Dict[str, GroupBlackList] = {}
def get_group_black_list(db, logger, name, superuser=SUPERUSER, on_func=None, off_func=None, is_service=True) -> GroupBlackList:
    if is_service:
        global _gbls
        if name not in _gbls:
            _gbls[name] = GroupBlackList(db, logger, name, superuser, on_func, off_func)
        return _gbls[name]
    return GroupBlackList(db, logger, name, superuser, on_func, off_func)



# ============================ 聊天处理 ============================ #

# 不会触发消息回复的Exception，用于退出当前Event
class NoReplyException(Exception):
    pass

# 触发特定消息回复并且不会折叠的Exception，用于退出当前Event
class ReplyException(Exception):
    pass

def assert_and_reply(condition, msg):
    if not condition:
        raise ReplyException(msg)

# 适用于HandlerContext的参数解析器
class MessageArgumentParser(ArgumentParser):
    def __init__(self, ctx, *args, **kwargs):
        super().__init__(*args, **kwargs, exit_on_error=False)
        self.ctx = ctx

    def error(self, message):
        raise Exception(message)

    async def parse_args(self, error_reply=None, *args, **kwargs):
        try:
            s = self.ctx.get_args().strip().split()
            return super().parse_args(s, *args, **kwargs)
        except Exception as e:
            self.ctx.logger.print_exc("参数解析失败")
            if error_reply is None:
                raise e
            else:
                await self.ctx.asend_msg(error_reply)
                raise NoReplyException()

@dataclass
class HandlerContext:
    time: datetime = None
    handler: "CmdHandler" = None
    nonebot_handler: Any = None
    bot: Bot = None
    event: MessageEvent = None
    trigger_cmd: str = None
    arg_text: str = None
    message_id: int = None
    user_id: int = None
    group_id: int = None
    logger: Logger = None
    block_ids: List[str] = field(default_factory=list)

    # --------------------------  数据获取 -------------------------- #

    def get_args(self) -> str:
        return self.arg_text

    def get_argparser(self) -> MessageArgumentParser:
        return MessageArgumentParser(self)

    def aget_msg(self):
        return get_msg(self.bot, self.message_id)

    def aget_msg_obj(self):
        return get_msg_obj(self.bot, self.message_id)
    
    async def aget_reply_msg(self):
        return await get_reply_msg(self.bot, await self.aget_msg())
    
    async def aget_reply_msg_obj(self):
        return await get_reply_msg_obj(self.bot, await self.aget_msg())
    
    # -------------------------- 消息发送 -------------------------- # 

    def asend_msg(self, msg: str):
        return send_msg(self.nonebot_handler, self.event, msg)

    def asend_reply_msg(self, msg: str):
        return send_reply_msg(self.nonebot_handler, self.event, msg)

    def asend_at_msg(self, msg: str):
        return send_at_msg(self.nonebot_handler, self.event, msg)

    def asend_fold_msg_adaptive(self, msg: str, threshold=200, need_reply=True, text_len=None, fallback_method='none'):
        return send_fold_msg_adaptive(self.bot, self.nonebot_handler, self.event, msg, threshold, need_reply, text_len, fallback_method)

    async def asend_multiple_fold_msg(self, msgs: List[str], show_cmd=True, fallback_method='none'):
        if show_cmd:
            cmd_msg = self.trigger_cmd + self.arg_text
            if self.group_id:
                user_name = await get_group_member_name(self.bot, self.group_id, self.user_id)
                cmd_msg = f'{user_name}: {cmd_msg}'
            msgs = [cmd_msg] + msgs
        return await send_multiple_fold_msg(self.bot, self.event, msgs, fallback_method)

    # -------------------------- 其他 -------------------------- # 

    async def block(self, block_id: str = "", timeout: int = 3 * 60, err_msg: str = None):
        block_id = str(block_id)
        block_start_time = datetime.now()
        while True:
            if block_id not in self.handler.block_set:
                break
            if (datetime.now() - block_start_time).seconds > timeout:
                if err_msg is None:
                    err_msg = f'指令执行繁忙(block_id={block_id})，请稍后再试'
                raise ReplyException(err_msg)
            await asyncio.sleep(1)
        self.handler.block_set.add(block_id)
        self.block_ids.append(block_id)

@dataclass
class HelpDocCmdPart:
    doc_name: str
    cmds: Set[str] = None
    content: str = ""
    md5: str = "",

@dataclass
class HelpDoc:
    mtime: int
    parts: List[HelpDocCmdPart] = field(default_factory=list)

_cmd_history: List[HandlerContext] = []
MAX_CMD_HISTORY = 100

class CmdHandler:
    HELP_PART_IMG_CACHE_DIR = "data/utils/help_part_img_cache/"
    help_docs: Dict[str, HelpDoc] = {}

    def __init__(
            self, 
            commands: List[str], 
            logger: Logger, 
            error_reply=True, 
            priority=100, 
            block=True, 
            only_to_me=False, 
            disabled=False, 
            banned_cmds: List[str] = None, 
            check_group_enabled=True,
            allow_bot_reply_msg=False,
            help_command: str=None,
            disable_help = False,
            help_trigger_condition: Union[str, Callable] = 'exact',
        ):
        if isinstance(commands, str):
            commands = [commands]
        self.commands = commands
        self.logger = logger
        self.error_reply = error_reply
        self.check_group_enabled = check_group_enabled
        handler_kwargs = {}
        if only_to_me: handler_kwargs["rule"] = rule_to_me()
        self.handler = on_command(commands[0], priority=priority, block=block, aliases=set(commands[1:]), **handler_kwargs)
        self.superuser_check = None
        self.private_group_check = None
        self.wblist_checks = []
        self.cdrate_checks = []
        self.disabled = disabled
        self.banned_cmds = banned_cmds or []
        if isinstance(self.banned_cmds, str):
            self.banned_cmds = [self.banned_cmds]
        self.block_set = set()
        self.allow_bot_reply_msg = allow_bot_reply_msg
        self.help_command = help_command
        self.disable_help = disable_help
        if isinstance(help_trigger_condition, str):
            assert help_trigger_condition in ['contain', 'exact']
        self.help_trigger_condition = help_trigger_condition
        # utils_logger.info(f'注册指令 {commands[0]}')

    def check_group(self):
        self.private_group_check = "group"
        return self
    
    def check_private(self):
        self.private_group_check = "private"
        return self

    def check_wblist(self, wblist: GroupWhiteList | GroupBlackList, allow_private=True, allow_super=False):
        self.wblist_checks.append((wblist, { "allow_private": allow_private, "allow_super": allow_super }))
        return self

    def check_cdrate(self, cd_rate: ColdDown | RateLimit, allow_super=True, verbose=True):
        self.cdrate_checks.append((cd_rate, { "allow_super": allow_super, "verbose": verbose }))
        return self

    def check_superuser(self, superuser=SUPERUSER):
        self.superuser_check = { "superuser": superuser }
        return self

    @classmethod
    def update_help_docs(cls):
        """
        更新帮助文档列表
        """
        HELP_DOC_PATH = "helps/*.md"
        paths = list(glob.glob(HELP_DOC_PATH))
        names = set()
        all_md5 = set()

        def parse_doc(path: str) -> List[HelpDocCmdPart]:
            help_doc = Path(path).read_text(encoding="utf-8")
            doc_name = Path(path).stem
            parts = help_doc.split("---")[2:-1] # 每个小标题
            ret: List[HelpDocCmdPart] = []   # 每个指令的部分
            for part in parts:
                start = part.find("### ")   
                if start == -1:  continue
                part = part[start:]
                for p in part.split("### "):
                    p = p.strip()
                    if p:
                        ret.append(HelpDocCmdPart(
                            cmds=None,
                            doc_name=doc_name, 
                            content="### " + p + f"\n\n>发送`/help {doc_name}`查看完整帮助",
                        ))
            for part in ret:
                lines = part.content.splitlines()
                if len(lines) < 2: continue
                start = lines[1].find("`")
                if start == -1: continue
                part.cmds = set(lines[1][start:].replace("` `", "%").replace("`", "").strip().split("%"))
                part.md5 = get_md5(part.content)
                # print(f"解析帮助: {part.doc_name} {part.cmds} {truncate(part.content, 50)}")
            return ret

        for path in paths:
            try:
                name = Path(path).stem
                mtime = int(os.path.getmtime(path))
                if name not in cls.help_docs or cls.help_docs[name].mtime < mtime:
                    cls.help_docs[name] = HelpDoc(mtime=mtime)
                    cls.help_docs[name].parts = parse_doc(path)
                names.add(name)
            except:
                utils_logger.print_exc(f"解析帮助文档 {path} 失败")

        for name in list(cls.help_docs.keys()):
            if name not in names:
                del cls.help_docs[name]

        # 删除不在帮助文档中的缓存图片
        for doc in cls.help_docs.values():
            for part in doc.parts:
                if part.md5:
                    all_md5.add(part.md5)
        for path in glob.glob(os.path.join(cls.HELP_PART_IMG_CACHE_DIR, "*.png")):
            name = Path(path).stem
            if name not in all_md5:
                try: 
                    os.remove(path)
                except Exception as e:
                    utils_logger.print_exc(f"删除帮助文档图片缓存 {path} 失败: {e}")
        
    @classmethod
    def find_cmd_help_doc(cls, cmd: str) -> Optional[HelpDocCmdPart]:
        cls.update_help_docs()
        for doc in cls.help_docs.values():
            for part in doc.parts:
                if part.cmds and cmd in part.cmds:
                    return part
        return None

    @classmethod
    async def get_cmd_help_doc_img(cls, part: HelpDocCmdPart, width=600) -> Image.Image:
        md5 = get_md5(part.content)
        cache_path = create_parent_folder(os.path.join(cls.HELP_PART_IMG_CACHE_DIR, f"{md5}.png"))
        if os.path.exists(cache_path):
            return open_image(cache_path)
        img = await markdown_to_image(part.content, width=width)
        img.save(cache_path)
        return img
 
    async def additional_context_process(self, context: HandlerContext):
        return context

    def handle(self):
        def decorator(handler_func):
            @self.handler.handle()
            async def func(bot: Bot, event: MessageEvent):
                # utils_logger.info(f'Handler {self.commands[0]} 收到指令: {event.message.extract_plain_text()}')

                if self.disabled:
                    return

                # 禁止私聊自己的指令生效
                if not is_group_msg(event) and event.user_id == event.self_id:
                    self.logger.warning(f'取消私聊自己的指令处理')
                    return
                
                # 禁止bot回复自己的消息重复触发
                if not self.allow_bot_reply_msg and event.message_id in bot_reply_msg_ids:
                    return
                
                # 检测群聊是否启用
                if self.check_group_enabled and is_group_msg(event) and check_group_disabled(event.group_id):
                    # self.logger.warning(f'取消未启用群聊 {event.group_id} 的指令处理')
                    return

                # 检测黑名单
                if check_in_blacklist(event.user_id):
                    self.logger.warning(f'取消黑名单用户 {event.user_id} 的指令处理')
                    return

                # 权限检查
                if self.private_group_check == "group" and not is_group_msg(event):
                    return
                if self.private_group_check == "private" and is_group_msg(event):
                    return
                if self.superuser_check and not check_superuser(event, **self.superuser_check):
                    return
                for wblist, kwargs in self.wblist_checks:
                    if not wblist.check(event, **kwargs):
                        return

                # 每日上限检查
                if not check_send_msg_daily_limit() and not check_superuser(event, **self.superuser_check):
                    return

                # cd检查
                for cdrate, kwargs in self.cdrate_checks:
                    if not (await cdrate.check(event, **kwargs)):
                        return

                # 上下文构造
                context = HandlerContext()
                context.time = datetime.now()
                context.handler = self
                context.nonebot_handler = self.handler
                context.bot = bot
                context.event = event
                context.logger = self.logger

                plain_text = event.message.extract_plain_text()
                for cmd in sorted(self.commands, key=len, reverse=True):
                    if cmd in plain_text:
                        context.trigger_cmd = cmd
                        break
                context.arg_text = plain_text.replace(context.trigger_cmd, "")

                if any([banned_cmd in context.trigger_cmd for banned_cmd in self.banned_cmds]):
                    return

                context.message_id = event.message_id
                context.user_id = event.user_id
                if is_group_msg(event):
                    context.group_id = event.group_id

                # 记录到历史
                global _cmd_history, MAX_CMD_HISTORY
                if context.trigger_cmd:
                    _cmd_history.append(context)
                    if len(_cmd_history) > MAX_CMD_HISTORY:
                        _cmd_history = _cmd_history[-MAX_CMD_HISTORY:]

                try:
                    # 额外处理，用于子类自定义
                    context = await self.additional_context_process(context)
                    assert context, "额外处理返回值不能为空"

                    # 帮助文档
                    if not self.disable_help:
                        for help_keyword in ('help', '帮助'):
                            ok = False
                            if isinstance(self.help_trigger_condition, str):
                                match self.help_trigger_condition:
                                    case 'contain':
                                        ok = help_keyword in context.arg_text
                                    case 'exact':
                                        ok = context.arg_text.strip() == help_keyword
                            else:
                                ok = self.help_trigger_condition(context.arg_text)
                            if ok:
                                cmds = self.commands if not self.help_command else [self.help_command]
                                for cmd in cmds:
                                    part = self.find_cmd_help_doc(cmd)
                                    if part:
                                        img = await self.get_cmd_help_doc_img(part)
                                        return await context.asend_reply_msg(await get_image_cq(img, low_quality=True))
                                raise ReplyException(f"没有找到该指令的帮助\n发送\"/help\"查看完整帮助")

                    # 执行函数
                    return await handler_func(context)
                
                except NoReplyException:
                    return
                except ReplyException as e:
                    return await context.asend_reply_msg(str(e))
                except Exception as e:
                    self.logger.print_exc(f'指令\"{context.trigger_cmd}\"处理失败')
                    if self.error_reply:
                        await context.asend_reply_msg(truncate(f"指令处理失败: {get_exc_desc(e)}", 256))
                finally:
                    for block_id in context.block_ids:
                        self.block_set.discard(block_id)
                        
            return func
        return decorator
  

# ============================ 指令处理 ============================ #

# 获取当前群聊开启和关闭的服务 或 获取某个服务在哪些群聊开启
_handler = CmdHandler(['/service', '/服务'], utils_logger)
_handler.check_superuser()
@_handler.handle()
async def _(ctx: HandlerContext):
    name = ctx.get_args().strip()

    if name:
        assert_and_reply(name in _gwls or name in _gbls, f"未知服务 {name}")
        msg = ""
        if name in _gwls:
            msg += f"{name}使用的规则是白名单\n开启服务的群聊有:\n"
            for group_id in _gwls[name].get():
                msg += f'{await get_group_name(ctx.bot, group_id)}({group_id})\n'
        elif name in _gbls:
            msg += f"{name}使用的规则是黑名单\n关闭服务的群聊有:\n"
            for group_id in _gbls[name].get():
                msg += f'{await get_group_name(ctx.bot, group_id)}({group_id})\n'
        return await ctx.asend_reply_msg(msg.strip())

    msg_on = "本群开启的服务:\n"
    msg_off = "本群关闭的服务:\n"
    for name, gwl in _gwls.items():
        if gwl.check_id(ctx.group_id):
            msg_on += f'{name} '
        else:
            msg_off += f'{name} '
    for name, gbl in _gbls.items():
        if gbl.check_id(ctx.group_id):
            msg_on += f'{name} '
        else:
            msg_off += f'{name} '

    return await ctx.asend_reply_msg(msg_on + '\n' + msg_off)

# 设置群聊开启
_handler = CmdHandler(['/enable'], utils_logger, check_group_enabled=False, only_to_me=True)
_handler.check_superuser()
@_handler.handle()
async def _(ctx: HandlerContext):
    args = ctx.get_args().strip()
    try: group_id = int(args)
    except: 
        assert_and_reply(ctx.group_id, "请指定群号")
        group_id = ctx.group_id
    group_name = await get_group_name(ctx.bot, group_id)
    set_group_enable(group_id, True)
    return await ctx.asend_reply_msg(f'已启用群聊 {group_name} ({group_id}) BOT服务')

# 设置群聊关闭
_handler = CmdHandler(['/disable'], utils_logger, check_group_enabled=False)
_handler.check_superuser()
@_handler.handle()
async def _(ctx: HandlerContext):
    args = ctx.get_args().strip()
    try: group_id = int(args)
    except: 
        assert_and_reply(ctx.group_id, "请指定群号")
        group_id = ctx.group_id
    group_name = await get_group_name(ctx.bot, group_id)
    set_group_enable(group_id, False)
    return await ctx.asend_reply_msg(f'已禁用群聊 {group_name} ({group_id}) BOT服务')

# 查看群聊列表的开启状态
_handler = CmdHandler(['/group_status'], utils_logger)
_handler.check_superuser()
@_handler.handle()
async def _(ctx: HandlerContext):
    enabled_msg = "【已启用的群聊】"
    disabled_msg = "【已禁用的群聊】"
    enabled_groups = utils_file_db.get("enabled_groups", [])
    for group_id in await get_group_id_list(ctx.bot):
        group_name = await get_group_name(ctx.bot, group_id)
        if group_id in enabled_groups:
            enabled_msg += f'\n{group_name} ({group_id})'
        else:
            disabled_msg += f'\n{group_name} ({group_id})'
    return await ctx.asend_reply_msg(enabled_msg + '\n\n' + disabled_msg)

# 添加qq号到黑名单
_handler = CmdHandler(['/blacklist_add'], utils_logger)
_handler.check_superuser()
@_handler.handle()
async def _(ctx: HandlerContext):
    args = ctx.get_args().strip()
    try: 
        user_ids = [int(x) for x in args.split()]
        assert user_ids
    except: 
        raise ReplyException("请指定要添加到黑名单的QQ号")

    msg = ""
    blacklist = utils_file_db.get("blacklist", [])
    for user_id in user_ids:
        if user_id in blacklist:
            msg += f'QQ号 {user_id} 已在黑名单中\n'
        else:
            blacklist.append(user_id)
            msg += f'已将QQ号 {user_id} 添加到黑名单\n'
    utils_file_db.set("blacklist", blacklist)

    return await ctx.asend_reply_msg(msg.strip())

# 删除黑名单中的qq号
_handler = CmdHandler(['/blacklist_del'], utils_logger)
_handler.check_superuser()
@_handler.handle()
async def _(ctx: HandlerContext):
    args = ctx.get_args().strip()
    try: 
        user_ids = [int(x) for x in args.split()]
        assert user_ids
    except: 
        raise ReplyException("请指定要删除黑名单的QQ号")

    msg = ""
    blacklist = utils_file_db.get("blacklist", [])
    for user_id in user_ids:
        if user_id not in blacklist:
            msg += f'QQ号 {user_id} 不在黑名单中\n'
        else:
            blacklist.remove(user_id)
            msg += f'已将QQ号 {user_id} 从黑名单中删除\n'
    utils_file_db.set("blacklist", blacklist)

    return await ctx.asend_reply_msg(msg.strip())

# 获取当日消息发送数量
_handler = CmdHandler(['/send_count'], utils_logger)
_handler.check_superuser()
@_handler.handle()
async def _(ctx: HandlerContext):
    count = get_send_msg_daily_count()
    return await ctx.asend_reply_msg(f'今日已发送消息数量: {count}')

# 画图调试
_handler = CmdHandler(['/draw time', '/画图时间'], utils_logger)
_handler.check_superuser()
@_handler.handle()
async def _(ctx: HandlerContext):
    if Canvas.log_draw_time:
        Canvas.log_draw_time = False
        return await ctx.asend_reply_msg("已关闭画图时间日志")
    else:
        Canvas.log_draw_time = True
        return await ctx.asend_reply_msg("已开启画图时间日志")

# 删除Painter缓存
_handler = CmdHandler(['/clear_pcache', '/clear pcache', '/pcache clear', '/pcache_clear'], utils_logger)
_handler.check_superuser()
@_handler.handle()
async def _(ctx: HandlerContext):
    key = ctx.get_args().strip()
    ok_count = Painter.clear_cache(key)
    return await ctx.asend_reply_msg(f'已清除Painter缓存: {ok_count}个文件被删除')

# 查看Painter缓存
_handler = CmdHandler(['/pcache'], utils_logger)
_handler.check_superuser()
@_handler.handle()
async def _(ctx: HandlerContext):
    ret = Painter.get_cache_key_mtimes()
    msg = f"当前Painter缓存的keys:\n"
    for key, mtime in ret.items():
        msg += f"{key}: {mtime.strftime('%Y-%m-%d %H:%M:%S')}\n"
    return await ctx.asend_reply_msg(msg.strip())
