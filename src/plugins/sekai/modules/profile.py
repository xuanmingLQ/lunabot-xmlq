from ...utils import *
from ..common import *
from ..handler import *
from ..asset import *
from ..draw import *
from .honor import compose_full_honor_image
from .resbox import get_res_box_info, get_res_icon
from ...utils.safety import *


SEKAI_PROFILE_DIR = f"{SEKAI_DATA_DIR}/profile"
profile_db = get_file_db(f"{SEKAI_PROFILE_DIR}/db.json", logger)
bind_history_db = get_file_db(f"{SEKAI_PROFILE_DIR}/bind_history.json", logger)
player_frame_db = get_file_db(f"{SEKAI_PROFILE_DIR}/player_frame.json", logger)

DAILY_BIND_LIMIT = config.item('daily_bind_limit')

gameapi_config = Config('sekai.gameapi')

@dataclass
class GameApiConfig:
    api_status_url: Optional[str] = None
    profile_api_url: Optional[str] = None 
    suite_api_url: Optional[str] = None
    mysekai_api_url: Optional[str] = None  
    mysekai_photo_api_url: Optional[str] = None 
    mysekai_upload_time_api_url: Optional[str] = None 
    update_msr_sub_api_url: Optional[str] = None
    ranking_border_api_url: Optional[str] = None
    ranking_top100_api_url: Optional[str] = None
    send_boost_api_url: Optional[str] = None
    create_account_api_url: Optional[str] = None
    ad_result_update_time_api_url: Optional[str] = None
    ad_result_api_url: Optional[str] = None


@dataclass
class PlayerAvatarInfo:
    card_id: int
    cid: int
    unit: str
    img: Image.Image

DEFAULT_DATA_MODE = 'latest'


@dataclass
class VerifyCode:
    region: str
    qid: int
    uid: int
    expire_time: datetime
    verify_code: str

VERIFY_CODE_EXPIRE_TIME = timedelta(minutes=30)
_region_qid_verify_codes: Dict[str, Dict[str, VerifyCode]] = {}
verify_rate_limit = RateLimit(file_db, logger, 10, 'd', rate_limit_name='pjsk验证')


@dataclass
class ProfileBgSettings:
    image: Image.Image
    blur: int = None
    alpha: int = None
    vertical: bool = False

PROFILE_BG_IMAGE_PATH = f"{SEKAI_PROFILE_DIR}/profile_bg/" + "{region}/{uid}.jpg"
profile_bg_settings_db = get_file_db(f"{SEKAI_PROFILE_DIR}/profile_bg_settings.json", logger)
profile_bg_upload_rate_limit = RateLimit(file_db, logger, 10, 'd', rate_limit_name='个人信息背景上传')


@dataclass
class AreaItemFilter:
    unit: str = None        # 某个团的世界里面的所有道具
    cid: int = None         # 某个角色的所有道具
    attr: str = None        # 某个属性的所有道具
    tree: bool = None       # 所有树
    flower: bool = None     # 所有花

FLOWER_AREA_ID = 13
TREE_AREA_ID = 11
UNIT_SEKAI_AREA_IDS = {
    "light_sound": 5,
    "idol": 7,
    "street": 8,
    "theme_park": 9,
    "school_refusal": 10,
}


# ======================= 卡牌逻辑（防止循环依赖） ======================= #

# 判断卡牌是否有after_training模式
def has_after_training(card):
    return card['cardRarityType'] in ["rarity_3", "rarity_4"]

# 判断卡牌是否只有after_training模式
def only_has_after_training(card):
    return card.get('initialSpecialTrainingStatus') == 'done'

# 获取角色卡牌缩略图
async def get_card_thumbnail(ctx: SekaiHandlerContext, cid: int, after_training: bool):
    image_type = "after_training" if after_training else "normal"
    card = await ctx.md.cards.find_by_id(cid)
    assert_and_reply(card, f"找不到ID为{cid}的卡牌")
    return await ctx.rip.img(f"thumbnail/chara_rip/{card['assetbundleName']}_{image_type}.png", use_img_cache=True)

# 获取角色卡牌完整缩略图（包括边框、星级等）
async def get_card_full_thumbnail(
    ctx: SekaiHandlerContext, 
    card_or_card_id: Dict, 
    after_training: bool=None, 
    pcard: Dict=None, 
    custom_text: str=None,
):
    if isinstance(card_or_card_id, int):
        card = await ctx.md.cards.find_by_id(card_or_card_id)
        assert_and_reply(card, f"找不到ID为{card_or_card_id}的卡牌")
    else:
        card = card_or_card_id
    cid = card['id']

    if not pcard:
        after_training = after_training and has_after_training(card)
        rare_image_type = "after_training" if after_training else "normal"
    else:
        after_training = pcard['defaultImage'] == "special_training"
        rare_image_type = "after_training" if pcard['specialTrainingStatus'] == "done" else "normal"

    # 如果没有指定pcard则尝试使用缓存
    if not pcard:
        image_type = "after_training" if after_training else "normal"
        cache_path = f"{SEKAI_ASSET_DIR}/card_full_thumbnail/{ctx.region}/{cid}_{image_type}.png"
        try: return open_image(cache_path)
        except: pass

    img = await get_card_thumbnail(ctx, cid, after_training)
    ok_to_cache = (img != UNKNOWN_IMG)
    img = img.copy()

    def draw(img: Image.Image, card):
        attr = card['attr']
        rare = card['cardRarityType']
        frame_img = ctx.static_imgs.get(f"card/frame_{rare}.png")
        attr_img = ctx.static_imgs.get(f"card/attr_{attr}.png")
        if rare == "rarity_birthday":
            rare_img = ctx.static_imgs.get(f"card/rare_birthday.png")
            rare_num = 1
        else:
            rare_img = ctx.static_imgs.get(f"card/rare_star_{rare_image_type}.png") 
            rare_num = int(rare.split("_")[1])

        img_w, img_h = img.size

        # 如果是profile卡片则绘制等级/加成
        if pcard:
            if custom_text is not None:
                draw = ImageDraw.Draw(img)
                draw.rectangle((0, img_h - 24, img_w, img_h), fill=(70, 70, 100, 255))
                draw.text((6, img_h - 31), custom_text, font=get_font(DEFAULT_BOLD_FONT, 20), fill=WHITE)
            else:
                level = pcard['level']
                draw = ImageDraw.Draw(img)
                draw.rectangle((0, img_h - 24, img_w, img_h), fill=(70, 70, 100, 255))
                draw.text((6, img_h - 31), f"Lv.{level}", font=get_font(DEFAULT_BOLD_FONT, 20), fill=WHITE)
            
        # 绘制边框
        frame_img = frame_img.resize((img_w, img_h))
        img.paste(frame_img, (0, 0), frame_img)
        # 绘制特训等级
        if pcard:
            rank = pcard['masterRank']
            if rank:
                rank_img = ctx.static_imgs.get(f"card/train_rank_{rank}.png")
                rank_img = rank_img.resize((int(img_w * 0.35), int(img_h * 0.35)))
                rank_img_w, rank_img_h = rank_img.size
                img.paste(rank_img, (img_w - rank_img_w, img_h - rank_img_h), rank_img)
        # 左上角绘制属性
        attr_img = attr_img.resize((int(img_w * 0.22), int(img_h * 0.25)))
        img.paste(attr_img, (1, 0), attr_img)
        # 左下角绘制稀有度
        hoffset, voffset = 6, 6 if not pcard else 24
        scale = 0.17 if not pcard else 0.15
        rare_img = rare_img.resize((int(img_w * scale), int(img_h * scale)))
        rare_w, rare_h = rare_img.size
        for i in range(rare_num):
            img.paste(rare_img, (hoffset + rare_w * i, img_h - rare_h - voffset), rare_img)
        mask = Image.new('L', (img_w, img_h), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle((0, 0, img_w, img_h), radius=10, fill=255)
        img.putalpha(mask)
        return img
    
    img = await run_in_pool(draw, img, card)

    if not pcard and ok_to_cache:
        create_parent_folder(cache_path)
        img.save(cache_path)

    return img

# 获取卡牌所属团名（VS会返回对应的所属团）
async def get_unit_by_card_id(ctx: SekaiHandlerContext, card_id: int) -> str:
    card = await ctx.md.cards.find_by_id(card_id)
    if not card: raise Exception(f"卡牌ID={card_id}不存在")
    chara_unit = get_unit_by_chara_id(card['characterId'])
    if chara_unit != 'piapro':
        return chara_unit
    return card['supportUnit'] if card['supportUnit'] != "none" else "piapro"


# ======================= 处理逻辑 ======================= #

# 处理敏感指令抓包数据来源
def process_sensitive_cmd_source(data):
    if data.get('source') == 'haruki':
        data['source'] = 'remote'
    if data.get('local_source') == 'haruki':
        data['local_source'] = 'sync'

# 验证uid
def validate_uid(ctx: SekaiHandlerContext, uid: str) -> bool:
    uid = str(uid)
    if not (13 <= len(uid) <= 20) or not uid.isdigit():
        return False
    reg_time = get_register_time(ctx.region, uid)
    if not reg_time or not (datetime.strptime("2020-09-01", "%Y-%m-%d") <= reg_time <= datetime.now()):
        return False
    return True

# 获取游戏api相关配置
def get_gameapi_config(ctx: SekaiHandlerContext) -> GameApiConfig:
    return GameApiConfig(**(gameapi_config.get(ctx.region, {})))
b'1'.decode()
# 请求游戏API data_type: json/bytes/None
async def request_gameapi(url: str, method: str = 'GET', data_type: str | None = 'json', **kwargs):
    logger.debug(f"请求游戏API后端: {method} {url}")
    token = config.get('gameapi_token', '')
    haruki_api_token = config.get("haruki_api_token", '')
    headers = { 'Authorization': f'Bearer {token}', 'X-Haruki-Sekai-Token':haruki_api_token }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, headers=headers, verify_ssl=False, **kwargs) as resp:
                if resp.status != 200:
                    try:
                        detail = await resp.text()
                        detail = loads_json(detail)['detail']
                    except:
                        pass
                    utils_logger.error(f"请求游戏API后端 {url} 失败: {resp.status} {detail}")
                    raise HttpError(resp.status, detail)
                
                if data_type is None:
                    return resp
                elif data_type == 'json':
                    if "text/plain" in resp.content_type:
                        return loads_json(await resp.text())
                    elif "application/octet-stream" in resp.content_type:
                        import io
                        return loads_json(io.BytesIO(await resp.read()).read())
                    else:
                        return await resp.json()
                elif data_type == 'bytes':
                    return await resp.read()
                else:
                    raise Exception(f"不支持的数据类型: {data_type}")
                
    except aiohttp.ClientConnectionError as e:
        raise Exception(f"连接游戏API后端失败，请稍后再试")
            
# 获取qq用户绑定的游戏id
def get_player_bind_id(ctx: SekaiHandlerContext, qid: int, check_bind=True) -> str:
    qid = str(qid)
    bind_list: Dict[str, str] = profile_db.get("bind_list", {}).get(ctx.region, {})
    if check_bind and not bind_list.get(qid, None):
        region = "" if ctx.region == "jp" else ctx.region
        raise ReplyException(f"请使用\"/{region}绑定 你的游戏ID\"绑定账号")
    uid = bind_list.get(qid, None)
    assert_and_reply(not check_uid_in_blacklist(uid), f"该游戏ID({uid})已被拉入黑名单")
    return uid

# 根据游戏id获取玩家基本信息
async def get_basic_profile(ctx: SekaiHandlerContext, uid: int, use_cache=True, use_remote_cache=True, raise_when_no_found=True) -> dict:
    cache_path = f"{SEKAI_PROFILE_DIR}/profile_cache/{ctx.region}/{uid}.json"
    try:
        url = get_gameapi_config(ctx).profile_api_url
        assert_and_reply(url, f"暂不支持查询 {ctx.region} 服务器的玩家信息")
        profile = await request_gameapi(url.format(uid=uid) + f"?use_cache={use_remote_cache}")
        if raise_when_no_found:
            assert_and_reply(profile, f"找不到ID为 {uid} 的玩家")
        elif not profile:
            return {}
        dump_json(profile, cache_path)
        return profile
    except Exception as e:
        if use_cache and os.path.exists(cache_path):
            logger.print_exc(f"获取{uid}基本信息失败，使用缓存数据")
            profile = load_json(cache_path)
            return profile
        raise e

