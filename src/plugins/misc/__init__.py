from ..utils import *
from nonebot.adapters.onebot.v11 import NoticeEvent
from nonebot import on_notice
import glob


config = get_config('misc')
logger = get_logger("Misc")
file_db = get_file_db("data/misc/db.json", logger)
gbl = get_group_black_list(file_db, logger, "misc")
cd = ColdDown(file_db, logger, config['cd'])



group_last_poke_reply_time = {}
GROUP_POKE_REPLY_INTERVAL = timedelta(seconds=5)

poke_reply = on_notice(block=False)
@poke_reply.handle()
async def _(bot: Bot, event: NoticeEvent):
    try:
        if not (event.notice_type == 'notify' and event.sub_type == 'poke'):
            return
        if not is_group_msg(event):
            return
        if event.target_id != event.self_id or event.user_id == event.self_id:
            return
        if check_group_disabled(event.group_id):
            return
        
        t = datetime.now()
        if event.group_id not in group_last_poke_reply_time:
            group_last_poke_reply_time[event.group_id] = t - GROUP_POKE_REPLY_INTERVAL
        if t - group_last_poke_reply_time[event.group_id] < GROUP_POKE_REPLY_INTERVAL:
            return
        group_last_poke_reply_time[event.group_id] = t

        imgs = glob.glob("data/misc/poke_reply/*")
        if not imgs:
            return
        img = random.choice(imgs)
        await send_group_msg_by_bot(bot, event.group_id, await get_image_cq(img))

    except:
        logger.print_exc("回复戳失败")

