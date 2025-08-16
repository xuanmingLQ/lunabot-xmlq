from ...utils import *
from ...record import after_record_hook
from ..common import *
from ..handler import *
from ..asset import *
from ..draw import *
from ..sub import SekaiGroupSubHelper
from .card_extractor import CardExtractor, CardExtractResult, CardThumbnail
from .profile import get_card_full_thumbnail
from .card import has_after_training, only_has_after_training

md_update_group_sub = SekaiGroupSubHelper("update", "MasterData更新通知", ALL_SERVER_REGIONS)

# ======================= 指令处理 ======================= #

pjsk_update = SekaiCmdHandler([
    "/pjsk update", "/pjsk_update", "/pjsk refresh", "/pjsk_refresh", "/pjskupdate",
])
pjsk_update.check_cdrate(cd).check_wblist(gbl)
@pjsk_update.handle()
async def _(ctx: SekaiHandlerContext):
    mgr = RegionMasterDbManager.get(ctx.region)
    msg = f"{get_region_name(ctx.region)}MasterData数据源"
    for source in await mgr.get_all_sources(force_update=True):
        msg += f"\n[{source.name}] {source.version}"
    return await ctx.asend_reply_msg(msg.strip())


ngword = SekaiCmdHandler([
    "/pjsk ng", "/pjsk ngword", "/pjsk ng word",
    "/pjsk屏蔽词", "/pjsk屏蔽", "/pjsk敏感", "/pjsk敏感词",
])
ngword.check_cdrate(cd).check_wblist(gbl)
@ngword.handle()
async def _(ctx: SekaiHandlerContext):
    text = ctx.get_args()
    assert_and_reply(text, "请输入要查询的文本")
    words = await ctx.md.ng_words.get()
    def check():
        ret = []
        for word in words:
            if word in text:
                ret.append(word)
        return ret
    ret = await run_in_pool(check)
    if ret:
        await ctx.asend_reply_msg(f"检测到屏蔽词：{', '.join(ret)}")
    else:
        await ctx.asend_reply_msg("未检测到屏蔽词")


upload_help = SekaiCmdHandler([
    "/抓包帮助", "/抓包", "/pjsk upload help"
])
upload_help.check_cdrate(cd).check_wblist(gbl)
@upload_help.handle()
async def _(ctx: SekaiHandlerContext):
    text = Path(f"{SEKAI_DATA_DIR}/upload_help.txt").read_text(encoding="utf-8")
    return await ctx.asend_msg(text.strip())


blurglass = CmdHandler([
    "/毛玻璃",
], logger=logger)
blurglass.check_cdrate(cd).check_wblist(gbl).check_superuser()
@blurglass.handle()
async def _(ctx: HandlerContext):
    if get_blurglass_enabled():
        set_blurglass_enabled(False)
        msg = "已关闭毛玻璃效果"
    else:
        set_blurglass_enabled(True)
        msg = "已开启毛玻璃效果"
    return await ctx.asend_msg(msg)



