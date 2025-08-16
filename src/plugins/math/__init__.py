from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot.adapters.onebot.v11.message import Message as OutMessage
from nonebot.adapters.onebot.v11 import MessageEvent
from ..utils import *
from asteval import Interpreter
from .oeis import oeis_query

config = get_config('math')
logger = get_logger("Math")
file_db = get_file_db("data/math/db.json", logger)
cd = ColdDown(file_db, logger, config['cd'])
gbl = get_group_black_list(file_db, logger, 'math')


aeval = Interpreter()

eval = CmdHandler(["/eval"], logger)
eval.check_cdrate(cd).check_wblist(gbl)
@eval.handle()
async def _(ctx: HandlerContext):
    expr = ctx.get_args().strip()
    assert_and_reply(expr, "请输入表达式")
    logger.info(f"计算 {expr}")
    global aeval
    result = aeval(expr)
    return await ctx.asend_reply_msg(str(result))


NUM_SEARCH = config['oeis_search_num']

query = CmdHandler(["/oeis"], logger)
query.check_cdrate(cd).check_wblist(gbl)
@query.handle()
async def _(ctx: HandlerContext):
    args = ctx.get_args().strip()
    sequences = await oeis_query(args, n=NUM_SEARCH)
    logger.info(f"查询 OEIS 序列: {args} 共 {len(sequences)} 条结果")
    assert_and_reply(sequences, "未找到相关序列")
    msg = ""
    for seq in sequences:
        msg += f"【{seq.id}】{seq.name}\n"
        msg += f"{seq.sequence}\n"
        msg += f"Formula: {seq.formula}\n"
        msg += "\n"
    return await ctx.asend_fold_msg_adaptive(msg.strip())

