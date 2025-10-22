from ...utils import *
from ..common import *
from ..handler import *
from ..asset import *
from ..draw import *
from .stamp_maker import make_stamp, check_stamp_can_make

GIF_STAMP_SCALE = 2.0

# ======================= 处理逻辑 ======================= #

# 获取表情图片
async def get_stamp_image(ctx: SekaiHandlerContext, sid) -> Image.Image:
    stamp = await ctx.md.stamps.find_by_id(sid)
    assert_and_reply(stamp, f"表情 {sid} 不存在")
    asset_name = stamp['assetbundleName']
    img = await ctx.rip.img(f"stamp/{asset_name}_rip/{asset_name}.png")
    return img

# 获取用于发送的透明表情cq码
async def get_stamp_image_cq(ctx: SekaiHandlerContext, sid: int, format: str) -> str:
    assert format in ["png", "gif"]
    if format == "gif":
        with TempFilePath("gif") as path:
            img = await get_stamp_image(ctx, sid)
            img = img.resize((int(img.width * GIF_STAMP_SCALE), int(img.height * GIF_STAMP_SCALE)), Image.Resampling.LANCZOS)
            save_transparent_static_gif(img, path)
            return await get_image_cq(path)
    else:
        return await get_image_cq(await get_stamp_image(ctx, sid))

# 合成某个角色的所有表情图片
async def compose_character_all_stamp_image(ctx: SekaiHandlerContext, cid):
    stamp_ids = []
    for stamp in await ctx.md.stamps.get():
        if stamp.get('characterId1') == cid or stamp.get('characterId2') == cid:
            stamp_ids.append(stamp['id'])
    stamp_imgs = await asyncio.gather(*[get_stamp_image(ctx, sid) for sid in stamp_ids])
    stamp_id_imgs = [(sid, img) for sid, img in zip(stamp_ids, stamp_imgs) if img]

    with Canvas(bg=SEKAI_BLUE_BG).set_padding(BG_PADDING) as canvas:
        with VSplit().set_sep(8).set_item_align('l'):
            TextBox(
                f"发送\"{ctx.original_trigger_cmd} ID\"获取单张表情\n"
                f"发送\"{ctx.original_trigger_cmd} ID 文本\"制作表情(仅蓝色ID支持制作)",
                style=TextStyle(font=DEFAULT_FONT, size=24, color=(50, 50, 50, 255)), use_real_line_count=True) \
                .set_padding(16).set_bg(roundrect_bg())
            with Grid(col_count=5).set_sep(4, 4).set_item_bg(roundrect_bg()):
                for sid, img in stamp_id_imgs:
                    text_color = (0, 0, 200, 255) if check_stamp_can_make(sid) else (200, 0, 0, 255)
                    with VSplit().set_padding(4).set_sep(4):
                        ImageBox(img, size=(None, 100), use_alphablend=True)
                        TextBox(str(sid), style=TextStyle(font=DEFAULT_BOLD_FONT, size=24, color=text_color))
    add_watermark(canvas)
    return await canvas.get_img()

# 制作表情并返回cq码
async def make_stamp_image_cq(ctx: SekaiHandlerContext, sid: int, text: str, format: str) -> str:
    stamp = await ctx.md.stamps.find_by_id(sid)
    assert_and_reply(stamp, f"表情 {sid} 不存在")
    cid = stamp.get('characterId1')
    cid2 = stamp.get('characterId2')
    assert_and_reply(cid and not cid2, f"该表情不支持制作")
    nickname = get_character_first_nickname(cid)
    text_zoom_ratio = 1.0
    line_count = 0
    for line in text.splitlines():
        dst_len = get_str_display_length(line)
        text_zoom_ratio = min(text_zoom_ratio, 0.3 + dst_len * 0.04)
        line_count += 1
    text_y_offset = int(15 - 30 * (1.0 - text_zoom_ratio))
    img = make_stamp(
        id = sid,
        character = nickname, 
        text = text,
        degree = 5,
        text_zoom_ratio = text_zoom_ratio,
        text_pos = "mu",
        line_spacing = 0,
        text_x_offset = 0,
        text_y_offset = text_y_offset,
        disable_different_font_size = False
    )
    assert_and_reply(img, f"该表情ID不支持制作\n使用/pjsk stamp 角色简称 查询哪些表情支持制作")
    if format == 'gif':
        img = img.resize((int(img.width * GIF_STAMP_SCALE), int(img.height * GIF_STAMP_SCALE)), Image.Resampling.LANCZOS)
        with TempFilePath("gif") as path:
            save_transparent_static_gif(img, path)
            return await get_image_cq(path)
    else:
        return await get_image_cq(img)