card_extractor = CardExtractor()
extract_card = SekaiCmdHandler([
    "/提取卡牌"
], regions=['jp'])
extract_card.check_cdrate(cd).check_wblist(gbl)
@extract_card.handle()
async def _(ctx: SekaiHandlerContext):
    await ctx.block()
    global card_extractor
    bot, event = ctx.bot, ctx.event
    reply_msg = await get_reply_msg(bot, await get_msg(bot, event.message_id))
    assert_and_reply(reply_msg, f"请回复一张图片")
    cqs = extract_cq_code(reply_msg)
    assert_and_reply('image' in cqs, f"请回复一张图片")
    img = await download_image(cqs['image'][0]['url'])
    
    if not card_extractor.is_initialized():
        card_thumbs = []
        for card in await ctx.md.cards.get():
            card_id = card['id']
            rarity = card['cardRarityType']
            attr = card['attr']
            assetbundle_name = card['assetbundleName']
            img_dir = 'data/sekai/assets/rip/jp/thumbnail/chara_rip'
            if not only_has_after_training(card):
                normal_path = await ctx.rip.get_asset_cache_path(f'thumbnail/chara_rip/{assetbundle_name}_normal.png')
                if normal_path:
                    card_thumbs.append(CardThumbnail(
                        id=card_id,
                        rarity=rarity,
                        attr=attr,
                        is_aftertraining=False,
                        img_path=os.path.join(img_dir, f"{assetbundle_name}_normal.png"),
                    ))
            if has_after_training(card):
                aftertraining_path = await ctx.rip.get_asset_cache_path(f'thumbnail/chara_rip/{assetbundle_name}_after_training.png')
                if aftertraining_path:
                    card_thumbs.append(CardThumbnail(
                        id=card_id,
                        rarity=rarity,
                        attr=attr,
                        is_aftertraining=True,
                        img_path=os.path.join(img_dir, f"{assetbundle_name}_after_training.png"),
                    ))
        t = datetime.now()
        await run_in_pool(card_extractor.init, card_thumbs)
        logger.info(f"CardExtractor initialized in {datetime.now() - t} seconds")
    
    t = datetime.now()
    result: CardExtractResult = await run_in_pool(card_extractor.extract_cards, img)
    logger.info(f"CardExtractor extracted {len(result.cards)} cards in {datetime.now() - t} seconds")
    
    with Canvas(bg=FillBg(WHITE)).set_padding(BG_PADDING) as canvas:
        with Grid(col_count=result.grid.cols).set_sep(8, 8):
            for row_idx in range(result.grid.rows):
                for col_idx in range(result.grid.cols):
                    with HSplit().set_sep(0):
                        w = 64
                        try:
                            import cv2
                            img = result.grid.get_grid_image(row_idx, col_idx)
                            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                            img = Image.fromarray(img)
                            ImageBox(img, size=(w, w))
                        except:
                            Spacer(w, w)
                            Spacer(w, w)
                            continue

                        card = find_by_predicate(result.cards, lambda c: c.row_idx == row_idx and c.col_idx == col_idx)
                        if card is None:
                            ImageBox(UNKNOWN_IMG, size=(w, w))
                        else:
                            pcard = {
                                'defaultImage': "special_training" if card.is_aftertraining else "normal",
                                'specialTrainingStatus': "done" if card.is_aftertraining else "none",
                                'level': card.level,
                                'masterRank': card.master_rank,
                            }
                            custom_text = None if card.level is not None else f"SLv.{card.skill_level}"
                            thumb = await get_card_full_thumbnail(ctx, card.id, pcard=pcard, custom_text=custom_text)
                            ImageBox(thumb, size=(w, w))
        
    return await ctx.asend_reply_msg(
        await get_image_cq(
            await canvas.get_img(),
            low_quality=True,
        )
    )


# ======================= 定时通知 ======================= #

# masterdata更新通知
@RegionMasterDbManager.on_update()
async def send_masterdata_update_notify(
    region: str, source: str,
    version: str, last_version: str,
    asset_version: str, last_asset_version: str,
):
    bot = get_bot()
    region_name = get_region_name(region)

    # 防止重复通知
    last_notified_version = file_db.get(f"last_notified_md_version_{region}", None)
    if last_notified_version and get_version_order(last_notified_version) >= get_version_order(version):
        return
    file_db.set(f"last_notified_md_version_{region}", version)

    msg = f"从{source}获取{region_name}的MasterData版本更新: {last_version} -> {version}\n"
    if last_asset_version != asset_version:
        msg += f"解包资源版本: {last_asset_version} -> {asset_version}\n"
    msg = msg.strip()

    for group_id in md_update_group_sub.get_all(region):
        if not gbl.check_id(group_id): continue
        try:
            await send_group_msg_by_bot(bot, group_id, msg)
        except Exception as e:
            logger.print_exc(f"在群聊发送 {group_id} 发送 {region} MasterData更新通知失败")
            continue