# 获取玩家基本信息的简单卡片控件，返回Frame
async def get_basic_profile_card(ctx: SekaiHandlerContext, profile: dict) -> Frame:
    with Frame().set_bg(roundrect_bg()).set_padding(16) as f:
        with HSplit().set_content_align('c').set_item_align('c').set_sep(14):
            avatar_info = await get_player_avatar_info_by_basic_profile(ctx, profile)

            frames = get_player_frames(ctx, profile['user']['userId'], None)
            await get_avatar_widget_with_frame(ctx, avatar_info.img, 80, frames)

            with VSplit().set_content_align('c').set_item_align('l').set_sep(5):
                game_data = profile['user']
                user_id = process_hide_uid(ctx, game_data['userId'])
                colored_text_box(
                    truncate(game_data['name'], 64),
                    TextStyle(font=DEFAULT_BOLD_FONT, size=24, color=BLACK, use_shadow=True, shadow_offset=2, shadow_color=ADAPTIVE_SHADOW),
                )
                TextBox(f"{ctx.region.upper()}: {user_id}", TextStyle(font=DEFAULT_FONT, size=16, color=BLACK))
    return f

# 从玩家基本信息获取该玩家头像PlayerAvatarInfo
async def get_player_avatar_info_by_basic_profile(ctx: SekaiHandlerContext, basic_profile: dict) -> PlayerAvatarInfo:
    decks = basic_profile['userDeck']
    pcards = [find_by(basic_profile['userCards'], 'cardId', decks[f'member{i}']) for i in range(1, 6)]
    for pcard in pcards:
        pcard['after_training'] = pcard['defaultImage'] == "special_training" and pcard['specialTrainingStatus'] == "done"
    card_id = pcards[0]['cardId']
    avatar_img = await get_card_thumbnail(ctx, card_id, pcards[0]['after_training'])
    cid = (await ctx.md.cards.find_by_id(card_id))['characterId']
    unit = await get_unit_by_card_id(ctx, card_id)
    return PlayerAvatarInfo(card_id, cid, unit, avatar_img)

# 查询抓包数据获取模式
def get_user_data_mode(ctx: SekaiHandlerContext, qid: int) -> str:
    data_modes = profile_db.get("data_modes", {})
    return data_modes.get(ctx.region, {}).get(str(qid), DEFAULT_DATA_MODE)

# 用户是否隐藏抓包信息
def is_user_hide_suite(ctx: SekaiHandlerContext, qid: int) -> bool:
    hide_list = profile_db.get("hide_suite_list", {}).get(ctx.region, [])
    return qid in hide_list

# 用户是否隐藏id
def is_user_hide_id(region: str, qid: int) -> bool:
    hide_list = profile_db.get("hide_id_list", {}).get(region, [])
    return qid in hide_list

# 如果ctx的用户隐藏id则返回隐藏的uid，否则原样返回
def process_hide_uid(ctx: SekaiHandlerContext, uid: int, keep: int=0) -> bool:
    if is_user_hide_id(ctx.region, ctx.user_id):
        if keep:
            return "*" * (16 - keep) + str(uid)[-keep:]
        return "*" * 16
    return uid

# 根据获取玩家详细信息，返回(profile, err_msg)
async def get_detailed_profile(
    ctx: SekaiHandlerContext, 
    qid: int, 
    raise_exc=False, 
    mode=None, 
    ignore_hide=False, 
    filter: list[str]=None,
) -> Tuple[dict, str]:
    cache_path = None
    try:
        # 获取绑定的游戏id
        try:
            uid = get_player_bind_id(ctx, qid, check_bind=True)
        except Exception as e:
            logger.info(f"获取 {qid} 抓包数据失败: 未绑定游戏账号")
            raise e
        
        # 检测是否隐藏抓包信息
        if not ignore_hide and is_user_hide_suite(ctx, qid):
            logger.info(f"获取 {qid} 抓包数据失败: 用户已隐藏抓包信息")
            raise ReplyException(f"你已隐藏抓包信息，发送\"/{ctx.region}展示抓包\"可重新展示")
        
        # 服务器不支持
        url = get_gameapi_config(ctx).suite_api_url
        if not url:
            raise ReplyException(f"暂不支持查询{get_region_name(ctx.region)}的抓包数据")
        
        # 数据获取模式
        mode = mode or get_user_data_mode(ctx, qid)

        # 尝试下载
        try:   
            url = url.format(uid=uid) + f"?mode={mode}"
            if filter:
                url += f"&key={','.join(filter)}"
            elif ( haruki_profile_keys:= config.get("haruki_profile_keys", [])):
                url += f"&key={','.join(haruki_profile_keys)}"
                pass
            profile = await request_gameapi(url)
        except HttpError as e:
            logger.info(f"获取 {qid} 抓包数据失败: {get_exc_desc(e)}")
            if e.status_code == 404:
                # local_err = e.message.get('local_err', None)
                # haruki_err = e.message.get('haruki_err', None)
                haruki_err = e.message
                msg = f"获取你的{get_region_name(ctx.region)}Suite抓包数据失败，发送\"/抓包\"指令可获取帮助\n"
                # if local_err is not None: msg += f"[本地数据] {local_err}\n"
                if haruki_err is not None: msg += f"[Haruki工具箱] {haruki_err}\n"
                raise ReplyException(msg.strip())
            else:
                raise e
        except Exception as e:
            logger.info(f"获取 {qid} 抓包数据失败: {get_exc_desc(e)}")
            raise e
            
        if not profile:
            logger.info(f"获取 {qid} 抓包数据失败: 找不到ID为 {uid} 的玩家")
            raise ReplyException(f"找不到ID为 {uid} 的玩家")
        
        # 缓存数据（目前已不缓存）
        cache_path = f"{SEKAI_PROFILE_DIR}/suite_cache/{ctx.region}/{uid}.json"
        # if not upload_time_only:
        #     dump_json(profile, cache_path)
        logger.info(f"获取 {qid} 抓包数据成功，数据已缓存")
        
    except Exception as e:
        # 获取失败的情况，尝试读取缓存
        if cache_path and os.path.exists(cache_path):
            profile = load_json(cache_path)
            logger.info(f"从缓存获取{qid}抓包数据")
            return profile, str(e) + "(使用先前的缓存数据)"
        else:
            logger.info(f"未找到 {qid} 的缓存抓包数据")

        if raise_exc:
            raise e
        else:
            return None, str(e)
        
    return profile, ""

# 从玩家详细信息获取该玩家头像的PlayerAvatarInfo
async def get_player_avatar_info_by_detailed_profile(ctx: SekaiHandlerContext, detail_profile: dict) -> PlayerAvatarInfo:
    deck_id = detail_profile['userGamedata']['deck']
    decks = find_by(detail_profile['userDecks'], 'deckId', deck_id)
    pcards = [find_by(detail_profile['userCards'], 'cardId', decks[f'member{i}']) for i in range(1, 6)]
    for pcard in pcards:
        pcard['after_training'] = pcard['defaultImage'] == "special_training" and pcard['specialTrainingStatus'] == "done"
    card_id = pcards[0]['cardId']
    avatar_img = await get_card_thumbnail(ctx, card_id, pcards[0]['after_training'])
    cid = (await ctx.md.cards.find_by_id(card_id))['characterId']
    unit = await get_unit_by_card_id(ctx, card_id)
    return PlayerAvatarInfo(card_id, cid, unit, avatar_img)

# 获取玩家详细信息的简单卡片控件，返回Frame
async def get_detailed_profile_card(ctx: SekaiHandlerContext, profile: dict, err_msg: str, mode=None) -> Frame:
    with Frame().set_bg(roundrect_bg()).set_padding(16) as f:
        with HSplit().set_content_align('c').set_item_align('c').set_sep(14):
            if profile:
                avatar_info = await get_player_avatar_info_by_detailed_profile(ctx, profile)

                frames = get_player_frames(ctx, profile['userGamedata']['userId'], profile)
                await get_avatar_widget_with_frame(ctx, avatar_info.img, 80, frames)

                with VSplit().set_content_align('c').set_item_align('l').set_sep(5):
                    game_data = profile['userGamedata']
                    source = profile.get('source', '?')
                    if local_source := profile.get('local_source'):
                        source += f"({local_source})"
                    mode = mode or get_user_data_mode(ctx, ctx.user_id)
                    # update_time = datetime.fromtimestamp(profile['upload_time'] / 1000) # DEBUG
                    update_time = datetime.fromtimestamp(profile['upload_time'])
                    update_time_text = update_time.strftime('%m-%d %H:%M:%S') + f" ({get_readable_datetime(update_time, show_original_time=False)})"
                    user_id = process_hide_uid(ctx, game_data['userId'])
                    colored_text_box(
                        truncate(game_data['name'], 64),
                        TextStyle(font=DEFAULT_BOLD_FONT, size=24, color=BLACK, use_shadow=True, shadow_offset=2),
                    )
                    TextBox(f"{ctx.region.upper()}: {user_id} Suite数据", TextStyle(font=DEFAULT_FONT, size=16, color=BLACK))
                    TextBox(f"更新时间: {update_time_text}", TextStyle(font=DEFAULT_FONT, size=16, color=BLACK))
                    TextBox(f"数据来源: {source}  获取模式: {mode}", TextStyle(font=DEFAULT_FONT, size=16, color=BLACK))
            if err_msg:
                TextBox(f"获取数据失败: {err_msg}", TextStyle(font=DEFAULT_FONT, size=20, color=RED), line_count=3).set_w(300)
    return f

# 获取注册时间，无效uid返回None
def get_register_time(region: str, uid: str) -> datetime:
    try:
        if region in ['jp', 'en']:
            time = int(uid[:-3]) / 1024 / 4096
            return datetime.fromtimestamp(1600218000 + int(time))
        elif region in ['tw', 'cn', 'kr']:
            time = int(uid) / 1024 / 1024 / 4096
            return datetime.fromtimestamp(int(time))
    except ValueError:
        return None