# ======================= 指令处理 ======================= #

# 表情查询/制作
pjsk_stamp = SekaiCmdHandler(["/pjsk stamp", "/pjsk_stamp", "/pjsk表情", "/pjsk表情制作"])
pjsk_stamp.check_cdrate(cd).check_wblist(gbl)
@pjsk_stamp.handle()
async def _(ctx: SekaiHandlerContext):
    await ctx.block_region()

    args = ctx.get_args().strip()
    format = 'gif'
    if "png" in args:
        format = 'png'
        args = args.replace("png", "").strip()

    qtype, sid, cid, text = None, None, None, None

    # 尝试解析：全都是id
    if not qtype:
        try:
            assert all([int(x) >= 0 for x in args.split()])
            sid = [int(x) for x in args.split()]
            qtype = "id"
        except:
            pass

    # 尝试解析：单独昵称作为参数
    if not qtype:
        try:
            cid = get_cid_by_nickname(args)
            assert cid is not None
            qtype = "cid"
        except:
            pass

    # 尝试解析：id+文本作为参数
    if not qtype:
        try:
            sid, text = args.split(maxsplit=1)
            sid = int(sid)
            assert sid >= 0 and text
            qtype = "id_text"
        except:
            pass
    
    if not qtype:
        return await ctx.asend_reply_msg(f"""使用方式
根据id查询: {ctx.original_trigger_cmd} 123
查询多个: {ctx.original_trigger_cmd} 123 456
查询某个角色所有: {ctx.original_trigger_cmd} miku                                    
制作表情: {ctx.original_trigger_cmd} 123 文本
""".strip())
    
    # id获取表情
    if qtype == "id":
        logger.info(f"获取表情 sid={sid}")
        msg = "".join([await get_stamp_image_cq(ctx, x, format) for x in sid])
        return await ctx.asend_reply_msg(msg)
    
    # 获取角色所有表情
    if qtype == "cid":
        logger.info(f"合成角色表情: cid={cid}")
        msg = await get_image_cq(await compose_character_all_stamp_image(ctx, cid))
        return await ctx.asend_reply_msg(msg)

    # 制作表情
    if qtype == "id_text":
        logger.info(f"制作表情: sid={sid} text={text}")
        return await ctx.asend_reply_msg(await make_stamp_image_cq(ctx, sid, text, format))


# 随机表情 
pjsk_rand_stamp = SekaiCmdHandler([
    "/pjsk rand stamp", "/pjsk随机表情", "/pjsk随机表情制作", "/随机表情",
])
pjsk_rand_stamp.check_cdrate(cd).check_wblist(gbl)
@pjsk_rand_stamp.handle()
async def _(ctx: SekaiHandlerContext):
    await ctx.block_region()
    args = ctx.get_args().strip()
    format = 'gif'
    if "png" in args:
        format = 'png'
        args = args.replace("png", "").strip()

    async def get_rand_sid(cid, can_make):
        stamps = await ctx.md.stamps.get()
        for i in range(10000):
            stamp = random.choice(stamps)
            if cid and stamp.get('characterId1') != cid and stamp.get('characterId2') != cid:
                continue
            if can_make and not check_stamp_can_make(stamp['id']):
                continue
            return stamp['id']
        return None

    # 如果存在角色昵称，只返回指定角色昵称的随机表情
    cid = None
    if args:
        for item in get_character_nickname_data():
            for nickname in item.nicknames:
                if args.startswith(nickname):
                    cid = item.id
                    args = args[len(nickname):].strip()
                    break

    if args:
        # 表情制作模式
        sid = await get_rand_sid(cid, True)
        assert_and_reply(sid, f"没有符合条件的表情")
        return await ctx.asend_reply_msg(await make_stamp_image_cq(ctx, sid, args, format))
    else:
        sid = await get_rand_sid(cid, False)
        assert_and_reply(sid, f"没有符合条件的表情")
        return await ctx.asend_reply_msg(await get_stamp_image_cq(ctx, sid, format))