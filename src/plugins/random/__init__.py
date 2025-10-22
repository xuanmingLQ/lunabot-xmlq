from ..utils import *

config = Config('random')
logger = get_logger("Random")
file_db = get_file_db("data/random/db.json", logger)
cd = ColdDown(file_db, logger)
gbl = get_group_black_list(file_db, logger, 'random')


DICE_SIZE = 32
dice_images = [f"data/random/dice/{i}.png" for i in range(1, 7)]
dice_images = [Image.open(d).resize((DICE_SIZE, DICE_SIZE)) for d in dice_images]
dice_rule_image = Image.open("data/random/dice_rule.jpg")


# 博饼
bing = CmdHandler(["/bing", "/bobing", "/博饼", "/饼"], logger)
bing.check_cdrate(cd).check_wblist(gbl)
@bing.handle()
async def _(ctx: HandlerContext):
    dices = [random.randint(1, 6) for _ in range(6)]
    image = Image.new('RGBA', (DICE_SIZE * 6, DICE_SIZE * 2), (255, 255, 255, 0))
    for i, dice in enumerate(dices):
        image.paste(dice_images[dice - 1], (i * DICE_SIZE, DICE_SIZE // 2))
    with TempFilePath('gif') as save_path:
        save_transparent_static_gif(image, save_path)
        await ctx.asend_reply_msg(await get_image_cq(save_path))


# 博饼规则
bing_rule = CmdHandler(["/bingrule", "/bing_rule", "/bing rule", 
                        "/bobing_rule", "/bobingrule", "/bobing rule",
                        "/博饼规则", "/博饼 规则", "/饼 规则", "/饼规则"], logger)
bing_rule.check_cdrate(cd).check_wblist(gbl)
@bing_rule.handle()
async def _(ctx: HandlerContext):
    return await ctx.asend_reply_msg(await get_image_cq(dice_rule_image, low_quality=True))


# 随机数
rand = CmdHandler(["/rand", "/roll", "/随机数"], logger)
rand.check_cdrate(cd).check_wblist(gbl)
@rand.handle()
async def _(ctx: HandlerContext):
    args = ctx.get_args().strip().split()
    if len(args) == 1:
        l, r = 1, int(args[0])
    elif len(args) == 2:
        l, r = int(args[0]), int(args[1])
        assert_and_reply(l <= r, '左边界必须小于右边界')
    else:
        l, r = 0, 100
    msg = f'{random.randint(l, r)}'
    return await ctx.asend_reply_msg(msg)


# 随机选择
choice = CmdHandler(["/choice", '/choose', "/选择"], logger)
choice.check_cdrate(cd).check_wblist(gbl)
@choice.handle()
async def _(ctx: HandlerContext):
    choices = ctx.get_args().strip().split()
    if len(choices) <= 1:
        raise Exception('至少需要两个选项')
    msg = f'选择: {random.choice(choices)}'
    return await ctx.asend_reply_msg(msg)


# 打乱
shuffle = CmdHandler(["/shuffle", "/洗牌", "/打乱"], logger)
shuffle.check_cdrate(cd).check_wblist(gbl)
@shuffle.handle()
async def _(ctx: HandlerContext):
    choices = ctx.get_args().strip().split()
    if len(choices) <= 1:
        raise Exception('至少需要两个选项')
    random.shuffle(choices)
    msg = f'{", ".join(choices)}'
    return await ctx.asend_reply_msg(msg)


# 随机群成员
randuser = CmdHandler(['/randuser', '/rolluser', '/randmember', '/rollmember', "/随机群友"], logger)
randuser.check_cdrate(cd).check_wblist(gbl)
@randuser.handle()
async def _(ctx: HandlerContext):
    num = 1
    try:
        num = int(ctx.get_args().strip())
        assert num > 0 and num < 20
    except:
        pass
    
    group_members = await get_group_users(ctx.bot, ctx.group_id)
    if num > len(group_members):
        raise Exception('群成员数量不足')

    random.shuffle(group_members)
    msg = ""
    for user in group_members[:num]:
        user_id = int(user['user_id'])
        icon_url = get_avatar_url(user_id)
        nickname = await get_group_member_name(ctx.bot, ctx.group_id, user_id)
        msg += f"{await get_image_cq(icon_url)}\n{nickname}({user_id})\n"

    return await ctx.asend_reply_msg(msg.strip())