# 合成个人信息图片
async def compose_profile_image(ctx: SekaiHandlerContext, basic_profile: dict, vertical: bool=None) -> Image.Image:
    bg_settings = get_profile_bg_settings(ctx)
    detail_profile, _ = await get_detailed_profile(
        ctx, ctx.user_id, raise_exc=False, ignore_hide=True, 
        filter=['upload_time', 'userPlayerFrames'],
    )
    uid = str(basic_profile['user']['userId'])

    decks = basic_profile['userDeck']
    pcards = [find_by(basic_profile['userCards'], 'cardId', decks[f'member{i}']) for i in range(1, 6)]
    for pcard in pcards:
        pcard['after_training'] = pcard['defaultImage'] == "special_training" and pcard['specialTrainingStatus'] == "done"
    avatar_info = await get_player_avatar_info_by_basic_profile(ctx, basic_profile)

    bg = ImageBg(bg_settings.image, blur=False, fade=0) if bg_settings.image else random_unit_bg(avatar_info.unit)
    ui_bg = roundrect_bg(fill=(255, 255, 255, bg_settings.alpha), blurglass=True, blurglass_kwargs={'blur': bg_settings.blur})

    # 个人信息部分
    async def draw_info():
        with VSplit().set_bg(ui_bg).set_content_align('c').set_item_align('c').set_sep(32).set_padding((32, 35)) as ret:
            # 名片
            with HSplit().set_content_align('c').set_item_align('c').set_sep(32).set_padding((32, 0)):
                frames = get_player_frames(ctx, uid, detail_profile)
                await get_avatar_widget_with_frame(ctx, avatar_info.img, 128, frames)

                with VSplit().set_content_align('c').set_item_align('l').set_sep(16):
                    game_data = basic_profile['user']
                    colored_text_box(
                        truncate(game_data['name'], 64),
                        TextStyle(font=DEFAULT_BOLD_FONT, size=32, color=ADAPTIVE_WB, use_shadow=True, shadow_offset=2),
                    )
                    TextBox(f"{ctx.region.upper()}: {process_hide_uid(ctx, game_data['userId'])}", TextStyle(font=DEFAULT_FONT, size=20, color=ADAPTIVE_WB))
                    with Frame():
                        ImageBox(ctx.static_imgs.get("lv_rank_bg.png"), size=(180, None))
                        TextBox(f"{game_data['rank']}", TextStyle(font=DEFAULT_FONT, size=30, color=WHITE)).set_offset((110, 0))

            # 推特
            with Frame().set_content_align('l').set_w(450):
                tw_id = basic_profile['userProfile'].get('twitterId', '')
                tw_id_box = TextBox('        @ ' + tw_id, TextStyle(font=DEFAULT_FONT, size=20, color=ADAPTIVE_WB), line_count=1)
                tw_id_box.set_wrap(False).set_bg(ui_bg).set_line_sep(2).set_padding(10).set_w(300).set_content_align('l')
                x_icon = ctx.static_imgs.get("x_icon.png").resize((24, 24)).convert('RGBA')
                ImageBox(x_icon, image_size_mode='original').set_offset((16, 0))

            # 留言
            user_word = basic_profile['userProfile'].get('word', '')
            user_word = re.sub(r'<#.*?>', '', user_word)
            user_word_box = TextBox(user_word, TextStyle(font=DEFAULT_FONT, size=20, color=ADAPTIVE_WB), line_count=3)
            user_word_box.set_wrap(True).set_bg(ui_bg).set_line_sep(2).set_padding((18, 16)).set_w(450)

            # 头衔
            with HSplit().set_content_align('c').set_item_align('c').set_sep(8).set_padding((16, 0)):
                honors = basic_profile["userProfileHonors"]
                async def compose_honor_image_nothrow(*args):
                    try: return await compose_full_honor_image(*args)
                    except: 
                        logger.print_exc("合成头衔图片失败")
                        return None
                honor_imgs = await asyncio.gather(*[
                    compose_honor_image_nothrow(ctx, find_by(honors, 'seq', 1), True, basic_profile),
                    compose_honor_image_nothrow(ctx, find_by(honors, 'seq', 2), False, basic_profile),
                    compose_honor_image_nothrow(ctx, find_by(honors, 'seq', 3), False, basic_profile)
                ])
                for img in honor_imgs:
                    if img: 
                        ImageBox(img, size=(None, 48))
            # 卡组
            with HSplit().set_content_align('c').set_item_align('c').set_sep(6).set_padding((16, 0)):
                card_ids = [pcard['cardId'] for pcard in pcards]
                cards = await ctx.md.cards.collect_by_ids(card_ids)
                card_imgs = [
                    await get_card_full_thumbnail(ctx, card, pcard=pcard)
                    for card, pcard in zip(cards, pcards)
                ]
                for i in range(len(card_imgs)):
                    ImageBox(card_imgs[i], size=(90, 90), image_size_mode='fill')
        return ret

    # 打歌部分
    async def draw_play(): 
        with HSplit().set_content_align('c').set_item_align('t').set_sep(12).set_bg(ui_bg).set_padding(32) as ret:
            hs, vs, gw, gh = 8, 12, 90, 25
            with VSplit().set_sep(vs):
                Spacer(gh, gh)
                ImageBox(ctx.static_imgs.get(f"icon_clear.png"), size=(gh, gh))
                ImageBox(ctx.static_imgs.get(f"icon_fc.png"), size=(gh, gh))
                ImageBox(ctx.static_imgs.get(f"icon_ap.png"), size=(gh, gh))
            with Grid(col_count=6).set_sep(hsep=hs, vsep=vs):
                for diff, color in DIFF_COLORS.items():
                    t = TextBox(diff.upper(), TextStyle(font=DEFAULT_BOLD_FONT, size=16, color=WHITE))
                    t.set_bg(RoundRectBg(fill=color, radius=3)).set_size((gw, gh)).set_content_align('c')
                diff_count = basic_profile['userMusicDifficultyClearCount']
                scores = ['liveClear', 'fullCombo', 'allPerfect']
                play_result = ['clear', 'fc', 'ap']
                for i, score in enumerate(scores):
                    for j, diff in enumerate(DIFF_COLORS.keys()):
                        bg_color = (255, 255, 255, 150) if j % 2 == 0 else (255, 255, 255, 100)
                        count = find_by(diff_count, 'musicDifficultyType', diff)[score]
                        TextBox(str(count), TextStyle(
                                DEFAULT_FONT, 20, PLAY_RESULT_COLORS['not_clear'], use_shadow=True,
                                shadow_color=PLAY_RESULT_COLORS[play_result[i]], shadow_offset=1,
                            )).set_bg(RoundRectBg(fill=bg_color, radius=3)).set_size((gw, gh)).set_content_align('c')
        return ret
    
    # 养成部分
    async def draw_chara():
        with Frame().set_content_align('rb').set_bg(ui_bg) as ret:
            hs, vs, gw, gh = 8, 7, 96, 48
            # 角色等级
            with Grid(col_count=6).set_sep(hsep=hs, vsep=vs).set_padding(32):
                chara_list = [
                    "miku", "rin", "len", "luka", "meiko", "kaito", 
                    "ick", "saki", "hnm", "shiho", None, None,
                    "mnr", "hrk", "airi", "szk", None, None,
                    "khn", "an", "akt", "toya", None, None,
                    "tks", "emu", "nene", "rui", None, None,
                    "knd", "mfy", "ena", "mzk", None, None,
                ]
                for chara in chara_list:
                    if chara is None:
                        Spacer(gw, gh)
                        continue
                    cid = int(get_cid_by_nickname(chara))
                    rank = find_by(basic_profile['userCharacters'], 'characterId', cid)['characterRank']
                    with Frame().set_size((gw, gh)):
                        chara_img = ctx.static_imgs.get(f'chara_rank_icon/{chara}.png')
                        ImageBox(chara_img, size=(gw, gh), use_alphablend=True)
                        t = TextBox(str(rank), TextStyle(font=DEFAULT_FONT, size=20, color=(40, 40, 40, 255)))
                        t.set_size((60, 48)).set_content_align('c').set_offset((36, 4))
            
            # 挑战Live等级
            if 'userChallengeLiveSoloResult' in basic_profile:
                solo_live_result = basic_profile['userChallengeLiveSoloResult']
                if isinstance(solo_live_result, list):
                    solo_live_result = sorted(solo_live_result, key=lambda x: x['highScore'], reverse=True)[0]
                cid, score = solo_live_result['characterId'], solo_live_result['highScore']
                stages = find_by(basic_profile['userChallengeLiveSoloStages'], 'characterId', cid, mode='all')
                stage_rank = max([stage['rank'] for stage in stages])
                
                with VSplit().set_content_align('c').set_item_align('c').set_padding((32, 64)).set_sep(12):
                    t = TextBox(f"CHANLLENGE LIVE", TextStyle(font=DEFAULT_FONT, size=18, color=(50, 50, 50, 255)))
                    t.set_bg(roundrect_bg(radius=6)).set_padding((10, 7))
                    with Frame():
                        chara_img = ctx.static_imgs.get(f'chara_rank_icon/{get_character_first_nickname(cid)}.png')
                        ImageBox(chara_img, size=(100, 50), use_alphablend=True)
                        t = TextBox(str(stage_rank), TextStyle(font=DEFAULT_FONT, size=22, color=(40, 40, 40, 255)), overflow='clip')
                        t.set_size((50, 50)).set_content_align('c').set_offset((40, 5))
                    t = TextBox(f"SCORE {score}", TextStyle(font=DEFAULT_FONT, size=18, color=(50, 50, 50, 255)))
                    t.set_bg(roundrect_bg(radius=6)).set_padding((10, 7))
        return ret

    if vertical is None:
        vertical = bg_settings.vertical

    with Canvas(bg=bg).set_padding(BG_PADDING) as canvas:
        if not vertical:
            with HSplit().set_content_align('lt').set_item_align('lt').set_sep(16):
                await draw_info()
                with VSplit().set_content_align('c').set_item_align('c').set_sep(16):
                    await draw_play()
                    await draw_chara()
        else:
            with VSplit().set_content_align('c').set_item_align('c').set_sep(16).set_item_bg(ui_bg):
                (await draw_info()).set_bg(None)
                (await draw_play()).set_bg(None)
                (await draw_chara()).set_bg(None)

    if 'update_time' in basic_profile:
        update_time = datetime.fromtimestamp(basic_profile['update_time'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
    else:
        update_time = "?"
    text = f"DT: {update_time}  " + DEFAULT_WATERMARK_CFG.get()
    if bg_settings.image:
        text = text + f"  This background is user-uploaded."
    add_watermark(canvas, text)
    return await canvas.get_img(1.5)

# 检测游戏id是否在黑名单中
def check_uid_in_blacklist(uid: str) -> bool:
    blacklist = profile_db.get("blacklist", [])
    return uid in blacklist

# 获取玩家挑战live信息，返回（rank, score, remain_jewel, remain_fragment）
async def get_user_challenge_live_info(ctx: SekaiHandlerContext, profile: dict) -> Dict[int, Tuple[int, int, int, int]]:
    challenge_info = {}
    challenge_results = profile['userChallengeLiveSoloResults']
    challenge_stages = profile['userChallengeLiveSoloStages']
    challenge_rewards = profile['userChallengeLiveSoloHighScoreRewards']
    for cid in range(1, 27):
        stages = find_by(challenge_stages, 'characterId', cid, mode='all')
        rank = max([stage['rank'] for stage in stages]) if stages else 0
        result = find_by(challenge_results, 'characterId', cid)
        score = result['highScore'] if result else 0
        remain_jewel, remain_fragment = 0, 0
        completed_reward_ids = [item['challengeLiveHighScoreRewardId'] for item in find_by(challenge_rewards, 'characterId', cid, mode='all')]
        for reward in await ctx.md.challenge_live_high_score_rewards.get():
            if reward['id'] in completed_reward_ids or reward['characterId'] != cid:
                continue
            res_box = await get_res_box_info(ctx, 'challenge_live_high_score', reward['resourceBoxId'])
            for res in res_box:
                if res['type'] == 'jewel':
                    remain_jewel += res['quantity']
                if res['type'] == 'material' and res['id'] == 15:
                    remain_fragment += res['quantity']
        challenge_info[cid] = (rank, score, remain_jewel, remain_fragment)
    return challenge_info

# 合成挑战live详情图片
async def compose_challenge_live_detail_image(ctx: SekaiHandlerContext, qid: int) -> Image.Image:
    profile, err_msg = await get_detailed_profile(ctx, qid, raise_exc=True)
    avatar_info = await get_player_avatar_info_by_detailed_profile(ctx, profile)

    challenge_info = await get_user_challenge_live_info(ctx, profile)

    header_h, row_h = 56, 48
    header_style = TextStyle(font=DEFAULT_BOLD_FONT, size=24, color=(25, 25, 25, 255))
    text_style = TextStyle(font=DEFAULT_FONT, size=20, color=(50, 50, 50, 255))
    w1, w2, w3, w4, w5, w6 = 80, 80, 150, 300, 80, 80

    max_score = max([item['highScore'] for item in await ctx.md.challenge_live_high_score_rewards.get()])

    with Canvas(bg=SEKAI_BLUE_BG).set_padding(BG_PADDING) as canvas:
        with VSplit().set_content_align('lt').set_item_align('lt').set_sep(16):
            await get_detailed_profile_card(ctx, profile, err_msg)
            with VSplit().set_content_align('c').set_item_align('c').set_sep(8).set_padding(16).set_bg(roundrect_bg()):
                # 标题
                with HSplit().set_content_align('c').set_item_align('c').set_sep(8).set_h(header_h).set_padding(4).set_bg(roundrect_bg()):
                    TextBox("角色", header_style).set_w(w1).set_content_align('c')
                    TextBox("等级", header_style).set_w(w2).set_content_align('c')
                    TextBox("分数", header_style).set_w(w3).set_content_align('c')
                    TextBox(f"进度(上限{max_score//10000}w)", header_style).set_w(w4).set_content_align('c')
                    with Frame().set_w(w5).set_content_align('c'):
                        ImageBox(ctx.static_imgs.get("jewel.png"), size=(None, 40))
                    with Frame().set_w(w6).set_content_align('c'):
                        ImageBox(ctx.static_imgs.get("shard.png"), size=(None, 40))

                # 项目
                for cid in range(1, 27):
                    bg_color = (255, 255, 255, 150) if cid % 2 == 0 else (255, 255, 255, 100)
                    rank = str(challenge_info[cid][0]) if challenge_info[cid][0] else "-"
                    score = str(challenge_info[cid][1]) if challenge_info[cid][1] else "-"
                    jewel = str(challenge_info[cid][2])
                    fragment = str(challenge_info[cid][3])
                    with HSplit().set_content_align('c').set_item_align('c').set_sep(8).set_h(row_h).set_padding(4).set_bg(roundrect_bg(fill=bg_color)):
                        with Frame().set_w(w1).set_content_align('c'):
                            ImageBox(get_chara_icon_by_chara_id(cid), size=(None, 40))
                        TextBox(rank, text_style).set_w(w2).set_content_align('c')
                        TextBox(score, text_style).set_w(w3).set_content_align('c')
                        with Frame().set_w(w4).set_content_align('lt'):
                            x = challenge_info[cid][1]
                            progress = max(min(x / max_score, 1), 0)
                            total_w, total_h, border = w4, 10, 2
                            progress_w = int((total_w - border * 2) * progress)
                            progress_h = total_h - border * 2
                            color = (255, 50, 50, 255)
                            if x > 250_0000:    color = (100, 255, 100, 255)
                            elif x > 200_0000:  color = (255, 255, 100, 255)
                            elif x > 150_0000:  color = (255, 200, 100, 255)
                            elif x > 100_0000:  color = (255, 150, 100, 255)
                            elif x > 50_0000:   color = (255, 100, 100, 255)
                            if progress > 0:
                                Spacer(w=total_w, h=total_h).set_bg(RoundRectBg(fill=(100, 100, 100, 255), radius=total_h//2))
                                Spacer(w=progress_w, h=progress_h).set_bg(RoundRectBg(fill=color, radius=(total_h-border)//2)).set_offset((border, border))
                            else:
                                Spacer(w=total_w, h=total_h).set_bg(RoundRectBg(fill=(100, 100, 100, 100), radius=total_h//2))
                        TextBox(jewel, text_style).set_w(w5).set_content_align('c')
                        TextBox(fragment, text_style).set_w(w6).set_content_align('c')

    add_watermark(canvas)
    return await canvas.get_img()

# 获取玩家加成信息
async def get_user_power_bonus(ctx: SekaiHandlerContext, profile: dict) -> Dict[str, int]:
    # 获取区域道具
    area_items: List[dict] = []
    for user_area in profile['userAreas']:
        for user_area_item in user_area.get('areaItems', []):
            item_id = user_area_item['areaItemId']
            lv = user_area_item['level']
            area_items.append(find_by(find_by(await ctx.md.area_item_levels.get(), 'areaItemId', item_id, mode='all'), 'level', lv))

    # 角色加成 = 区域道具 + 角色等级 + 烤森家具
    chara_bonus = { i : {
        'area_item': 0,
        'rank': 0,
        'fixture': 0,
    } for i in range(1, 27) }
    for item in area_items:
        if item.get('targetGameCharacterId', "any") != "any":
            chara_bonus[item['targetGameCharacterId']]['area_item'] += item['power1BonusRate']
    for chara in profile['userCharacters']:
        rank = find_by(await ctx.md.character_ranks.find_by('characterId', chara['characterId'], mode='all'), 'characterRank', chara['characterRank'])
        chara_bonus[chara['characterId']]['rank'] += rank['power1BonusRate']
    for fb in profile.get('userMysekaiFixtureGameCharacterPerformanceBonuses', []):
        chara_bonus[fb['gameCharacterId']]['fixture'] += fb['totalBonusRate'] * 0.1
    
    # 组合加成 = 区域道具 + 烤森门
    unit_bonus = { unit : {
        'area_item': 0,
        'gate': 0,
    } for unit in UNITS }
    for item in area_items:
        if item.get('targetUnit', "any") != "any":
            unit_bonus[item['targetUnit']]['area_item'] += item['power1BonusRate']
    max_bonus = 0
    for gate in profile.get('userMysekaiGates', []):
        gate_id = gate['mysekaiGateId']
        bonus = find_by(await ctx.md.mysekai_gate_levels.find_by('mysekaiGateId', gate_id, mode='all'), 'level', gate['mysekaiGateLevel'])
        unit_bonus[UNITS[gate_id - 1]]['gate'] += bonus['powerBonusRate']
        max_bonus = max(max_bonus, bonus['powerBonusRate'])
    unit_bonus[UNIT_VS]['gate'] += max_bonus

    # 属性加成 = 区域道具
    attr_bouns = { attr : {
        'area_item': 0,
    } for attr in CARD_ATTRS }
    for item in area_items:
        if item.get('targetCardAttr', "any") != "any":
            attr_bouns[item['targetCardAttr']]['area_item'] += item['power1BonusRate']

    for _, bonus in chara_bonus.items():
        bonus['total'] = sum(bonus.values())
    for _, bonus in unit_bonus.items():
        bonus['total'] = sum(bonus.values())
    for _, bonus in attr_bouns.items():
        bonus['total'] = sum(bonus.values())
    
    return {
        "chara": chara_bonus,
        "unit": unit_bonus,
        "attr": attr_bouns
    }

# 合成加成详情图片
async def compose_power_bonus_detail_image(ctx: SekaiHandlerContext, qid: int) -> Image.Image:
    profile, err_msg = await get_detailed_profile(ctx, qid, raise_exc=True)
    avatar_info = await get_player_avatar_info_by_detailed_profile(ctx, profile)

    bonus = await get_user_power_bonus(ctx, profile)
    chara_bonus = bonus['chara']
    unit_bonus = bonus['unit']
    attr_bonus = bonus['attr']

    header_h, row_h = 56, 48
    header_style = TextStyle(font=DEFAULT_BOLD_FONT, size=24, color=(25, 25, 25, 255))
    text_style = TextStyle(font=DEFAULT_FONT, size=16, color=(100, 100, 100, 255))

    with Canvas(bg=SEKAI_BLUE_BG).set_padding(BG_PADDING) as canvas:
        with VSplit().set_content_align('lt').set_item_align('lt').set_sep(16):
            await get_detailed_profile_card(ctx, profile, err_msg)
            with VSplit().set_content_align('lt').set_item_align('lt').set_sep(8).set_item_bg(roundrect_bg()).set_bg(roundrect_bg()).set_padding(16):
                # 角色加成
                cid_parts = [range(1, 5), range(5, 9), range(9, 13), range(13, 17), range(17, 21), range(21, 27)]
                for cids in cid_parts:
                    with Grid(col_count=2).set_content_align('l').set_item_align('l').set_sep(20, 4).set_padding(16):
                        for cid in cids:
                            with HSplit().set_content_align('l').set_item_align('l').set_sep(4):
                                ImageBox(get_chara_icon_by_chara_id(cid), size=(None, 40))
                                TextBox(f"{chara_bonus[cid]['total']:.1f}%", header_style).set_w(100).set_content_align('r').set_overflow('clip')
                                detail = f"区域道具{chara_bonus[cid]['area_item']:.1f}% + 角色等级{chara_bonus[cid]['rank']:.1f}% + 烤森玩偶{chara_bonus[cid]['fixture']:.1f}%"
                                TextBox(detail, text_style)
                        
                # 组合加成
                with Grid(col_count=3).set_content_align('l').set_item_align('l').set_sep(20, 4).set_padding(16):
                    for unit in UNITS:
                        with HSplit().set_content_align('l').set_item_align('l').set_sep(4):
                            ImageBox(get_unit_icon(unit), size=(None, 40))
                            TextBox(f"{unit_bonus[unit]['total']:.1f}%", header_style).set_w(100).set_content_align('r').set_overflow('clip')
                            detail = f"区域道具{unit_bonus[unit]['area_item']:.1f}% + 烤森门{unit_bonus[unit]['gate']:.1f}%"
                            TextBox(detail, text_style)

                # 属性加成
                with Grid(col_count=5).set_content_align('l').set_item_align('l').set_sep(20, 4).set_padding(16):
                    for attr in CARD_ATTRS:
                        with HSplit().set_content_align('l').set_item_align('l').set_sep(4):
                            ImageBox(get_attr_icon(attr), size=(None, 40))
                            TextBox(f"{attr_bonus[attr]['total']:.1f}%", header_style).set_w(100).set_content_align('r').set_overflow('clip')
                            # detail = f"区域道具{attr_bonus[attr]['area_item']:.1f}%"
                            # TextBox(detail, text_style)

    add_watermark(canvas)
    return await canvas.get_img()

# 验证用户游戏帐号
async def verify_user_game_account(ctx: SekaiHandlerContext):
    verified_uids = get_user_verified_uids(ctx)
    uid = get_player_bind_id(ctx, ctx.user_id, check_bind=True)
    assert_and_reply(uid not in verified_uids, f"你当前绑定的{get_region_name(ctx.region)}帐号已经验证过")

    def generate_verify_code() -> str:
        while True:
            code = str(random.randint(1000, 9999))
            code = '/'.join(code)
            hit = False
            for codes in _region_qid_verify_codes.values():
                if any(info.verify_code == code for info in codes.values()):
                    hit = True
                    break
            if hit:
                continue
            return code
    
    qid = ctx.user_id
    if ctx.region not in _region_qid_verify_codes:
        _region_qid_verify_codes[ctx.region] = {}

    info = None
    err_msg = ""
    if qid in _region_qid_verify_codes[ctx.region]:
        info = _region_qid_verify_codes[ctx.region][qid]
        if info.expire_time < datetime.now():
            err_msg = f"你的上次验证已过期\n"
        if info.uid != uid:
            err_msg = f"开始验证时绑定的帐号与当前绑定帐号不一致\n"
        if err_msg:
            _region_qid_verify_codes[ctx.region].pop(qid, None)
            info = None
    
    if not info:
        # 首次验证
        info = VerifyCode(
            region=ctx.region,
            qid=qid,
            uid=uid,
            verify_code=generate_verify_code(),
            expire_time=datetime.now() + VERIFY_CODE_EXPIRE_TIME,
        )
        _region_qid_verify_codes[ctx.region][qid] = info
        raise ReplyException(f"""
{err_msg}请在你当前绑定的{get_region_name(ctx.region)}帐号({process_hide_uid(ctx, info.uid, keep=6)})的游戏名片的简介(word)的末尾输入该验证码(不要去掉斜杠):
{info.verify_code}
编辑后需要退出名片界面以保存，然后在{get_readable_timedelta(VERIFY_CODE_EXPIRE_TIME)}内重新发送一次\"{ctx.original_trigger_cmd}\"以完成验证
""".strip())
    
    profile = await get_basic_profile(ctx, info.uid, use_cache=False, use_remote_cache=False)
    word: str = profile['userProfile'].get('word', '').strip()

    assert_and_reply(word.endswith(info.verify_code), f"""
验证失败，从你绑定的{get_region_name(ctx.region)}帐号留言末尾没有获取到验证码\"{info.verify_code}\"，请重试（验证码未改变）
""".strip())

    try:
        # 验证成功
        verify_accounts = profile_db.get(f"verify_accounts_{ctx.region}", {})
        verify_accounts.setdefault(str(qid), []).append(info.uid)
        profile_db.set(f"verify_accounts_{ctx.region}", verify_accounts)
        raise ReplyException(f"验证成功！使用\"/{ctx.region}pjsk验证列表\"可以查看你验证过的游戏ID")
    finally:
        _region_qid_verify_codes[ctx.region].pop(qid, None)

# 获取用户验证过的游戏ID列表
def get_user_verified_uids(ctx: SekaiHandlerContext) -> List[str]:
    return profile_db.get(f"verify_accounts_{ctx.region}", {}).get(str(ctx.user_id), [])

# 获取游戏id并检查用户是否验证过当前的游戏id，失败抛出异常
def get_uid_and_check_verified(ctx: SekaiHandlerContext, force: bool = False) -> str:
    uid = get_player_bind_id(ctx, ctx.user_id, check_bind=True)
    if not force:
        verified_uids = get_user_verified_uids(ctx)
        assert_and_reply(uid in verified_uids, f"""
该功能需要验证你的游戏帐号
请使用"/{ctx.region}pjsk验证"进行验证，使用"/{ctx.region}pjsk验证列表"查看你验证过的游戏ID
""".strip())
    return uid

# 个人信息背景设置
def set_profile_bg_settings(
    ctx: SekaiHandlerContext,
    image: Optional[Image.Image] = None,
    remove_image: bool = False,
    blur: Optional[int] = None,
    alpha: Optional[int] = None,
    vertical: Optional[bool] = None,
    force: bool = False
):
    uid = get_uid_and_check_verified(ctx, force)
    region = ctx.region
    image_path = PROFILE_BG_IMAGE_PATH.format(region=region, uid=uid)

    settings: Dict[str, Dict[str, Any]] = profile_bg_settings_db.get(region, {})
    
    if remove_image:
        if os.path.exists(image_path):
            os.remove(image_path)
    elif image:
        w, h = image.size
        w1, h1 = config.get('profile_bg_image_size.horizontal')
        w2, h2 = config.get('profile_bg_image_size.vertical')
        scale = -1
        if w > w1 and h > h1:
            scale = max(scale, w1 / w, h1 / h)
        if w > w2 and h > h2:
            scale = max(scale, w2 / w, h2 / h)
        if scale < 0:
            scale = 1
        target_w, target_h = int(w * scale), int(h * scale)
        assert_and_reply(min(target_w, target_h) < 10000, "上传图片的横纵比过大或过小")
        image = image.convert('RGB')
        if image.width > target_w:
            image = image.resize((target_w, target_h), Image.LANCZOS)
        save_kwargs = config.get('profile_bg_image_save_kwargs', {})
        create_parent_folder(image_path)
        image.save(image_path, **save_kwargs)
        settings.setdefault(uid, {})['vertical'] = target_w < target_h

    if blur is not None:
        blur = max(0, min(10, blur))
        settings.setdefault(uid, {})['blur'] = blur

    if alpha is not None:
        alpha = max(0, min(255, alpha))
        settings.setdefault(uid, {})['alpha'] = alpha

    if vertical is not None:
        settings.setdefault(uid, {})['vertical'] = vertical

    profile_bg_settings_db.set(region, settings)

# 个人信息背景设置获取
def get_profile_bg_settings(ctx: SekaiHandlerContext) -> ProfileBgSettings:
    uid = get_player_bind_id(ctx, ctx.user_id, check_bind=True)
    region = ctx.region
    try:
        image = open_image(PROFILE_BG_IMAGE_PATH.format(region=region, uid=uid))
    except:
        image = None
    settings = profile_bg_settings_db.get(region, {}).get(uid, {})
    ret = ProfileBgSettings(image=image, **settings)
    if ret.alpha is None:
        ret.alpha = WIDGET_BG_COLOR_CFG.get()[3]
    if ret.blur is None:
        ret.blur = 4
    return ret

# 获取玩家框信息，提供detail_profile会直接取用并更新缓存，否则使用缓存数据
def get_player_frames(ctx: SekaiHandlerContext, uid: str, detail_profile: Optional[dict] = None) -> List[dict]:
    uid = str(uid)
    all_cached_frames = player_frame_db.get(ctx.region, {})
    cached_frames = all_cached_frames.get(uid, {})
    if detail_profile:
        upload_time = detail_profile.get('upload_time', 0)
        frames = detail_profile.get('userPlayerFrames', [])
        if upload_time > cached_frames.get('upload_time', 0):
            # 更新缓存
            cached_frames = {
                'upload_time': upload_time,
                'frames': frames
            }
            if frames:
                all_cached_frames[uid] = cached_frames
                player_frame_db.set(ctx.region, all_cached_frames)
    return cached_frames.get('frames', [])

# 获取头像框图片，失败返回None
async def get_player_frame_image(ctx: SekaiHandlerContext, frame_id: int, frame_w: int) -> Image.Image | None:
    try:
        frame = await ctx.md.player_frames.find_by_id(frame_id)
        frame_group = await ctx.md.player_frame_groups.find_by_id(frame['playerFrameGroupId'])
        asset_name = frame_group['assetbundleName']
        asset_path = f"player_frame/{asset_name}/{frame_id}/"

        cache_path = f"{SEKAI_ASSET_DIR}/player_frames/{ctx.region}/{asset_name}_{frame_id}.png"

        scale = 1.5
        corner = 20
        corner2 = 50
        w = 700
        border = 100
        border2 = 80
        inner_w = w - 2*border

        if os.path.exists(cache_path):
            img = open_image(cache_path)
        else:
            base = await ctx.rip.img(asset_path + "horizontal/frame_base.png", allow_error=False)
            ct = await ctx.rip.img(asset_path + "vertical/frame_centertop.png", allow_error=False)
            lb = await ctx.rip.img(asset_path + "vertical/frame_leftbottom.png", allow_error=False)
            lt = await ctx.rip.img(asset_path + "vertical/frame_lefttop.png", allow_error=False)
            rb = await ctx.rip.img(asset_path + "vertical/frame_rightbottom.png", allow_error=False)
            rt = await ctx.rip.img(asset_path + "vertical/frame_righttop.png", allow_error=False)
            
            ct = resize_keep_ratio(ct, scale, mode='scale')
            lt = resize_keep_ratio(lt, scale, mode='scale')
            lb = resize_keep_ratio(lb, scale, mode='scale')
            rt = resize_keep_ratio(rt, scale, mode='scale')
            rb = resize_keep_ratio(rb, scale, mode='scale')

            bw = base.width
            base_lt = base.crop((0, 0, corner, corner))
            base_rt = base.crop((bw-corner, 0, bw, corner))
            base_lb = base.crop((0, bw-corner, corner, bw))
            base_rb = base.crop((bw-corner, bw-corner, bw, bw))
            base_l = base.crop((0, corner, corner, bw-corner))
            base_r = base.crop((bw-corner, corner, bw, bw-corner))
            base_t = base.crop((corner, 0, bw-corner, corner))
            base_b = base.crop((corner, bw-corner, bw-corner, bw))

            p = Painter(size=(w, w))

            p.move_region((border, border), (inner_w, inner_w))
            p.paste(base_lt, (0, 0), (corner2, corner2))
            p.paste(base_rt, (inner_w-corner2, 0), (corner2, corner2))
            p.paste(base_lb, (0, inner_w-corner2), (corner2, corner2))
            p.paste(base_rb, (inner_w-corner2, inner_w-corner2), (corner2, corner2))
            p.paste(base_l.resize((corner2, inner_w-2*corner2)), (0, corner2))
            p.paste(base_r.resize((corner2, inner_w-2*corner2)), (inner_w-corner2, corner2))
            p.paste(base_t.resize((inner_w-2*corner2, corner2)), (corner2, 0))
            p.paste(base_b.resize((inner_w-2*corner2, corner2)), (corner2, inner_w-corner2))
            p.restore_region()

            p.paste(lb, (border2, w-border2-lb.height))
            p.paste(rb, (w-border2-rb.width, w-border2-rb.height))
            p.paste(lt, (border2, border2))
            p.paste(rt, (w-border2-rt.width, border2))
            p.paste(ct, ((w-ct.width)//2, border2-ct.height//2))

            img = await p.get()
            create_parent_folder(cache_path)
            img.save(cache_path)

        img = resize_keep_ratio(img, frame_w / inner_w, mode='scale')
        return img

    except:
        logger.print_exc(f"获取playerFrame {frame_id} 失败")
        return None
    
# 获取带框头像控件
async def get_avatar_widget_with_frame(ctx: SekaiHandlerContext, avatar_img: Image.Image, avatar_w: int, frame_data: list[dict]) -> Frame:
    frame_img = None
    try:
        if frame := find_by(frame_data, 'playerFrameAttachStatus', "first"):
            frame_img = await get_player_frame_image(ctx, frame['playerFrameId'], avatar_w + 5)
    except:
        pass
    with Frame().set_size((avatar_w, avatar_w)).set_content_align('c').set_allow_draw_outside(True) as ret:
        ImageBox(avatar_img, size=(avatar_w, avatar_w), use_alphablend=False)
        if frame_img:
            ImageBox(frame_img, use_alphablend=True)
    return ret

# 合成区域道具升级材料图片
async def compose_area_item_upgrade_materials_image(ctx: SekaiHandlerContext, qid: int, filter: AreaItemFilter) -> Image.Image:
    profile = None
    if qid:
        profile, pmsg = await get_detailed_profile(ctx, qid, raise_exc=True, ignore_hide=True)

    COIN_ID = -1
    user_materials: dict[int, int] = {}
    user_area_item_lvs: dict[int, int] = {}
    
    if profile:
        # 获取玩家材料（金币当作id=-1的材料）
        assert_and_reply('userMaterials' in profile, "你的Suite数据来源没有提供userMaterials数据（可能需要重传）")
        user_materials = {}
        user_materials[COIN_ID] = profile['userGamedata'].get('coin', 0)
        for item in profile.get('userMaterials', []):
            user_materials[item['materialId']] = item['quantity']
        # 获取玩家区域道具等级
        user_area_item_lvs = {}
        for area in profile.get('userAreas', []):
            for area_item in area.get('areaItems', []):
                user_area_item_lvs[area_item['areaItemId']] = area_item['level']

    # 筛选vs额外判断
    filter_piapro = False
    if filter.unit == 'piapro':
        filter.unit = None
        filter_piapro = True

    # 获取区域道具信息，同时筛选需要展示的区域道具id
    item_ids: set[int] = set()
    area_item_icons: dict[int, Image.Image] = {}
    area_item_target_icons: dict[int, Image.Image] = {}
    area_item_level_bonuses: dict[int, dict[int, float]] = {}
    area_item_max_levels: dict[int, int] = {}
    for item in await ctx.md.area_items.get():
        item_id, area_id, asset_name = item['id'], item['areaId'], item['assetbundleName']

        is_vs_item = False

        area_item_icons[item_id] = await ctx.rip.img(f"areaitem/{asset_name}/{asset_name}.png")
        for item_lv in await ctx.md.area_item_levels.find_by('areaItemId', item_id, mode='all'):
            area_item_level_bonuses.setdefault(item_id, {})[item_lv['level']] = item_lv['power1BonusRate']
            area_item_max_levels[item_id] = max(area_item_max_levels.get(item_id, 0), item_lv['level'])

            if item_id not in area_item_target_icons:
                if item_lv.get('targetUnit', 'any') != 'any':
                    area_item_target_icons[item_id] = get_unit_icon(item_lv['targetUnit'])
                    if item_lv['targetUnit'] == 'piapro':
                        if filter_piapro:
                            item_ids.add(item_id)
                        is_vs_item = True
                elif item_lv.get('targetGameCharacterId', 'any') != 'any':
                    area_item_target_icons[item_id] = get_chara_icon_by_chara_id(item_lv['targetGameCharacterId'])
                    if filter.cid and item_lv['targetGameCharacterId'] == filter.cid:
                        item_ids.add(item_id)
                    if item_lv['targetGameCharacterId'] in UNIT_CID_MAP['piapro']:
                        is_vs_item = True
                elif item_lv.get('targetCardAttr', 'any') != 'any':
                    area_item_target_icons[item_id] = get_attr_icon(item_lv['targetCardAttr'])
                    if filter.attr and item_lv['targetCardAttr'] == filter.attr:
                        item_ids.add(item_id)

        if filter.flower and area_id == FLOWER_AREA_ID:
            item_ids.add(item_id)
        if filter.tree and area_id == TREE_AREA_ID:
            item_ids.add(item_id)
        if filter.unit and area_id == UNIT_SEKAI_AREA_IDS[filter.unit] and not is_vs_item:
            item_ids.add(item_id)

    item_ids = sorted(item_ids)

    # 统计展示的最低等级
    user_area_item_lower_lv = None
    for item_id in item_ids:
        lv = user_area_item_lvs.get(item_id, 0)
        if user_area_item_lower_lv is None or lv < user_area_item_lower_lv:
            user_area_item_lower_lv = lv
    if user_area_item_lower_lv is None:
        user_area_item_lower_lv = 0

    # 获取区域道具等级对应的shopItem的resboxId ids[item_id][level] = resbox_id
    area_item_lv_shop_item_resbox_ids: dict[int, dict[int, int]] = {}
    for box_id, box in (await ctx.md.resource_boxes.get())['shop_item'].items():
        if details := box.get('details'):
            detail = details[0]
            res_type = detail.get('resourceType')
            res_id = detail.get('resourceId')
            res_lv = detail.get('resourceLevel')
            if res_type == 'area_item' and res_id in item_ids:
                area_item_lv_shop_item_resbox_ids.setdefault(res_id, {})[res_lv] = box_id
                
    # 获取区域道具升级材料列表 m[item_id][level][material_id] = quantity
    area_item_lv_materials: dict[int, dict[int, dict[int, int]]] = {}
    for item_id in item_ids:
        for lv, resbox_id in area_item_lv_shop_item_resbox_ids[item_id].items():
            for cost in (await ctx.md.shop_items.find_by('resourceBoxId', resbox_id)).get('costs', []):
                cost = cost['cost']
                res_id = cost['resourceId']
                if cost['resourceType'] == 'coin':
                    res_id = COIN_ID
                quantity = cost['quantity']
                area_item_lv_materials.setdefault(item_id, {}).setdefault(lv, {})[res_id] = quantity

    # 计算从玩家当前等级到目标等级所需材料（没有提供profile则从0累计）
    area_item_lv_sum_materials: dict[int, dict[int, dict[int, dict]]] = {}
    for item_id, lv_materials in area_item_lv_materials.items():
        user_lv = user_area_item_lvs.get(item_id, 0)
        sum_materials: dict[int, int] = {}
        # 枚举等级和材料
        for lv in range(user_lv + 1, area_item_max_levels[item_id] + 1):
            for mid, quantity in lv_materials[lv].items():
                sum_materials[mid] = sum_materials.get(mid, 0) + quantity
                area_item_lv_sum_materials.setdefault(item_id, {}).setdefault(lv, {})[mid] = sum_materials[mid]

    def get_quant_text(q: int) -> str:
        if q >= 10000000:
            return f"{q//10000000}kw"
        elif q >= 10000:
            return f"{q//10000}w"
        elif q >= 1000:
            return f"{q//1000}k"
        else:
            return str(q)
    
    # 绘图
    gray_color, red_color, green_color = (50, 50, 50), (200, 0, 0), (0, 200, 0)
    ok_color = green_color if profile else gray_color
    no_color = red_color if profile else gray_color
    with Canvas(bg=SEKAI_BLUE_BG).set_padding(BG_PADDING) as canvas:
        with VSplit().set_content_align('lt').set_item_align('lt').set_sep(16):
            if profile:
                await get_detailed_profile_card(ctx, profile, pmsg)

            with HSplit().set_content_align('lt').set_item_align('lt').set_sep(16).set_bg(roundrect_bg()).set_padding(8):
                for item_id, lv_materials in area_item_lv_materials.items():
                    lv_sum_materials = area_item_lv_sum_materials.get(item_id, {})
                    current_lv = user_area_item_lvs.get(item_id, 0)
                    # 每个道具的列
                    with VSplit().set_content_align('l').set_item_align('l').set_sep(8).set_item_bg(roundrect_bg()).set_padding(8):
                        # 列头
                        with HSplit().set_content_align('c').set_item_align('c').set_omit_parent_bg(True):
                            ImageBox(area_item_target_icons.get(item_id, UNKNOWN_IMG), size=(None, 64))
                            ImageBox(area_item_icons.get(item_id, UNKNOWN_IMG), size=(128, 64), image_size_mode='fit') \
                                .set_content_align('c')
                            if current_lv:
                                TextBox(f"Lv.{current_lv}", TextStyle(font=DEFAULT_BOLD_FONT, size=24, color=gray_color))

                        lv_can_upgrade = True
                        for lv in range(user_area_item_lower_lv + 1, area_item_max_levels[item_id] + 1):
                            # 统计道具是否足够
                            if lv > current_lv:
                                material_is_enough: dict[int, bool] = {}
                                for mid, quantity in lv_sum_materials[lv].items():
                                    material_is_enough[mid] = user_materials.get(mid, 0) >= quantity
                                lv_can_upgrade = lv_can_upgrade and all(material_is_enough.values())

                            # 列项
                            with HSplit().set_content_align('l').set_item_align('l').set_sep(8).set_padding(8):
                                bonus_text = f"+{area_item_level_bonuses[item_id][lv]:.1f}%"
                                with VSplit().set_content_align('c').set_item_align('c').set_sep(4):
                                    color = ok_color if lv_can_upgrade else no_color
                                    if lv <= current_lv:
                                        color = gray_color
                                    TextBox(f"{lv}", TextStyle(font=DEFAULT_BOLD_FONT, size=24, color=color))
                                    TextBox(bonus_text, TextStyle(font=DEFAULT_BOLD_FONT, size=16, color=gray_color)).set_w(64)

                                if lv <= current_lv:
                                    with VSplit().set_content_align('c').set_item_align('c').set_sep(4):
                                        Spacer(w=64, h=64)
                                        TextBox(" ", TextStyle(font=DEFAULT_BOLD_FONT, size=15, color=gray_color))
                                else:
                                    for mid, quantity in lv_materials[lv].items():
                                        with VSplit().set_content_align('c').set_item_align('c').set_sep(4):
                                            material_icon = await get_res_icon(ctx, 'coin' if mid == COIN_ID else 'material', mid)
                                            quantity_text = get_quant_text(quantity)
                                            have_text = get_quant_text(user_materials.get(mid, 0))
                                            sum_text = get_quant_text(lv_sum_materials[lv][mid])
                                            with Frame():
                                                sz = 64
                                                ImageBox(material_icon, size=(sz, sz))
                                                TextBox(f"x{quantity_text}", TextStyle(font=DEFAULT_BOLD_FONT, size=16, color=(50, 50, 50))) \
                                                    .set_offset((sz, sz)).set_offset_anchor('rb')
                                            color = ok_color if material_is_enough.get(mid) else no_color
                                            text = f"{have_text}/{sum_text}" if profile else f"{sum_text}"
                                            TextBox(text, TextStyle(font=DEFAULT_BOLD_FONT, size=15, color=color))

    add_watermark(canvas)

    # 缓存full查询
    cache_key = None
    if profile is None:
        cache_key = f"{ctx.region}_area_item_{filter.unit}_{filter.cid}_{filter.attr}_{filter.flower}_{filter.tree}"
    return await canvas.get_img(scale=0.75, cache_key=cache_key)



# ======================= 指令处理 ======================= #

# 绑定id或查询绑定id
pjsk_bind = SekaiCmdHandler([
    "/pjsk bind", "/pjsk_bind", "/pjsk id", "/pjsk_id",
    "/绑定", "/pjsk绑定", "/pjsk 绑定"
])
pjsk_bind.check_cdrate(cd).check_wblist(gbl)
@pjsk_bind.handle()
async def _(ctx: SekaiHandlerContext):
    args = ctx.get_args().strip()
    args = ''.join([c for c in args if c.isdigit()])
    
    # 查询
    if not args:
        uids: List[str] = []
        for region in ALL_SERVER_REGIONS:
            region_ctx = SekaiHandlerContext.from_region(region)
            uid = get_player_bind_id(region_ctx, ctx.user_id, check_bind=False)
            if uid:
                if is_user_hide_id(region, ctx.user_id):
                    uid = "*" * 14 + uid[-6:]
                uids.append(f"[{region.upper()}] {uid}")
        if not uids:
            return await ctx.asend_reply_msg("你还没有绑定过游戏ID，请使用\"/绑定 游戏ID\"进行绑定")
        return await ctx.asend_reply_msg(f"已经绑定的游戏ID:\n" + "\n".join(uids))

    # 检查是否在黑名单中
    assert_and_reply(not check_uid_in_blacklist(args), f"该游戏ID({args})已被拉入黑名单，无法绑定")
    
    # 检查有效的服务器
    checked_regions = []
    async def check_bind(region: str) -> Optional[Tuple[str, str, str]]:
        try:
            region_ctx = SekaiHandlerContext.from_region(region)
            if not get_gameapi_config(region_ctx).profile_api_url:
                return None
            # 检查格式
            if not validate_uid(region_ctx, args):
                return region, None, f"ID格式错误"
            checked_regions.append(get_region_name(region))
            profile = await get_basic_profile(region_ctx, args, use_cache=False, use_remote_cache=False, raise_when_no_found=False)
            if not profile:
                return region, None, "找不到该ID的玩家"
            user_name = profile['user']['name']
            return region, user_name, None
        except Exception as e:
            logger.warning(f"在 {region} 服务器尝试绑定失败: {get_exc_desc(e)}")
            return region, None, "内部错误，请稍后重试"
        
    check_results = await asyncio.gather(*[check_bind(region) for region in ALL_SERVER_REGIONS])
    check_results = [res for res in check_results if res]
    ok_check_results = [res for res in check_results if res[2] is None]

    if not ok_check_results:
        reply_text = f"所有支持的服务器尝试绑定失败，请检查ID是否正确"
        for region, _, err_msg in check_results:
            if err_msg:
                reply_text += f"\n{get_region_name(region)}: {err_msg}"
        return await ctx.asend_reply_msg(reply_text)
    
    if len(ok_check_results) > 1:
        await ctx.asend_reply_msg(f"该ID在多个服务器都存在！默认绑定找到的第一个服务器")
    region, user_name, _ = ok_check_results[0]
    uid = str(ctx.user_id)

    bind_list: Dict[str, Dict[str, setattr]] = profile_db.get("bind_list", {})
    last_bind_id = bind_list.get(region, {}).get(uid, None)

    # 检查绑定次数限制
    if not check_superuser(ctx.event):
        date = get_date_str()
        all_daily_info = bind_history_db.get(f"{region}_daily", {})
        daily_info = all_daily_info.get(uid, { 'date': date, 'ids': [] })
        if daily_info['date'] != date:
            daily_info = { 'date': date, 'ids': [] }

        today_ids = set(daily_info.get('ids', []))
        today_ids.add(args)
        if last_bind_id:
            today_ids.add(last_bind_id) # 当前绑定的id也算在内

        daily_info['ids'] = list(today_ids)
        if len(daily_info['ids']) > DAILY_BIND_LIMIT.get():
            return await ctx.asend_reply_msg(f"你今日绑定{get_region_name(region)}帐号的数量已达上限")
        all_daily_info[uid] = daily_info
        bind_history_db.set(f"{region}_daily", all_daily_info)

    msg = f"{get_region_name(region)}绑定成功: {user_name}"

    # 如果以前没有绑定过其他区服，设置默认服务器
    other_bind = None
    for r in ALL_SERVER_REGIONS:
        if r == region: continue
        other_bind = other_bind or bind_list.get(r, {}).get(uid, None)
    default_region = get_user_default_region(ctx.user_id, None)
    if not other_bind and not default_region:
        msg += f"\n已设置你的默认服务器为{get_region_name(region)}，如需修改可使用\"/pjsk服务器\""
        set_user_default_region(ctx.user_id, region)
    if default_region and default_region != region:
        msg += f"\n你的默认服务器为{get_region_name(default_region)}，查询{get_region_name(region)}需加前缀{region}，或使用\"/pjsk服务器\"修改默认服务器"

    # 如果该区服以前没有绑定过，设置默认隐藏id
    if not last_bind_id:
        lst = profile_db.get("hide_id_list", {})
        if region not in lst:
            lst[region] = []
        if ctx.user_id not in lst[ctx.region]:
            lst[region].append(ctx.user_id)
        profile_db.set("hide_id_list", lst)

    # 进行绑定
    if region not in bind_list:
        bind_list[region] = {}
    bind_list[region][uid] = args
    profile_db.set("bind_list", bind_list)

    # 保存绑定历史
    if last_bind_id != args:
        bind_history = bind_history_db.get("history", {})
        if uid not in bind_history:
            bind_history[uid] = []
        bind_history[uid].append({
            "time": int(time.time() * 1000),
            "region": region,
            "uid": args,
        })
        bind_history_db.set("history", bind_history)
    
    return await ctx.asend_reply_msg(msg)


# 隐藏抓包信息
pjsk_hide_suite = SekaiCmdHandler([
    "/pjsk hide suite", "/pjsk_hide_suite", 
    "/pjsk隐藏抓包", "/隐藏抓包",
])
pjsk_hide_suite.check_cdrate(cd).check_wblist(gbl)
@pjsk_hide_suite.handle()
async def _(ctx: SekaiHandlerContext):
    lst = profile_db.get("hide_suite_list", {})
    if ctx.region not in lst:
        lst[ctx.region] = []
    if ctx.user_id not in lst[ctx.region]:
        lst[ctx.region].append(ctx.user_id)
    profile_db.set("hide_suite_list", lst)
    return await ctx.asend_reply_msg(f"已隐藏{get_region_name(ctx.region)}抓包信息")
    

# 展示抓包信息
pjsk_show_suite = SekaiCmdHandler([
    "/pjsk show suite", "/pjsk_show_suite",
    "/pjsk显示抓包", "/pjsk展示抓包", "/展示抓包",
])
pjsk_show_suite.check_cdrate(cd).check_wblist(gbl)
@pjsk_show_suite.handle()
async def _(ctx: SekaiHandlerContext):
    lst = profile_db.get("hide_suite_list", {})
    if ctx.region not in lst:
        lst[ctx.region] = []
    if ctx.user_id in lst[ctx.region]:
        lst[ctx.region].remove(ctx.user_id)
    profile_db.set("hide_suite_list", lst)
    return await ctx.asend_reply_msg(f"已展示{get_region_name(ctx.region)}抓包信息")


# 隐藏id信息
pjsk_hide_id = SekaiCmdHandler([
    "/pjsk hide id", "/pjsk_hide_id",
    "/pjsk隐藏id", "/pjsk隐藏ID", "/隐藏id", "/隐藏ID",
])
pjsk_hide_id.check_cdrate(cd).check_wblist(gbl)
@pjsk_hide_id.handle()
async def _(ctx: SekaiHandlerContext):
    lst = profile_db.get("hide_id_list", {})
    if ctx.region not in lst:
        lst[ctx.region] = []
    if ctx.user_id not in lst[ctx.region]:
        lst[ctx.region].append(ctx.user_id)
    profile_db.set("hide_id_list", lst)
    return await ctx.asend_reply_msg(f"已隐藏{get_region_name(ctx.region)}ID信息")


# 展示id信息
pjsk_show_id = SekaiCmdHandler([
    "/pjsk show id", "/pjsk_show_id",
    "/pjsk显示id", "/pjsk显示ID", "/pjsk展示id", "/pjsk展示ID",
    "/展示id", "/展示ID", "/显示id", "/显示ID",
])
pjsk_show_id.check_cdrate(cd).check_wblist(gbl)
@pjsk_show_id.handle()
async def _(ctx: SekaiHandlerContext):
    lst = profile_db.get("hide_id_list", {})
    if ctx.region not in lst:
        lst[ctx.region] = []
    if ctx.user_id in lst[ctx.region]:
        lst[ctx.region].remove(ctx.user_id)
    profile_db.set("hide_id_list", lst)
    return await ctx.asend_reply_msg(f"已展示{get_region_name(ctx.region)}ID信息")


# 查询个人名片
pjsk_info = SekaiCmdHandler([
    "/pjsk profile", "/pjsk_profile", "/pjskprofile", 
    "/个人信息", "/名片", "/pjsk个人信息", "/pjsk名片", "/pjsk 个人信息", "/pjsk 名片",
])
pjsk_info.check_cdrate(cd).check_wblist(gbl)
@pjsk_info.handle()
async def _(ctx: SekaiHandlerContext):
    args = ctx.get_args().strip()
    vertical = None
    try:
        if '横屏' in args:
            vertical = False
            args = args.replace('横屏', '').strip()
        elif '竖屏' in args:
            vertical = True
            args = args.replace('竖屏', '').strip()
        uid = int(args)
    except:
        uid = get_player_bind_id(ctx, ctx.user_id)
    profile = await get_basic_profile(ctx, uid, use_cache=True, use_remote_cache=False)
    logger.info(f"绘制名片 region={ctx.region} uid={uid}")
    return await ctx.asend_reply_msg(await get_image_cq(
        await compose_profile_image(ctx, profile, vertical=vertical),
        low_quality=True, quality=95,
    ))


# 查询注册时间
pjsk_reg_time = SekaiCmdHandler([
    "/pjsk reg time", "/pjsk_reg_time", 
    "/注册时间", "/pjsk注册时间", "/pjsk 注册时间", "/查时间",
])
pjsk_reg_time.check_cdrate(cd).check_wblist(gbl)
@pjsk_reg_time.handle()
async def _(ctx: SekaiHandlerContext):
    uid = get_player_bind_id(ctx, ctx.user_id)
    reg_time = get_register_time(ctx.region, uid)
    elapsed = datetime.now() - reg_time
    region_name = get_region_name(ctx.region)
    return await ctx.asend_reply_msg(f"{region_name}注册时间: {reg_time.strftime('%Y-%m-%d %H:%M:%S')} ({elapsed.days}天前)")


# 检查profile服务器状态
pjsk_check_service = SekaiCmdHandler([
    "/pjsk check service", "/pjsk_check_service", "/pcs",
    "/pjsk检查", "/pjsk检查服务", "/pjsk检查服务状态", "/pjsk状态",
])
pjsk_check_service.check_cdrate(cd).check_wblist(gbl)
@pjsk_check_service.handle()
async def _(ctx: SekaiHandlerContext):
    url = get_gameapi_config(ctx).api_status_url
    assert_and_reply(url, f"暂无 {ctx.region} 的查询服务器")
    try:
        data = await request_gameapi(url)
        assert data['status'] == 'ok'
    except Exception as e:
        logger.print_exc(f"profile查询服务状态异常")
        return await ctx.asend_reply_msg(f"profile查询服务异常: {str(e)}")
    return await ctx.asend_reply_msg("profile查询服务正常")


# 设置抓包数据获取模式
pjsk_data_mode = SekaiCmdHandler([
    "/pjsk data mode", "/pjsk_data_mode",
    "/pjsk抓包模式", "/pjsk抓包获取模式", "/抓包模式",
])
pjsk_data_mode.check_cdrate(cd).check_wblist(gbl)
@pjsk_data_mode.handle()
async def _(ctx: SekaiHandlerContext):
    data_modes = profile_db.get("data_modes", {})
    cur_mode = data_modes.get(ctx.region, {}).get(str(ctx.user_id), DEFAULT_DATA_MODE)
    help_text = f"""
你的{get_region_name(ctx.region)}抓包数据获取模式: {cur_mode} 
---
使用\"{ctx.original_trigger_cmd} 模式名\"来切换模式，可用模式名如下:
【latest】
同时从所有数据源获取，使用最新的一个（推荐）
【default】
从本地数据获取失败才尝试从Haruki工具箱获取
【local】
仅从本地数据获取
【haruki】
仅从Haruki工具箱获取
""".strip()
    
    ats = extract_at_qq(await ctx.aget_msg())
    if ats and ats[0] != int(ctx.bot.self_id):
        # 如果有at则使用at的qid
        qid = ats[0]
        assert_and_reply(check_superuser(ctx.event), "只有超级管理能修改别人的模式")
    else:
        qid = ctx.user_id
    
    args = ctx.get_args().strip().lower()
    assert_and_reply(args in ["default", "latest", "local", "haruki"], help_text)

    if ctx.region not in data_modes:
        data_modes[ctx.region] = {}
    data_modes[ctx.region][str(qid)] = args
    profile_db.set("data_modes", data_modes)

    if qid == ctx.user_id:
        return await ctx.asend_reply_msg(f"切换{get_region_name(ctx.region)}抓包数据获取模式:\n{cur_mode} -> {args}")
    else:
        return await ctx.asend_reply_msg(f"切换 {qid} 的{get_region_name(ctx.region)}抓包数据获取模式:\n{cur_mode} -> {args}")


# 查询抓包数据
pjsk_check_data = SekaiCmdHandler([
    "/pjsk check data", "/pjsk_check_data",
    "/pjsk抓包", "/pjsk抓包状态", "/pjsk抓包数据", "/pjsk抓包查询", "/抓包数据", "/抓包状态",
])
pjsk_check_data.check_cdrate(cd).check_wblist(gbl)
@pjsk_check_data.handle()
async def _(ctx: SekaiHandlerContext):
    cqs = extract_cq_code(await ctx.aget_msg())
    qid = int(cqs['at'][0]['qq']) if 'at' in cqs else ctx.user_id
    uid = get_player_bind_id(ctx, qid, check_bind=True)
    ''' # DEBUG
    task1 = get_detailed_profile(ctx, qid, raise_exc=False, mode="local", filter=['upload_time'])
    task2 = get_detailed_profile(ctx, qid, raise_exc=False, mode="haruki", filter=['upload_time'])
    (local_profile, local_err), (haruki_profile, haruki_err) = await asyncio.gather(task1, task2)

    msg = f"{process_hide_uid(ctx, uid, keep=6)}({ctx.region.upper()}) Suite数据\n"

    if local_err:
        local_err = local_err[local_err.find(']')+1:].strip()
        msg += f"[本地数据]\n获取失败: {local_err}\n"
    else:
        msg += "[本地数据]\n"
        upload_time = datetime.fromtimestamp(local_profile['upload_time'] / 1000)
        upload_time_text = upload_time.strftime('%m-%d %H:%M:%S') + f"({get_readable_datetime(upload_time, show_original_time=False)})"
        if local_source := local_profile.get('local_source'):
            upload_time_text = local_source + " " + upload_time_text
        msg += f"{upload_time_text}\n"

    if haruki_err:
        haruki_err = haruki_err[haruki_err.find(']')+1:].strip()
        msg += f"[Haruki工具箱]\n获取失败: {haruki_err}\n"
    else:
        msg += "[Haruki工具箱]\n"
        upload_time = datetime.fromtimestamp(haruki_profile['upload_time'] / 1000)
        # upload_time = datetime.fromtimestamp(haruki_profile['upload_time'] )
        upload_time_text = upload_time.strftime('%m-%d %H:%M:%S') + f"({get_readable_datetime(upload_time, show_original_time=False)})"
        msg += f"{upload_time_text}\n"
'''
    (haruki_profile, haruki_err) = await get_detailed_profile(ctx, qid, raise_exc=False, mode="haruki", filter=['upload_time'])
    
    msg = f"{process_hide_uid(ctx, uid, keep=6)}({ctx.region.upper()}) Suite数据\n"
    
    if haruki_err:
        haruki_err = haruki_err[haruki_err.find(']')+1:].strip()
        msg += f"[Haruki工具箱]\n获取失败: {haruki_err}\n"
    else:
        msg += "[Haruki工具箱]\n"
        upload_time = datetime.fromtimestamp(haruki_profile if isinstance(haruki_profile, int) else haruki_profile['upload_time'])
        # upload_time = datetime.fromtimestamp(haruki_profile['upload_time'] )
        upload_time_text = upload_time.strftime('%m-%d %H:%M:%S') + f"({get_readable_datetime(upload_time, show_original_time=False)})"
        msg += f"{upload_time_text}\n"
    mode = get_user_data_mode(ctx, ctx.user_id)
    msg += f"---\n"
    msg += f"该指令查询Suite数据，查询Mysekai数据请使用\"/{ctx.region}msd\"\n"
    # msg += f"数据获取模式: {mode}，使用\"/{ctx.region}抓包模式\"来切换模式\n"
    msg += f"发送\"/抓包\"获取抓包教程"

    return await ctx.asend_reply_msg(msg)


# 添加游戏id到黑名单
pjsk_blacklist = CmdHandler([
    "/pjsk blacklist add", "/pjsk_blacklist_add",
    "/pjsk黑名单添加", "/pjsk添加黑名单",
], logger)
pjsk_blacklist.check_cdrate(cd).check_wblist(gbl).check_superuser()
@pjsk_blacklist.handle()
async def _(ctx: HandlerContext):
    args = ctx.get_args().strip()
    assert_and_reply(args, "请提供要添加的游戏ID")
    blacklist = profile_db.get("blacklist", [])
    if args in blacklist:
        return await ctx.asend_reply_msg(f"ID {args} 已在黑名单中")
    blacklist.append(args)
    profile_db.set("blacklist", blacklist)
    return await ctx.asend_reply_msg(f"ID {args} 已添加到黑名单中")


# 移除游戏id到黑名单
pjsk_blacklist_remove = CmdHandler([
    "/pjsk blacklist remove", "/pjsk_blacklist_remove", "/pjsk_blacklist_del",
    "/pjsk黑名单移除", "/pjsk移除黑名单", "/pjsk删除黑名单",
], logger)
pjsk_blacklist_remove.check_cdrate(cd).check_wblist(gbl).check_superuser()
@pjsk_blacklist_remove.handle()
async def _(ctx: HandlerContext):
    args = ctx.get_args().strip()
    assert_and_reply(args, "请提供要移除的游戏ID")
    blacklist = profile_db.get("blacklist", [])
    if args not in blacklist:
        return await ctx.asend_reply_msg(f"ID {args} 不在黑名单中")
    blacklist.remove(args)
    profile_db.set("blacklist", blacklist)
    return await ctx.asend_reply_msg(f"ID {args} 已从黑名单中移除")


# 挑战信息
pjsk_challenge_info = SekaiCmdHandler([
    "/pjsk challenge info", "/pjsk_challenge_info",
    "/挑战信息", "/挑战详情", "/挑战进度", "/挑战一览",
])
pjsk_challenge_info.check_cdrate(cd).check_wblist(gbl)
@pjsk_challenge_info.handle()
async def _(ctx: SekaiHandlerContext):
    return await ctx.asend_reply_msg(await get_image_cq(
        await compose_challenge_live_detail_image(ctx, ctx.user_id),
        low_quality=True,
    ))


# 加成信息
pjsk_power_bonus_info = SekaiCmdHandler([
    "/pjsk power bonus info", "/pjsk_power_bonus_info",
    "/加成信息", "/加成详情", "/加成进度", "/加成一览",
])
pjsk_power_bonus_info.check_cdrate(cd).check_wblist(gbl)
@pjsk_power_bonus_info.handle()
async def _(ctx: SekaiHandlerContext):
    return await ctx.asend_reply_msg(await get_image_cq(
        await compose_power_bonus_detail_image(ctx, ctx.user_id),
        low_quality=True,
    ))


# 验证用户游戏帐号
verify_game_account = SekaiCmdHandler([
    "/pjsk verify", "/pjsk验证",
])
verify_game_account.check_cdrate(cd).check_wblist(gbl).check_cdrate(verify_rate_limit)
@verify_game_account.handle()
async def _(ctx: SekaiHandlerContext):
    await ctx.block_region(key=str(ctx.user_id))
    await verify_user_game_account(ctx)


# 查询用户验证过的游戏ID列表
get_verified_uids = SekaiCmdHandler([
    "/pjsk verify list", "/pjsk验证列表", "/pjsk验证状态", 
])
get_verified_uids.check_cdrate(cd).check_wblist(gbl)
@get_verified_uids.handle()
async def _(ctx: SekaiHandlerContext):
    uids = get_user_verified_uids(ctx)
    msg = ""
    region_name = get_region_name(ctx.region)
    if not uids:
        msg += f"你还没有验证过任何{region_name}游戏ID\n"
    else:
        msg += f"你验证过的{region_name}游戏ID:\n"
        for uid in uids:
            msg += process_hide_uid(ctx, uid, keep=6) + "\n"
    msg += f"---\n"
    msg += f"使用\"/{ctx.region}pjsk验证\"进行验证"
    return await ctx.asend_reply_msg(msg)


# 上传个人信息背景图片
upload_profile_bg = SekaiCmdHandler([
    "/pjsk upload profile bg", "/pjsk upload profile background",
    "/上传个人信息背景", "/上传个人信息图片", 
])
upload_profile_bg.check_cdrate(cd).check_wblist(gbl).check_cdrate(profile_bg_upload_rate_limit)
@upload_profile_bg.handle()
async def _(ctx: SekaiHandlerContext):
    await ctx.block_region(key=str(ctx.user_id))

    args = ctx.get_args().strip()
    force = False
    if 'force' in args and check_superuser(ctx.event):
        force = True
        args = args.replace('force', '').strip()

    uid = get_uid_and_check_verified(ctx, force)
    img_url = await ctx.aget_image_urls(return_first=True)
    res = await image_safety_check(img_url)
    if res.suggest_block():
        raise ReplyException(f"图片审核结果: {res.message}")
    img = await download_image(img_url)
    set_profile_bg_settings(ctx, image=img, force=force)

    msg = f"背景设置成功，使用\"/{ctx.region}调整个人信息\"可以调整界面方向、模糊、透明度\n"
    if res.suggest_review():
        msg += f"图片审核结果: {res.message}"
        logger.warning(f"用户 {ctx.user_id} 上传的个人信息背景图片需要人工审核: {res.message}")
        review_log_path = f"{SEKAI_PROFILE_DIR}/profile_bg_review.log"
        with open(review_log_path, 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now().isoformat()} {ctx.user_id} set {ctx.region} {uid}\n")

    try:
        img_cq = await get_image_cq(
            await compose_profile_image(ctx, await get_basic_profile(ctx, uid)),
            low_quality=True,
        )
        msg = img_cq + msg.strip()
    except Exception as e:
        logger.print_exc(f"绘制个人信息背景图片失败: {get_exc_desc(e)}")
        msg += f"绘制个人信息背景图片失败: {get_exc_desc(e)}"

    return await ctx.asend_reply_msg(msg)


# 清空个人信息背景图片
clear_profile_bg = SekaiCmdHandler([
    "/pjsk clear profile bg", "/pjsk clear profile background",
    "/清空个人信息背景", "/清除个人信息背景",  "/清空个人信息图片", "/清除个人信息图片", 
])
clear_profile_bg.check_cdrate(cd).check_wblist(gbl)
@clear_profile_bg.handle()
async def _(ctx: SekaiHandlerContext):
    await ctx.block_region(key=str(ctx.user_id))

    args = ctx.get_args().strip()
    force = False
    if 'force' in args and check_superuser(ctx.event):
        force = True
        args = args.replace('force', '').strip()

    set_profile_bg_settings(ctx, remove_image=True, force=force)
    return await ctx.asend_reply_msg(f"已清空{get_region_name(ctx.region)}个人信息背景图片")


# 调整个人信息背景设置
adjust_profile_bg = SekaiCmdHandler([
    "/pjsk adjust profile", "/pjsk adjust profile bg", "/pjsk adjust profile background",
    "/调整个人信息背景", "/调整个人信息", "/设置个人信息", "/设置个人信息背景",
])
adjust_profile_bg.check_cdrate(cd).check_wblist(gbl)
@adjust_profile_bg.handle()
async def _(ctx: SekaiHandlerContext):
    await ctx.block_region(key=str(ctx.user_id))

    args = ctx.get_args().strip()
    force = False
    if 'force' in args and check_superuser(ctx.event):
        force = True
        args = args.replace('force', '').strip()

    uid = get_uid_and_check_verified(ctx, force)
    HELP = f"""
调整横屏/竖屏:
{ctx.original_trigger_cmd} 竖屏
调整界面模糊度(0为无模糊):
{ctx.original_trigger_cmd} 模糊 0~10
调整界面透明度(0为不透明):
{ctx.original_trigger_cmd} 透明 0~100
""".strip()
    
    args = ctx.get_args().strip()
    if not args:
        settings = get_profile_bg_settings(ctx)
        msg = f"当前{get_region_name(ctx.region)}个人信息背景设置:\n"
        msg += f"ID: {process_hide_uid(ctx, uid, keep=6)}\n"
        msg += f"方向: {'竖屏' if settings.vertical else '横屏'}\n"
        msg += f"模糊度: {settings.blur}\n"
        msg += f"透明度: {100 - int(settings.alpha * 100 // 255)}\n"
        msg += f"---\n"
        msg += HELP
        return await ctx.asend_reply_msg(msg.strip())

    vertical, blur, alpha = None, None, None
    try:
        args = args.replace('度', '').replace('%', '')
        if '竖屏' in args:
            vertical = True
        elif '横屏' in args:
            vertical = False
        elif '模糊' in args:
            blur = int(args.replace('模糊', ''))
        elif '透明' in args:
            alpha = (100 - int(args.replace('透明', ''))) * 255 // 100
        else:
            raise Exception()
    except:
        raise ReplyException(HELP)
    
    if blur is not None:
        assert_and_reply(0 <= blur <= 10, "模糊度必须在0到10之间")
    if alpha is not None:
        assert_and_reply(0 <= alpha <= 255, "透明度必须在0到100之间")
    
    set_profile_bg_settings(ctx, vertical=vertical, blur=blur, alpha=alpha, force=force)
    settings = get_profile_bg_settings(ctx)

    msg = f"当前设置: {'竖屏' if settings.vertical else '横屏'} 透明度{100 - int(settings.alpha * 100 / 255)} 模糊度{settings.blur}\n"

    try:
        img_cq = await get_image_cq(
            await compose_profile_image(ctx, await get_basic_profile(ctx, uid)),
            low_quality=True,
        )
        msg = img_cq + msg.strip()
    except Exception as e:
        logger.print_exc(f"绘制个人信息背景图片失败: {get_exc_desc(e)}")
        msg += f"绘制个人信息背景图片失败: {get_exc_desc(e)}"
    return await ctx.asend_reply_msg(msg.strip())


# 查询用户统计
pjsk_user_sta = CmdHandler([
    "/pjsk user sta", "/用户统计",
], logger)
pjsk_user_sta.check_cdrate(cd).check_wblist(gbl).check_superuser()
@pjsk_user_sta.handle()
async def _(ctx: HandlerContext):
    args = ctx.get_args().strip()
    group_mode = False
    detail_mode = False
    if '群' in args or 'group' in args:
        group_mode = True
    if '详细' in args or 'detail' in args:
        detail_mode = True
    SUITE_DIR = "/root/program/qqbot/mybot/data/sekai/user_data/{region}/suite/*"
    MYSEKAI_DIR = "/root/program/qqbot/mybot/data/sekai/user_data/{region}/mysekai/*"
    bind_list: Dict[str, Dict[str, str]] = profile_db.get("bind_list", {})
    suite_total, mysekai_total, qid_set = 0, 0, set()
    suite_source_total: dict[str, int] = {}
    mysekai_source_total: dict[str, int] = {}

    msg = "所有群聊统计:\n" if not group_mode else "当前群聊统计:\n"
    group_qids = set([str(m['user_id']) for m in await get_group_users(ctx.bot, ctx.group_id)])

    for region in ALL_SERVER_REGIONS:
        qids = set(bind_list.get(region, {}).keys())
        if group_mode:
            qids = qids.intersection(group_qids)
            uids = set([bind_list.get(region, {}).get(qid) for qid in qids])
        qid_set.update(qids)

        suites = glob.glob(SUITE_DIR.format(region=region))
        if group_mode:
            suites = [s for s in suites if s.split('/')[-1].split('.')[0] in uids]
        suite_total += len(suites)

        mysekais = glob.glob(MYSEKAI_DIR.format(region=region))
        if group_mode:
            mysekais = [m for m in mysekais if m.split('/')[-1].split('.')[0] in uids]
        mysekai_total += len(mysekais)

        msg += f"【{get_region_name(region)}】\n绑定 {len(qids)} | Suite {len(suites)} | MySekai {len(mysekais)}\n"

        if detail_mode:
            suite_source_num: dict[str, int] = {}
            mysekai_source_num: dict[str, int] = {}
            def get_detail():
                for p in suites:
                    local_source = load_json_zstd(p).get('local_source', '未知')
                    suite_source_num[local_source] = suite_source_num.get(local_source, 0) + 1
                for k, v in suite_source_num.items():
                    suite_source_total[k] = suite_source_total.get(k, 0) + v
                for p in mysekais:
                    local_source = load_json_zstd(p).get('local_source', '未知')
                    mysekai_source_num[local_source] = mysekai_source_num.get(local_source, 0) + 1
                for k, v in mysekai_source_num.items():
                    mysekai_source_total[k] = mysekai_source_total.get(k, 0) + v
            await run_in_pool(get_detail)
            msg += "Suite来源: " + " | ".join([f"{k} {v}" for k, v in suite_source_num.items()]) + "\n"
            msg += "MySekai来源: " + " | ".join([f"{k} {v}" for k, v in mysekai_source_num.items()]) + "\n"


    msg += f"---\n【总计】\n绑定 {len(qid_set)} | Suite {suite_total} | MySekai {mysekai_total}"
    if detail_mode:
        msg += "\nSuite来源: " + " | ".join([f"{k} {v}" for k, v in suite_source_total.items()])
        msg += "\nMySekai来源: " + " | ".join([f"{k} {v}" for k, v in mysekai_source_total.items()])

    return await ctx.asend_fold_msg_adaptive(msg.strip())


# 查询绑定历史
pjsk_bind_history = CmdHandler([
    "/pjsk bind history", "/pjsk bind his", "/绑定历史", "/绑定记录",
], logger, priority=200)
pjsk_bind_history.check_cdrate(cd).check_wblist(gbl).check_superuser()
@pjsk_bind_history.handle()
async def _(ctx: HandlerContext):
    args = ctx.get_args().strip()
    uid = None
    for region in ALL_SERVER_REGIONS:
        if validate_uid(SekaiHandlerContext.from_region(region), args):
            uid = args
            break

    if not uid:
        if ats := await ctx.aget_at_qids():
            qid = str(ats[0])
        else:
            qid = args

    bind_history = bind_history_db.get("history", {})
    if uid:
        # 游戏ID查QQ号
        msg = f"绑定过{uid}的QQ用户:\n"
        for qid, items in bind_history.items():
            for item in items:
                if item['uid'] == uid:
                    time = datetime.fromtimestamp(item['time'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
                    msg += f"[{time}] {qid}"
    else:
        # QQ号查游戏ID
        msg = f"用户{qid}的绑定历史:\n"
        items = bind_history.get(qid, [])
        for item in items:
            time = datetime.fromtimestamp(item['time'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
            msg += f"[{time}]\n{item['region']} {item['uid']}\n"

    return await ctx.asend_fold_msg_adaptive(msg.strip())


# 查询区域道具升级材料
pjsk_area_item = SekaiCmdHandler([
    "/pjsk area item", "/area item",
    "/区域道具", "/区域道具升级", "/区域道具升级材料",
])
pjsk_area_item.check_cdrate(cd).check_wblist(gbl)
@pjsk_area_item.handle()
async def _(ctx: SekaiHandlerContext):
    args = ctx.get_args().strip()

    HELP_TEXT = f"""
可用参数: 团名/角色名/属性/树/花
加上"all"可以查询所有级别材料，不加则查询你的账号的升级情况，示例：
"{ctx.original_trigger_cmd} 树" 所有树
"{ctx.original_trigger_cmd} miku" miku的道具
"{ctx.original_trigger_cmd} 25h" 25的SEKAI里的所有区域道具
"{ctx.original_trigger_cmd} miku all" miku的道具所有等级
""".strip()

    qid = ctx.user_id
    for keyword in ('all', 'full'):
        if keyword in args:
            qid = None
            args = args.replace(keyword, '').strip()
            break

    tree = False
    for keyword in ('树',):
        if keyword in args:
            tree = True
            args = args.replace(keyword, '').strip()
            break
    flower = False
    for keyword in ('花',):
        if keyword in args:
            flower = True
            args = args.replace(keyword, '').strip()
            break
    unit, args = extract_unit(args)
    attr, args = extract_card_attr(args)
    cid = get_cid_by_nickname(args)

    assert_and_reply(unit or attr or cid or tree or flower, HELP_TEXT)

    filter = AreaItemFilter(
        unit=unit,
        attr=attr,
        cid=cid,
        tree=tree,
        flower=flower,
    )
    return await ctx.asend_reply_msg(await get_image_cq(
        await compose_area_item_upgrade_materials_image(ctx, qid, filter),
        low_quality=True,
    ))


# 创建游客账号
pjsk_create_guest_account = SekaiCmdHandler([
    "/pjsk create guest", "/pjsk register", "/pjsk注册",
], regions=['jp', 'en'])
guest_account_create_rate_limit = RateLimit(file_db, logger, 2, 'd', rate_limit_name='注册游客账号')
pjsk_create_guest_account.check_cdrate(cd).check_wblist(gbl).check_cdrate(guest_account_create_rate_limit)
@pjsk_create_guest_account.handle()
async def _(ctx: SekaiHandlerContext):
    region_name = get_region_name(ctx.region)
    url = get_gameapi_config(ctx).create_account_api_url
    assert_and_reply(url, f"不支持注册{region_name}帐号")
    data = await request_gameapi(url, method="POST")
    return await ctx.asend_fold_msg([
        f"注册{region_name}帐号成功，引继码和引继密码如下，登陆后请及时重新生成引继码",
        data['inherit_id'],
        data['inherit_pw'],
    ])
