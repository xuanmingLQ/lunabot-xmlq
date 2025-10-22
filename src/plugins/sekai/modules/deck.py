from ...utils import *
from ..common import *
from ..handler import *
from ..asset import *
from ..draw import *
from .event import get_event_banner_img, get_current_event
from .sk import get_wl_events
from .profile import (
    get_player_bind_id,
    get_basic_profile,
    get_detailed_profile, 
    get_detailed_profile_card, 
    get_card_full_thumbnail,
    get_user_challenge_live_info,
)
from .card import get_unit_by_card_id, has_after_training
from .music import DIFF_NAMES, search_music, MusicSearchOptions, extract_diff, is_valid_music
from .mysekai import MYSEKAI_REGIONS
from sekai_deck_recommend import (
    DeckRecommendOptions, 
    DeckRecommendCardConfig, 
    DeckRecommendSingleCardConfig,
    DeckRecommendResult,
    DeckRecommendSaOptions,
    RecommendDeck,
)


RECOMMEND_TIMEOUT_CFG = config.item('deck.timeout.default')
NO_EVENT_RECOMMEND_TIMEOUT_CFG = config.item('deck.timeout.no_event')
SINGLE_ALG_RECOMMEND_TIMEOUT_CFG = config.item('deck.timeout.single_alg')
BONUS_RECOMMEND_TIMEOUT_CFG = config.item('deck.timeout.bonus_target')
RECOMMEND_ALGS_CFG = config.item('deck.default_algs')
RECOMMEND_ALG_NAMES = {
    'dfs': '暴力搜索',
    'sa': '模拟退火',
    'ga': '遗传算法',
}

musicmetas_json = WebJsonRes(
    name="MusicMeta", 
    url="https://sekai-data.3-3.dev/music_metas.json", 
    update_interval=timedelta(hours=1),
)
MUSICMETAS_SAVE_PATH = f"{SEKAI_ASSET_DIR}/music_metas.json"
DECK_RECOMMEND_MUSICMETAS_UPDATE_INTERVAL = timedelta(days=1)

OMAKASE_MUSIC_ID = 10000
OMAKASE_MUSIC_DIFFS = ["master", "expert", "hard"]

data_update_lock = asyncio.Lock()
last_deck_recommend_masterdata_version: Dict[str, str] = {}
last_deck_recommend_masterdata_update_time: Dict[str, datetime] = {} 
last_deck_recommend_musicmetas_update_time: Dict[str, datetime] = {}


# ======================= 默认配置 ======================= #

DEFAULT_DECK_RECOMMEND_MUSICDIFFS = {
    "event": {
        "multi": [
            (OMAKASE_MUSIC_ID, "master"),
        ],
        "solo": [
            (74, "expert"),
        ],
        "auto": [
            (74, "expert"),
        ],
    },
    "challenge": [
        (540, "master"),
        (104, "master"),
    ],
}

POWER_TARGET_KEYWORDS = ('综合力', '综合', '总合力', '总和', 'power')
SKILL_TARGET_KEYWORDS = ('倍率', '实效', 'skill', '时效')

SKILL_MAX_KEYWORDS = ("满技能", "满技", "skillmax", "技能满级", "slv4")
MASTER_MAX_KEYWORDS = ("满突破", "满破", "rankmax", "mastermax", "5破", "五破")
EPISODE_READ_KEYWORDS = ("剧情已读", "满剧情", "前后篇已读", "前后篇", "已读")
CANVAS_KEYWORDS = ("满画布", "全画布", "画布", "满画板", "全画板", "画板")
DISABLE_KEYWORDS = ("禁用", "disable")
TEAMMATE_POWER_KEYWORDS = ("队友综合力", "队友总合力", "队友综合", "队友总和")
TEAMMATE_SCOREUP_KEYWORDS = ("队友实效", "队友技能", "队友时效")
KEEP_AFTERTRAINING_STATE_KEYWORDS = ("bfes不变", "bf不变")

UNIT_FILTER_KEYWORDS = {
    "light_sound": ["纯ln", "仅ln"],
    "idol": ["纯mmj", "仅mmj"],
    "street": ["纯vbs", "仅vbs"],
    "theme_park": ["纯ws", "仅ws"],
    "school_refusal": ["纯25h", "纯25时", "纯25", "仅25h", "仅25时", "仅25"],
    "piapro": ["纯vs", "纯v", "仅vs", "仅v"],
}
MAX_PROFILE_KEYWORDS = ('顶配', '满配',)
CURRENT_DECK_KEYWORDS = ('当前', '目前')

DEFAULT_CARD_CONFIG_12 = DeckRecommendCardConfig()
DEFAULT_CARD_CONFIG_12.disable = False
DEFAULT_CARD_CONFIG_12.level_max = True
DEFAULT_CARD_CONFIG_12.episode_read = True
DEFAULT_CARD_CONFIG_12.master_max = True
DEFAULT_CARD_CONFIG_12.skill_max = True
DEFAULT_CARD_CONFIG_12.canvas = False

DEFAULT_CARD_CONFIG_34bd = DeckRecommendCardConfig()
DEFAULT_CARD_CONFIG_34bd.disable = False
DEFAULT_CARD_CONFIG_34bd.level_max = True
DEFAULT_CARD_CONFIG_34bd.episode_read = False
DEFAULT_CARD_CONFIG_34bd.master_max = False
DEFAULT_CARD_CONFIG_34bd.skill_max = False
DEFAULT_CARD_CONFIG_34bd.canvas = False

NOCHANGE_CARD_CONFIG = DeckRecommendCardConfig()
NOCHANGE_CARD_CONFIG.disable = False
NOCHANGE_CARD_CONFIG.level_max = False
NOCHANGE_CARD_CONFIG.episode_read = False
NOCHANGE_CARD_CONFIG.master_max = False
NOCHANGE_CARD_CONFIG.skill_max = False
NOCHANGE_CARD_CONFIG.canvas = False

DEFAULT_LIMIT = 8
BONUS_TARGET_LIMIT = 1

DEFAULT_TEAMMATE_POWER = 250000
DEFAULT_TEAMMATE_SCOREUP = 200


# ======================= 参数获取 ======================= #

# 解析 20k 20w 这类数字
def parse_number(s: str) -> Optional[int]:
    s = s.strip().lower()
    if s.endswith('k'):
        return int(float(s[:-1]) * 1000)
    elif s.endswith('w'):
        return int(float(s[:-1]) * 10000)
    else:
        return int(s)

# 从args获取组卡目标活动（如果是wl则会同时返回cid）返回 (活动, cid, 剩余参数)
async def extract_target_event(
    ctx: SekaiHandlerContext, 
    args: str,
    need_event_prefix: bool,
) -> Tuple[dict, Optional[int], str]:
    for keyword in ('终章', ):
        if keyword in args:
            args = args.replace(keyword, "event180")

    # 是否指定了活动id/章节id/角色昵称
    event_id, chapter_id, chapter_nickname = None, None, None
    for i in range(1, 10):
        if f"wl{i}" in args:
            chapter_id = i
            args = args.replace(f"wl{i}", "").strip()
            break
    event_match = re.search(r"event(\d+)" if need_event_prefix else r"(?:event)?(\d+)", args)
    if event_match:
        event_id = int(event_match.group(1))
        args = args.replace(event_match.group(0), "").strip()
    for item in get_character_nickname_data():
        for nickname in item.nicknames:
            if nickname in args:
                chapter_nickname = nickname
                args = args.replace(nickname, "").strip()
                break

    if not event_id:
        # 获取默认活动：寻找当前活动，如果没有就下一个活动
        event = await get_current_event(ctx, "next_first")
        assert_and_reply(event, """
找不到正在进行的/即将开始的活动
使用\"/组卡\"指定团队&属性组卡，或使用\"/活动组卡help\"查看如何组往期活动
""".strip())
    else:
        event = await ctx.md.events.find_by_id(event_id)
        assert_and_reply(event, f"""
活动{ctx.region}-{event_id}不存在，使用\"/组卡\"指定团队&属性组卡
""".strip())

    wl_events = await get_wl_events(ctx, event['id'])
    if wl_events:
        if not chapter_id and not chapter_nickname:
            # 获取默认章节
            if len(wl_events) == 1:
                # 只有一个章节就直接用
                chapter = wl_events[0]
            elif datetime.now() > datetime.fromtimestamp(event['aggregateAt'] / 1000):
                # 活动已经结束，默认使用最后一个章节
                wl_events.sort(key=lambda x: x['startAt'], reverse=True)
                chapter = wl_events[0]
            elif datetime.now() < datetime.fromtimestamp(event['startAt'] / 1000):
                # 活动还没开始，默认使用第一个章节
                wl_events.sort(key=lambda x: x['startAt'])
                chapter = wl_events[0]
            else:
                # 否则寻找 开始时间 <= 当前 <= 结束时间 的最晚的章节
                ok_chapters = []
                for chapter in wl_events:
                    start_time = datetime.fromtimestamp(chapter['startAt'] / 1000)
                    end_time = datetime.fromtimestamp(chapter['aggregateAt'] / 1000 + 1)
                    if start_time <= datetime.now() <= end_time:
                        ok_chapters.append(chapter)
                assert_and_reply(ok_chapters, f"请指定一个要查询的WL章节，例如\"event140 wl1\"或\"event140 miku\"")
                ok_chapters.sort(key=lambda x: x['startAt'], reverse=True)
                chapter = ok_chapters[0]
        elif chapter_id:
            chapter = find_by(wl_events, "id", 1000 * chapter_id + event['id'])
            assert_and_reply(chapter, f"活动 {ctx.region}-{event['id']} 没有章节 {chapter_id}")
        else: 
            cid = get_cid_by_nickname(chapter_nickname)
            chapter = find_by(wl_events, "wl_cid", cid)
            assert_and_reply(chapter, f"活动 {ctx.region}-{event['id']} 没有 {chapter_nickname} 的章节 ")

        wl_cid = chapter['wl_cid']

    else:
        assert_and_reply(not chapter_id, f"活动 {ctx.region}-{event['id']} 不是WL活动，无法指定章节")
        wl_cid = None

    return event, wl_cid, args

# 从args中提取组卡目标
def extract_target(args: str, options: DeckRecommendOptions) -> str:
    options.target = "score"

    for keyword in POWER_TARGET_KEYWORDS:
        if keyword in args:
            args = args.replace(keyword, "").strip()
            options.target = "power"
            break

    for keyword in SKILL_TARGET_KEYWORDS:
        if keyword in args:
            args = args.replace(keyword, "").strip()
            options.target = "skill"
            break
    
    return args.strip()
    
# 从args中提取固定卡牌
def extract_fixed_cards_and_characters(args: str, options: DeckRecommendOptions) -> str:
    if '#' in args:
        args, fixed_args = args.split('#', 1)
        fixed_cards, fixed_characters = [], []
        try:
            # 固定卡牌
            fixed_cards = list(map(int, fixed_args.strip().split()))
        except:
            try:
                # 固定角色
                for seg in fixed_args.strip().split():
                    nickname, _ = extract_nickname_from_args(seg)
                    assert nickname
                    fixed_characters.append(get_cid_by_nickname(nickname))
                assert fixed_characters
            except:
                raise ReplyException("""
格式错误，固定卡牌或固定角色参数必须放在最后，示例:
/组卡指令 其他参数 #123 456 789...
/组卡指令 其他参数 #miku rin...
""".strip())

        if fixed_cards:
            assert_and_reply(len(fixed_cards) <= 5, f"固定卡牌数量不能超过5张")
            assert_and_reply(len(set(fixed_cards)) == len(fixed_cards), "固定卡牌不能重复")
            options.fixed_cards = fixed_cards

        elif fixed_characters:
            assert_and_reply(len(fixed_characters) <= 5, f"固定角色数量不能超过5个")
            assert_and_reply(len(set(fixed_characters)) == len(fixed_characters), "固定角色不能重复")
            options.fixed_characters = fixed_characters

    return args.strip()

# 从args中提取卡牌设置
def extract_card_config(args: str, options: DeckRecommendOptions) -> str:
    def get_prefix_digit(s: str) -> Optional[int]:
        d = ""
        for c in s:
            if c.isdigit():
                d += c
            else:
                break
        return int(d) if d else None

    def has_config_keyword(s: str):
        return any(
            keyword in s for keyword 
            in DISABLE_KEYWORDS + SKILL_MAX_KEYWORDS + MASTER_MAX_KEYWORDS + EPISODE_READ_KEYWORDS + CANVAS_KEYWORDS
        )

    def apply_card_config(args: str, cfgs: List[DeckRecommendCardConfig]) -> str:
        for keyword in DISABLE_KEYWORDS:
            if keyword in args:
                for cfg in cfgs:
                    cfg.disable = True
                args = args.replace(keyword, "").strip()
                break
        for keyword in SKILL_MAX_KEYWORDS:
            if keyword in args:
                for cfg in cfgs:
                    cfg.skill_max = True
                args = args.replace(keyword, "").strip()
                break
        for keyword in MASTER_MAX_KEYWORDS:
            if keyword in args:
                for cfg in cfgs:
                    cfg.master_max = True
                args = args.replace(keyword, "").strip()
                break
        for keyword in EPISODE_READ_KEYWORDS:
            if keyword in args:
                for cfg in cfgs:
                    cfg.episode_read = True
                args = args.replace(keyword, "").strip()
                break
        for keyword in CANVAS_KEYWORDS:
            if keyword in args:
                for cfg in cfgs:
                    cfg.canvas = True
                args = args.replace(keyword, "").strip()
                break
        return args.strip()

    options.rarity_1_config = DEFAULT_CARD_CONFIG_12
    options.rarity_2_config = DEFAULT_CARD_CONFIG_12
    options.rarity_3_config = DEFAULT_CARD_CONFIG_34bd
    options.rarity_4_config = DEFAULT_CARD_CONFIG_34bd
    options.rarity_birthday_config = DEFAULT_CARD_CONFIG_34bd

    segs = args.split()

    # 稀有度单独设置
    for rarity, cfg in [
        ('一星', options.rarity_1_config),
        ('二星', options.rarity_2_config),
        ('三星', options.rarity_3_config),
        ('四星', options.rarity_4_config),
        ('生日', options.rarity_birthday_config),
    ]:
        for seg in segs:
            if seg.startswith(rarity) and has_config_keyword(seg):
                apply_card_config(seg, [cfg])
                args = args.replace(seg, "").strip()
    
    # 卡牌单独设置
    single_card_configs = []
    for seg in segs:
        card_id = get_prefix_digit(seg)
        if card_id is not None and has_config_keyword(seg):
            cfg = DeckRecommendSingleCardConfig()
            cfg.card_id = card_id
            cfg.level_max = True
            apply_card_config(seg, [cfg])
            single_card_configs.append(cfg)
            args = args.replace(seg, "").strip()
    options.single_card_configs = single_card_configs

    # 全体设置
    args = apply_card_config(args, [
        options.rarity_1_config,
        options.rarity_2_config,
        options.rarity_3_config,
        options.rarity_4_config,
        options.rarity_birthday_config,
    ])

    # bfes不变设置
    options.keep_after_training_state = False
    for keyword in KEEP_AFTERTRAINING_STATE_KEYWORDS:
        if keyword in args:
            options.keep_after_training_state = True
            args = args.replace(keyword, "").strip()
            break

    return args

# 从args中提取多人live相关设置
def extract_multilive_options(args: str, options: DeckRecommendOptions) -> str:
    if options.live_type != "multi":
        return args.strip()

    options.multi_live_teammate_power = DEFAULT_TEAMMATE_POWER
    options.multi_live_teammate_score_up = DEFAULT_TEAMMATE_SCOREUP

    segs = args.split()
    for seg in segs:
        for keyword in TEAMMATE_POWER_KEYWORDS:
            if keyword in seg:
                value = seg.replace(keyword, "").strip()
                try:
                    options.multi_live_teammate_power = parse_number(value)
                    args = args.replace(seg, "").strip()
                    break
                except:
                    raise ReplyException(f"无法解析指定的队友综合力\"{value}\"")
        for keyword in TEAMMATE_SCOREUP_KEYWORDS:
            if keyword in seg:
                value = seg.replace(keyword, "").strip()
                try:
                    options.multi_live_teammate_score_up = int(value)
                    args = args.replace(seg, "").strip()
                    break
                except:
                    raise ReplyException(f"无法解析指定的队友实效\"{value}\"")
        for keyword in SKILL_TARGET_KEYWORDS:
            if keyword in seg:
                value = seg.replace(keyword, "").strip()
                if value.isdigit():
                    options.multi_live_score_up_lower_bound = int(value)
                    args = args.replace(seg, "").strip()
                    break

    return args.strip()

# 从args中提取歌曲和难度
async def extract_music_and_diff(ctx: SekaiHandlerContext, args: str, options: DeckRecommendOptions, rec_type: str, live_type: str) -> str:
    options.music_diff, args = extract_diff(args, default=None)
    args = args.strip()

    if args:
        search_options = MusicSearchOptions(
            use_emb=False,
            use_id=False,
            use_nidx=False,
            diff=options.music_diff, 
            raise_when_err=False,
        )
        music = (await search_music(ctx, args, search_options)).music
        assert_and_reply(music, f"找不到歌曲\"{args}\"\n发送\"{ctx.trigger_cmd}help\"查看帮助")
        options.music_id = music['id']

    default_musicdiffs = DEFAULT_DECK_RECOMMEND_MUSICDIFFS[rec_type]
    if isinstance(default_musicdiffs, dict):
        default_musicdiffs = default_musicdiffs[live_type]

    for mid, diff in default_musicdiffs:
        if mid == OMAKASE_MUSIC_ID or await is_valid_music(ctx, mid, leak=False):
            if options.music_id is None:
                options.music_id = mid
            if options.music_diff is None:
                options.music_diff = diff
            break
    return args

# 从args中提取不在options中的参数
def extract_addtional_options(args: str) -> Tuple[dict, str]:
    ret = {}

    for unit, keywords in UNIT_FILTER_KEYWORDS.items():
        for keyword in keywords:
            if keyword in args:
                ret['unit_filter'] = unit
                args = args.replace(keyword, "").strip()
                break

    for names in CARD_ATTR_NAMES:
        for name in names:
            keyword = '纯' + name
            if keyword in args:
                ret['attr_filter'] = names[0]
                args = args.replace(keyword, "").strip()
                break
            keyword = '仅' + name
            if keyword in args:
                ret['attr_filter'] = names[0]
                args = args.replace(keyword, "").strip()
                break
    
    for keyword in MAX_PROFILE_KEYWORDS:
        if keyword in args:
            ret['max_profile'] = True
            args = args.replace(keyword, "").strip()
            break

    for keyword in CURRENT_DECK_KEYWORDS:
        if keyword in args:
            ret['use_current_deck'] = True
            args = args.replace(keyword, "").strip()
            break

    ret['excluded_cards'] = []
    segs = args.split()
    for seg in segs:
        if seg[0] == '-' and seg[1:].isdigit():
            try:
                x = int(seg[1:])
                if 0 < x < 5000:
                    ret['excluded_cards'].append(x)
                    args = args.replace(seg, "").strip()
            except ValueError:
                pass

    return ret, args.strip()


# 从args中提取活动组卡参数
async def extract_event_options(ctx: SekaiHandlerContext, args: str) -> Dict:
    args = ctx.get_args().strip().lower()
    options = DeckRecommendOptions()

    additional, args = extract_addtional_options(args)

    # live类型
    if "多人" in args or '协力' in args: 
        options.live_type = "multi"
        args = args.replace("多人", "").replace("协力", "").strip()
    elif "单人" in args: 
        options.live_type = "solo"
        args = args.replace("单人", "").strip()
    elif "自动" in args or "auto" in args: 
        options.live_type = "auto"
        args = args.replace("自动", "").replace("auto", "").strip()
    else:
        options.live_type = "multi"

    args = extract_multilive_options(args, options)
    args = extract_fixed_cards_and_characters(args, options)
    args = extract_card_config(args, options)
    args = extract_target(args, options)

    # 算法
    options.algorithm = "all"
    options.timeout_ms = int(RECOMMEND_TIMEOUT_CFG.get() * 1000)
    if "dfs" in args:
        options.algorithm = "dfs"
        args = args.replace("dfs", "").strip()
        options.timeout_ms = int(SINGLE_ALG_RECOMMEND_TIMEOUT_CFG.get() * 1000)

    # 活动id
    event, wl_cid, args = await extract_target_event(ctx, args, need_event_prefix=False)
    options.event_id = event['id']
    options.world_bloom_character_id = wl_cid
        
    # 歌曲id和难度
    args = await extract_music_and_diff(ctx, args, options, "event", options.live_type)

    # 组卡限制
    options.limit = DEFAULT_LIMIT

    # bfes技能计算策略
    options.skill_reference_choose_strategy = "average"

    # 模拟退火设置
    options.sa_options = DeckRecommendSaOptions()
    options.sa_options.max_no_improve_iter = 10000

    return {
        'options': options,
        'last_args': args.strip(),
        'additional': additional,
    }

# 从args中提取挑战组卡参数
async def extract_challenge_options(ctx: SekaiHandlerContext, args: str) -> Dict:
    args = ctx.get_args().strip().lower()
    options = DeckRecommendOptions()

    additional, args = extract_addtional_options(args)

    args = extract_fixed_cards_and_characters(args, options)
    args = extract_card_config(args, options)
    args = extract_target(args, options)

    options.live_type = "challenge"

    # 算法
    options.algorithm = "all"
    options.timeout_ms = int(RECOMMEND_TIMEOUT_CFG.get() * 1000)
    if "dfs" in args:
        options.algorithm = "dfs"
        args = args.replace("dfs", "").strip()
        options.timeout_ms = int(SINGLE_ALG_RECOMMEND_TIMEOUT_CFG.get() * 1000)
    
    # 指定角色
    options.challenge_live_character_id = None
    for item in get_character_nickname_data():
        for nickname in item.nicknames:
            if nickname in args:
                options.challenge_live_character_id = item.id
                args = args.replace(nickname, "").strip()
                break
    # 不指定角色情况下每个角色都组1个最强卡

    # 歌曲id和难度
    args = await extract_music_and_diff(ctx, args, options, "challenge", options.live_type)

    # 组卡限制
    options.limit = DEFAULT_LIMIT

    # bfes技能计算策略
    options.skill_reference_choose_strategy = "max"

    # 模拟退火设置
    options.sa_options = DeckRecommendSaOptions()
    if options.challenge_live_character_id is None:
        options.sa_options.run_num = 5  # 不指定角色情况下适当减少模拟退火次数

    return {
        'options': options,
        'last_args': args.strip(),
        'additional': additional,
    }

# 从args中提取长草组卡参数
async def extract_no_event_options(ctx: SekaiHandlerContext, args: str) -> Dict:
    args = ctx.get_args().strip().lower()
    options = DeckRecommendOptions()

    additional, args = extract_addtional_options(args)

    # live类型
    if "多人" in args or '协力' in args: 
        options.live_type = "multi"
        args = args.replace("多人", "").replace("协力", "").strip()
    elif "单人" in args: 
        options.live_type = "solo"
        args = args.replace("单人", "").strip()
    elif "自动" in args or "auto" in args: 
        options.live_type = "auto"
        args = args.replace("自动", "").replace("auto", "").strip()
    else:
        options.live_type = "multi"

    args = extract_multilive_options(args, options)
    args = extract_fixed_cards_and_characters(args, options)
    args = extract_card_config(args, options)
    args = extract_target(args, options)

    # 算法
    options.algorithm = "all"
    options.timeout_ms = int(NO_EVENT_RECOMMEND_TIMEOUT_CFG.get() * 1000)
    if "dfs" in args:
        options.algorithm = "dfs"
        args = args.replace("dfs", "").strip()
        options.timeout_ms = int(SINGLE_ALG_RECOMMEND_TIMEOUT_CFG.get() * 1000)

    # 活动id
    options.event_id = None
        
    # 歌曲id和难度
    args = await extract_music_and_diff(ctx, args, options, "event", options.live_type)

    # 组卡限制
    options.limit = DEFAULT_LIMIT

    # bfes技能计算策略
    options.skill_reference_choose_strategy = "max"

    # 模拟退火设置
    options.sa_options = DeckRecommendSaOptions()
    options.sa_options.max_no_improve_iter = 50000

    return {
        'options': options,
        'last_args': args.strip(),
        'additional': additional,
    }

# 从args中提取组卡参数
async def extract_unit_attr_spec_options(ctx: SekaiHandlerContext, args: str) -> Dict:
    args = ctx.get_args().strip().lower()
    options = DeckRecommendOptions()

    additional, args = extract_addtional_options(args)

    # live类型
    if "多人" in args or '协力' in args: 
        options.live_type = "multi"
        args = args.replace("多人", "").replace("协力", "").strip()
    elif "单人" in args: 
        options.live_type = "solo"
        args = args.replace("单人", "").strip()
    elif "自动" in args or "auto" in args: 
        options.live_type = "auto"
        args = args.replace("自动", "").replace("auto", "").strip()
    else:
        options.live_type = "multi"

    args = extract_multilive_options(args, options)
    args = extract_fixed_cards_and_characters(args, options)
    args = extract_card_config(args, options)
    args = extract_target(args, options)

    # 算法
    options.algorithm = "all"
    options.timeout_ms = int(RECOMMEND_TIMEOUT_CFG.get() * 1000)
    if "dfs" in args:
        options.algorithm = "dfs"
        args = args.replace("dfs", "").strip()
        options.timeout_ms = int(SINGLE_ALG_RECOMMEND_TIMEOUT_CFG.get() * 1000)

    # 5v5
    if "5v5" in args or "5V5" in args:
        options.live_type = "multi"
        args = args.replace("5v5", "").replace("5V5", "").strip()
        options.event_type = "cheerful_carnival"

    # 活动id
    options.event_id = None
    options.event_unit, args = extract_unit(args, default=None)
    options.event_attr, args = extract_card_attr(args, default=None)

    unit_hint = "请指定组卡的团（ln/mmj/vbs/ws/25/vs）\n"
    attr_hint = "请指定组卡的属性（例如: 紫/紫月/月亮）\n"
    hint = ""
    if not options.event_unit:  hint += unit_hint
    if not options.event_attr:  hint += attr_hint
    if hint:
        hint += "该指令用于组指定团&属性加成的模拟活动（暂不支持模拟wl），组实际存在的活动使用\"/活动组卡\"，与活动无关的组卡使用\"/最强组卡\""
        raise ReplyException(hint.strip())
        
    # 歌曲id和难度
    args = await extract_music_and_diff(ctx, args, options, "event", options.live_type)

    # 组卡限制
    options.limit = DEFAULT_LIMIT

    # bfes技能计算策略
    options.skill_reference_choose_strategy = "average"

    # 模拟退火设置
    options.sa_options = DeckRecommendSaOptions()
    options.sa_options.max_no_improve_iter = 10000

    return {
        'options': options,
        'last_args': args.strip(),
        'additional': additional,
    }

# 从args中提取加成组卡参数
async def extract_bonus_options(ctx: SekaiHandlerContext, args: str) -> Dict:
    args = ctx.get_args().strip().lower()
    options = DeckRecommendOptions()

    additional, args = extract_addtional_options(args)

    options.algorithm = "dfs"
    options.timeout_ms = int(BONUS_RECOMMEND_TIMEOUT_CFG.get() * 1000)
    options.target = "bonus"
    options.live_type = "solo"

    # 卡牌设置
    options.rarity_1_config = NOCHANGE_CARD_CONFIG
    options.rarity_2_config = NOCHANGE_CARD_CONFIG
    options.rarity_3_config = NOCHANGE_CARD_CONFIG
    options.rarity_4_config = NOCHANGE_CARD_CONFIG
    options.rarity_birthday_config = NOCHANGE_CARD_CONFIG

    # 活动id
    event, wl_cid, args = await extract_target_event(ctx, args, need_event_prefix=True)
    options.event_id = event['id']
    options.world_bloom_character_id = wl_cid
        
    # 歌曲id和难度
    await extract_music_and_diff(ctx, "", options, "event", options.live_type)

    # 组卡限制
    options.limit = BONUS_TARGET_LIMIT

    # 目标加成
    try:
        options.target_bonus_list = list(map(int, args.split()))
        assert options.target_bonus_list
    except:
        raise ReplyException("使用方式: /加成组卡 其他参数 100 200 300 ...")

    return {
        'options': options,
        'last_args': '',
        'additional': additional,
    }


# ======================= 处理逻辑 ======================= #

RECOMMEND_SERVE_URL = "http://localhost:45556/recommend"

# 添加OMAKASE音乐
def add_omakase_music(music_metas: list[dict]) -> list[dict]:
    if find_by(music_metas, "id", OMAKASE_MUSIC_ID) is None:
        omakase = {
            "music_id": OMAKASE_MUSIC_ID,
            "difficulty": None,
            "music_time": 0.0,
            "event_rate": 0.0,
            "base_score": 0.0,
            "base_score_auto": 0.0,
            "skill_score_solo": [0.0 for _ in range(6)],
            "skill_score_auto": [0.0 for _ in range(6)],
            "skill_score_multi": [0.0 for _ in range(6)],
            "fever_score": 0,
            "fever_end_time": 0,
            "tap_count": 0,
        }

        music_count = 0
        for item in music_metas:
            if item['difficulty'] in OMAKASE_MUSIC_DIFFS:
                omakase['music_time'] += item['music_time']
                omakase['event_rate'] += item['event_rate']
                omakase['base_score'] += item['base_score']
                omakase['base_score_auto'] += item['base_score_auto']
                for i in range(6):
                    omakase['skill_score_solo'][i] += item['skill_score_solo'][i]
                    omakase['skill_score_auto'][i] += item['skill_score_auto'][i]
                    omakase['skill_score_multi'][i] += item['skill_score_multi'][i]
                omakase['fever_score'] += item['fever_score']
                omakase['fever_end_time'] += item['fever_end_time']
                omakase['tap_count'] += item['tap_count']
                music_count += 1

        omakase['music_time'] /= music_count
        omakase['event_rate'] = int(omakase['event_rate'] / music_count)
        omakase['base_score'] /= music_count
        omakase['base_score_auto'] /= music_count
        for i in range(6):
            omakase['skill_score_solo'][i] /= music_count
            omakase['skill_score_auto'][i] /= music_count
            omakase['skill_score_multi'][i] /= music_count
        omakase['fever_score'] /= music_count
        omakase['fever_end_time'] /= music_count
        omakase['tap_count'] = int(omakase['tap_count'] / music_count)

        for difficulty in ('easy', 'normal', 'hard', 'expert', 'master', 'append'):
            new_omakase = omakase.copy()
            new_omakase['difficulty'] = difficulty
            music_metas.append(new_omakase)
    return music_metas

# 获取deck的hash
def get_deck_hash(deck: RecommendDeck) -> str:
    deck_hash = str(deck.score) + str(deck.total_power) + str(deck.cards[0].card_id)
    return deck_hash

# 打印组卡配置
def log_options(ctx: SekaiHandlerContext, user_id: int, options: DeckRecommendOptions):
    def cardconfig2str(cfg: DeckRecommendCardConfig):
        return f"{(int)(cfg.disable)}{(int)(cfg.level_max)}{(int)(cfg.episode_read)}{(int)(cfg.master_max)}{(int)(cfg.skill_max)}"
    log = "组卡配置: "
    log += f"region={ctx.region}, "
    log += f"uid={user_id}, "
    log += f"type={options.live_type}, "
    log += f"mid={options.music_id}, "
    log += f"mdiff={options.music_diff}, "
    log += f"eid={options.event_id}, "
    log += f"wl_cid={options.world_bloom_character_id}, "
    log += f"challenge_cid={options.challenge_live_character_id}, "
    log += f"limit={options.limit}, "
    log += f"member={options.member}, "
    log += f"rarity1={cardconfig2str(options.rarity_1_config)}, "
    log += f"rarity2={cardconfig2str(options.rarity_2_config)}, "
    log += f"rarity3={cardconfig2str(options.rarity_3_config)}, "
    log += f"rarity4={cardconfig2str(options.rarity_4_config)}, "
    log += f"rarity_bd={cardconfig2str(options.rarity_birthday_config)}, "
    log += f"fixed_cards={options.fixed_cards}"
    logger.info(log)

# 自动组卡实现 返回Tuple[结果，结果算法来源，Dict[算法: Tuple[耗时，等待时间]]]
async def do_deck_recommend(
    ctx: SekaiHandlerContext, 
    options: DeckRecommendOptions,
) -> Tuple[DeckRecommendResult, List[str], Dict[str, Tuple[timedelta, timedelta]]]:
    # 检查数据更新
    with Timer("deckrec:checkupdate", logger):
        async with data_update_lock:
            global last_deck_recommend_masterdata_version
            global last_deck_recommend_masterdata_update_time
            global last_deck_recommend_musicmetas_update_time
            
            # 更新masterdata
            if last_deck_recommend_masterdata_version.get(ctx.region) != await ctx.md.get_version():
                logger.info(f"重新加载本地自动组卡 {ctx.region} masterdata")
                # 确保所有masterdata就绪
                mds = [
                    ctx.md.area_item_levels.get(),
                    ctx.md.area_items.get(),
                    ctx.md.areas.get(),
                    ctx.md.card_episodes.get(),
                    ctx.md.cards.get(),
                    ctx.md.card_rarities.get(),
                    ctx.md.character_ranks.get(),
                    ctx.md.event_cards.get(),
                    ctx.md.event_deck_bonuses.get(),
                    ctx.md.event_exchange_summaries.get(),
                    ctx.md.events.get(),
                    ctx.md.event_items.get(),
                    ctx.md.event_rarity_bonus_rates.get(),
                    ctx.md.game_characters.get(),
                    ctx.md.game_character_units.get(),
                    ctx.md.honors.get(),
                    ctx.md.master_lessons.get(),
                    ctx.md.music_diffs.get(),
                    ctx.md.musics.get(),
                    ctx.md.music_vocals.get(),
                    ctx.md.shop_items.get(),
                    ctx.md.skills.get(),
                    ctx.md.world_bloom_different_attribute_bonuses.get(),
                    ctx.md.world_blooms.get(),
                    ctx.md.world_bloom_support_deck_bonuses.get(),
                ]
                if ctx.region in MYSEKAI_REGIONS:
                    mds += [
                        ctx.md.world_bloom_support_deck_unit_event_limited_bonuses.get(),
                        ctx.md.card_mysekai_canvas_bonuses.get(),
                        ctx.md.mysekai_fixture_game_character_groups.get(),
                        ctx.md.mysekai_fixture_game_character_group_performance_bonuses.get(),
                        ctx.md.mysekai_gates.get(),
                        ctx.md.mysekai_gate_levels.get(),
                    ]
                await asyncio.gather(*mds)
                last_deck_recommend_masterdata_version[ctx.region] = await ctx.md.get_version()
                last_deck_recommend_masterdata_update_time[ctx.region] = datetime.now()

            # 更新musicmetas
            if last_deck_recommend_musicmetas_update_time.get(ctx.region) is None \
                or datetime.now() - last_deck_recommend_musicmetas_update_time[ctx.region] > DECK_RECOMMEND_MUSICMETAS_UPDATE_INTERVAL:
                logger.info(f"重新加载本地自动组卡 {ctx.region} musicmetas")
                try:
                    # 尝试从网络下载
                    musicmetas = await musicmetas_json.get()
                    musicmetas = add_omakase_music(musicmetas)
                    await adump_json(musicmetas, MUSICMETAS_SAVE_PATH)
                except Exception as e:
                    logger.warning(f"下载music_metas.json失败: {get_exc_desc(e)}")
                    if os.path.exists(MUSICMETAS_SAVE_PATH):
                        # 使用本地缓存
                        logger.info(f"使用本地缓存music_metas.json")
                    else:
                        raise ReplyException(f"获取music_metas.json失败: {get_exc_desc(e)}")
                last_deck_recommend_musicmetas_update_time[ctx.region] = datetime.now()

    # 算法选择
    if options.algorithm == "all": 
        algs = RECOMMEND_ALGS_CFG.get()
    else:
        algs = [options.algorithm]

    # 请求组卡函数
    async def request_recommend(options: DeckRecommendOptions) -> dict:
        payload = {
            'create_ts': datetime.now().timestamp(),
            'region': options.region,
            'masterdata_path': f"{SEKAI_ASSET_DIR}/masterdata/{options.region}/",
            'masterdata_update_ts': last_deck_recommend_masterdata_update_time[options.region].timestamp(),
            'musicmetas_path': MUSICMETAS_SAVE_PATH,
            'musicmetas_update_ts': last_deck_recommend_musicmetas_update_time[options.region].timestamp(),
            'options': options.to_dict(),
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(RECOMMEND_SERVE_URL, json=payload) as resp:
                if resp.status != 200:
                    raise ReplyException(f"组卡请求失败: HTTP {resp.status}")
                data = await resp.json()
                if data['status'] != 'success':
                    raise ReplyException(data['exception'])
                return data

    # 组卡!
    futs = []
    for alg in algs:
        opt = DeckRecommendOptions(options)
        opt.algorithm = alg
        futs.append(request_recommend(opt))
    with Timer("deckrec:request", logger):
        results: List[dict] = await asyncio.gather(*futs)

    # 结果排序去重
    decks: List[RecommendDeck] = []
    cost_and_wait_times = {}
    deck_src_alg = {}
    for resp in results:
        alg = resp['alg']
        cost_time = resp['cost_time']
        wait_time = resp['wait_time']
        result = DeckRecommendResult.from_dict(resp['result'])
        cost_and_wait_times[alg] = (cost_time, wait_time)
        for deck in result.decks:
            deck_hash = get_deck_hash(deck)
            if deck_hash not in deck_src_alg:
                deck_src_alg[deck_hash] = alg
                decks.append(deck)
            else:
                deck_src_alg[deck_hash] += "+" + alg
    def key_func(deck: RecommendDeck):
        if options.target == "score":
            return (deck.score, deck.multi_live_score_up)
        elif options.target == "power":
            return deck.total_power
        elif options.target == "skill":
            return deck.multi_live_score_up
        elif options.target == "bonus":
            return (-deck.event_bonus_rate, deck.score)
    limit = options.limit if options.target != "bonus" else options.limit * len(options.target_bonus_list)
    decks = sorted(decks, key=key_func, reverse=True)[:limit]
    src_algs = [deck_src_alg[get_deck_hash(deck)] for deck in decks]
    res = DeckRecommendResult()
    # 加成组卡的队伍按照加成排序
    if options.target == "bonus":
        for deck in decks:
            deck.cards = sorted(deck.cards, key=lambda x: x.event_bonus_rate, reverse=True)
    res.decks = decks
    return res, src_algs, cost_and_wait_times

# 构造顶配profile
async def construct_max_profile(ctx: SekaiHandlerContext) -> dict:
    try: 
        await ctx.md.mysekai_gates.get()
        has_mysekai = True
    except:
        has_mysekai = False

    p = {
        'userGamedata': {},
        'userDecks': [],
        'userCards': [],
        'userHonors': [],
        "userMysekaiCanvases": [],
        "userCharacters": [],
        "userMysekaiGates": [],
        "userMysekaiFixtureGameCharacterPerformanceBonuses": [],
        "userAreas": [],
    }

    for card in await ctx.md.cards.get():
        release_time = datetime.fromtimestamp(card['releaseAt'] / 1000)
        if release_time > datetime.now():
            continue
        episodes = await ctx.md.card_episodes.find_by("cardId", card['id'], mode='all')
        p["userCards"].append({
            "cardId": card['id'],
            "level": 1,
            "skillLevel": 4,
            "masterRank": 5,
            "specialTrainingStatus": "done" if has_after_training(card) else "none",
            "defaultImage": "special_training" if has_after_training(card) else "original",
            "episodes": [
                {
                    "cardEpisodeId": ep['id'],
                    "scenarioStatus": "already_read",
                } for ep in episodes
            ]
        })
        if has_mysekai:
            p['userMysekaiCanvases'].append({
                'cardId': card['id'],
                "quantity": 1,
            })

    for honor in await ctx.md.honors.get():
        if honor.get('levels'):
            p['userHonors'].append({
                "honorId": honor['id'],
                "level": honor['levels'][-1]['level'],
            })

    for cid in range(1, 27):
        p['userCharacters'].append({
            "characterId": cid,
            "characterRank": 120,
        })

    if has_mysekai:
        for gid in range(1, 6):
            p['userMysekaiGates'].append({
                "mysekaiGateId": gid,
                "mysekaiGateLevel": 40,
            })
        
        fixture_chara_bonus = { cid: 0 for cid in range(1, 27) }
        for fixture in await ctx.md.mysekai_fixtures.get():
            bid = fixture.get('mysekaiFixtureGameCharacterGroupPerformanceBonusId')
            if bid:
                cid = (bid - 1) // 3 + 1
                t = (bid - 1) % 3
                if t == 0: fixture_chara_bonus[cid] += 1
                elif t == 1: fixture_chara_bonus[cid] += 3
                else: fixture_chara_bonus[cid] += 6
        for cid in range(1, 27):
            p['userMysekaiFixtureGameCharacterPerformanceBonuses'].append({
                "gameCharacterId": cid,
                "totalBonusRate": min(fixture_chara_bonus[cid], 100)
            })
    
    levels = {}
    for item in await ctx.md.area_item_levels.get():
        item_id = item['areaItemId']
        lv = item['level']
        levels[item_id] = max(levels.get(item_id, 0), lv)
    p['userAreas'].append({
        "userAreaStatus": {},
        "areaItems": [
            {
                "areaItemId": item_id,
                "level": lv,
            } for item_id, lv in levels.items()
        ]
    })

    return p


# 合成自动组卡图片
async def compose_deck_recommend_image(
    ctx: SekaiHandlerContext, 
    qid: int,
    options: DeckRecommendOptions,
    last_args: str,
    additional: dict,
) -> Image.Image:
    # 是哪种组卡类型
    is_wl = options.world_bloom_character_id or options.event_id == 180
    if options.target == "bonus":
        if is_wl:
            recommend_type = "wl_bonus"
        else:
            recommend_type = "bonus"
    elif options.live_type == "challenge":
        if options.challenge_live_character_id:
            recommend_type = "challenge"
        else:
            recommend_type = "challenge_all"
    elif options.event_id:
        if is_wl:
            recommend_type = "wl"
        else:
            recommend_type = "event"
    else:
        if options.event_unit:
            recommend_type = "unit_attr"
        else:
            recommend_type = "no_event"

    # 是否是顶配租卡
    use_max_profile = additional.get('max_profile', False)
    if use_max_profile:
        profile = await construct_max_profile(ctx)
        uid = None
    else:
        # 用户信息
        with Timer("deckrec:get_detailed_profile", logger):
            profile, pmsg = await get_detailed_profile(ctx, qid, raise_exc=True, ignore_hide=True)
            uid = profile['userGamedata']['userId']

    original_usercards = profile['userCards']
    # 组合卡牌过滤
    unit_filter = additional.get('unit_filter', None)
    if unit_filter:
        profile['userCards'] = [
            uc for uc in profile['userCards']
            if await get_unit_by_card_id(ctx, uc['cardId']) == unit_filter
        ]
    # 属性卡牌过滤
    attr_filter = additional.get('attr_filter', None)
    if attr_filter:
        profile['userCards'] = [
            uc for uc in profile['userCards']
            if (await ctx.md.cards.find_by_id(uc['cardId']))['attr'] == attr_filter
        ]
    # 排除卡牌
    excluded_cards = additional.get('excluded_cards', [])
    if excluded_cards:
        profile['userCards'] = [
            uc for uc in profile['userCards']
            if uc['cardId'] not in excluded_cards
        ]

    # 使用当前队伍
    use_current_deck = additional.get('use_current_deck', False)
    if use_current_deck:
        assert_and_reply(options.live_type not in ['challenge'], "暂不支持获取挑战组卡的当前队伍")
        basic_profile = await get_basic_profile(
            ctx, get_player_bind_id(ctx, qid, check_bind=True), 
            use_cache=False, use_remote_cache=False,
        )
        options.fixed_cards = [basic_profile['userDeck'][f'member{i}'] for i in range(1, 6)]
        options.fixed_characters = None
        options.best_skill_as_leader = False
        # 转移basic_profile中的卡到profile中
        for bp_card in basic_profile['userCards']:
            if p_card := find_by(profile['userCards'], 'cardId', bp_card['cardId']):
                p_card.update(bp_card)
            else:
                profile['userCards'].append(bp_card)

    # 准备用户数据
    with TempFilePath("json") as userdata_path:
        with Timer("deckrec:dump_profile", logger):
            await adump_json(profile, userdata_path)

        options.region = ctx.region
        options.user_data_file_path = userdata_path
        log_options(ctx, uid, options)
        # 还原profile避免画头像问题
        profile['userCards'] = original_usercards

        # 组卡！
        cost_times, wait_times = {}, {}
        result_decks = []
        result_algs = []
        if recommend_type == "challenge_all":
            # 挑战组卡没有指定角色情况下，每角色组1个最强
            for cid in range(1, 26 + 1):
                options.challenge_live_character_id = cid
                options.limit = 1
                res, algs, cost_and_wait_times = await do_deck_recommend(ctx, options)
                result_decks.extend(res.decks)
                result_algs.extend(algs)
                for alg, (cost, wait) in cost_and_wait_times.items():
                    if alg not in cost_times:
                        cost_times[alg] = 0
                        wait_times[alg] = 0
                    cost_times[alg] += cost
                    wait_times[alg] = max(wait_times[alg], wait)
            options.challenge_live_character_id = None
        else:
            # 正常组卡
            res, algs, cost_and_wait_times = await do_deck_recommend(ctx, options)
            for alg, (cost, wait) in cost_and_wait_times.items():
                cost_times[alg] = cost
                wait_times[alg] = wait
            result_decks = res.decks
            result_algs = algs

    # 获取音乐标题和封面
    if options.music_id == OMAKASE_MUSIC_ID:
        music_title = "おまかせ（所有歌曲平均）"
        music_cover = ctx.static_imgs.get('omakase.png')
    else:
        music = await ctx.md.musics.find_by_id(options.music_id)
        asset_name = music['assetbundleName']
        music_title = music['title']
        music_title += f" ({options.music_diff.upper()})"
        music_cover = await ctx.rip.img(f"music/jacket/{asset_name}_rip/{asset_name}.png", use_img_cache=True)

    # 获取活动banner和标题
    live_name = "协力"
    if recommend_type in ["event", "wl", "bonus", "wl_bonus"]:
        event = await ctx.md.events.find_by_id(options.event_id)
        event_banner = await get_event_banner_img(ctx, event)
        event_title = event['name']
        if event['eventType'] == 'cheerful_carnival':
            live_name = "5v5" 

    # 团队属性组卡指定5v5
    if recommend_type == "unit_attr" and options.event_type == "cheerful_carnival":
        live_name = "5v5"
        
    # 获取挑战角色名字和头像
    chara_name = None
    if recommend_type == "challenge":
        chara = await ctx.md.game_characters.find_by_id(options.challenge_live_character_id)
        chara_name = chara.get('firstName', '') + chara.get('givenName', '')
        chara_icon = get_chara_icon_by_chara_id(chara['id'])

    # 获取WL角色名字和头像
    wl_chara_name = None
    if recommend_type in ["wl", "wl_bonus"] and options.world_bloom_character_id:
        wl_chara = await ctx.md.game_characters.find_by_id(options.world_bloom_character_id)
        if wl_chara:
            wl_chara_name = wl_chara.get('firstName', '') + wl_chara.get('givenName', '')
            wl_chara_icon = get_chara_icon_by_chara_id(wl_chara['id'])
        else:
            wl_chara_name = ""
            wl_chara_icon = None

    # 获取指定团名和属性的icon和logo
    if recommend_type == "unit_attr":
        unit_logo = get_unit_logo(options.event_unit)
        attr_icon = get_attr_icon(options.event_attr)

    # 获取缩略图
    draw_eventbonus = recommend_type in ["bonus", "wl_bonus"]
    async def _get_thumb(card, pcard):
        try: 
            custom_text = None
            if draw_eventbonus:
                bonus = pcard.get('eventBonus', 0)
                if abs(bonus - int(bonus)) < 0.01:
                    bonus = int(bonus)
                custom_text = f"+{bonus}%"
            return await get_card_full_thumbnail(ctx, card, pcard=pcard, custom_text=custom_text)
        except: 
            return UNKNOWN_IMG
    card_imgs, card_keys = [], []
    for deck in result_decks:
        for deckcard in deck.cards:
            card = await ctx.md.cards.find_by_id(deckcard.card_id)
            usercard = find_by(profile['userCards'], 'cardId', deckcard.card_id)
            pcard = {
                'cardId': deckcard.card_id,
                'defaultImage': deckcard.default_image,                                 # 默认图片跟随组卡结果
                'specialTrainingStatus': usercard.get('specialTrainingStatus', 'none') if usercard else 'none', # 稀有度图标绘制跟随原本卡组
                'level': deckcard.level,
                'masterRank': deckcard.master_rank,
                'eventBonus': deckcard.event_bonus_rate,
            }
            card_key = f"{deckcard.card_id}_{deckcard.default_image}"
            if card_key not in card_keys:
                card_keys.append(card_key)
                card_imgs.append(_get_thumb(card, pcard))
    card_imgs = await asyncio.gather(*card_imgs)
    card_imgs = { key : img for key, img in zip(card_keys, card_imgs) }

    # 获取挑战live额外分数信息
    challenge_score_dlt = []
    if recommend_type in ["challenge", "challenge_all"]:
        try: challenge_live_info = await get_user_challenge_live_info(ctx, profile)
        except: challenge_live_info = {}
        for deck in result_decks:
            card_id = deck.cards[0].card_id
            chara_id = (await ctx.md.cards.find_by_id(card_id))['characterId']
            _, high_score, _, _ = challenge_live_info.get(chara_id, (None, 0, None, None))
            challenge_score_dlt.append(deck.score - high_score)
        
    # 绘图
    with Canvas(bg=SEKAI_BLUE_BG).set_padding(BG_PADDING) as canvas:
        with VSplit().set_content_align('lt').set_item_align('lt').set_sep(16).set_padding(16):
            if not use_max_profile:
                await get_detailed_profile_card(ctx, profile, pmsg)

            with VSplit().set_content_align('lt').set_item_align('lt').set_sep(16).set_padding(16).set_bg(roundrect_bg()):
                # 标题
                with VSplit().set_content_align('lb').set_item_align('lb').set_sep(16).set_padding(16).set_bg(roundrect_bg()):
                    title = ""

                    if recommend_type in ['challenge', 'challenge_all']: 
                        title += "每日挑战组卡"
                    elif recommend_type in ['bonus', 'wl_bonus']:
                        if recommend_type == "bonus":
                            title += f"活动加成组卡"
                        elif recommend_type == "wl_bonus":
                            title += f"WL活动加成组卡"
                    else:
                        if recommend_type == "event":
                            title += "活动组卡"
                        elif recommend_type == "wl":
                            if wl_chara_name:
                                title += f"WL活动组卡"
                            else:
                                title += f"WL终章活动组卡"
                        elif recommend_type == "unit_attr":
                            title += f"指定团队&属性组卡"
                        elif recommend_type == "no_event":
                            title += f"无活动组卡"
                    
                        if options.live_type == "multi":
                            title += f"({live_name})"
                        elif options.live_type == "solo":
                            title += "(单人)"
                        elif options.live_type == "auto":
                            title += "(AUTO)"
                    
                    score_name = "PT"
                    if recommend_type in ["challenge", "challenge_all", "no_event"]:
                        score_name = "分数"  

                    target = score_name
                    if options.target == "power":
                        target = "综合力"
                    elif options.target == "skill":
                        target = "实效"

                    with HSplit().set_content_align('l').set_item_align('l').set_sep(16):
                        if recommend_type in ["event", "wl", "bonus", "wl_bonus"]:
                            if event_banner:
                                ImageBox(event_banner, size=(None, 50))
                            else:
                                title = event_title + " " + title

                        TextBox(title, TextStyle(font=DEFAULT_BOLD_FONT, size=30, color=(50, 50, 50)), use_real_line_count=True)

                        if recommend_type == "challenge":
                            ImageBox(chara_icon, size=(None, 50))
                            TextBox(f"{chara_name}", TextStyle(font=DEFAULT_BOLD_FONT, size=30, color=(70, 70, 70)))
                        if recommend_type in ["wl"] and wl_chara_name:
                            ImageBox(wl_chara_icon, size=(None, 50))
                            TextBox(f"{wl_chara_name} 章节", TextStyle(font=DEFAULT_BOLD_FONT, size=30, color=(70, 70, 70)))
                        if recommend_type == "unit_attr":
                            ImageBox(unit_logo, size=(None, 60))
                            ImageBox(attr_icon, size=(None, 50))
                        
                        if use_max_profile:
                            TextBox(f"({get_region_name(ctx.region)}顶配)", TextStyle(font=DEFAULT_BOLD_FONT, size=30, color=(50, 50, 50)))

                    if any([
                        unit_filter, attr_filter, 
                        excluded_cards, 
                        options.multi_live_score_up_lower_bound, 
                        options.keep_after_training_state,
                    ]):
                        with HSplit().set_content_align('l').set_item_align('l').set_sep(16):
                            setting_style = TextStyle(font=DEFAULT_BOLD_FONT, size=24, color=(50, 50, 50))
                            TextBox("卡组设置:", setting_style)
                            if unit_filter or attr_filter:
                                TextBox(f"仅", setting_style)
                                if unit_filter: ImageBox(get_unit_logo(unit_filter), size=(None, 40))
                                if attr_filter: ImageBox(get_attr_icon(attr_filter), size=(None, 35))
                                TextBox(f"上场", setting_style)
                            if excluded_cards:
                                TextBox(f"排除 {','.join(map(str, excluded_cards))}", setting_style)
                            if options.multi_live_score_up_lower_bound:
                                TextBox(f"实效≥{int(options.multi_live_score_up_lower_bound)}%", setting_style)
                            if options.keep_after_training_state:
                                TextBox(f"禁用双技能自动切换", setting_style)
                            
                    if recommend_type in ["bonus", "wl_bonus"]:
                        TextBox(f"友情提醒：控分前请核对加成和体力设置", TextStyle(font=DEFAULT_BOLD_FONT, size=26, color=(255, 50, 50)))
                        if recommend_type == "wl_bonus":
                            TextBox(f"WL仅支持自动组主队，支援队请自行配置", TextStyle(font=DEFAULT_FONT, size=26, color=(50, 50, 50)))
                    else:
                        with HSplit().set_content_align('l').set_item_align('l').set_sep(16):
                            if last_args:
                                TextBox(f"{last_args} → ", TextStyle(font=DEFAULT_BOLD_FONT, size=26, color=(70, 70, 70)))
                            with Frame().set_size((50, 50)):
                                if options.music_id != OMAKASE_MUSIC_ID:
                                    Spacer(w=50, h=50).set_bg(FillBg(fill=DIFF_COLORS[options.music_diff])).set_offset((6, 6))
                                ImageBox(music_cover, size=(50, 50))
                            TextBox(music_title, TextStyle(font=DEFAULT_BOLD_FONT, size=26, color=(70, 70, 70)))
                    
                    if last_args:
                        arg_unit, args = extract_unit(last_args)
                        arg_attr, args = extract_card_attr(last_args)
                        if arg_unit or arg_attr:
                            TextBox(f"检测到你的歌曲查询中包含团名/颜色，可能是参数格式不正确\n"
                                     "如果你想指定仅包含某个团名/颜色的卡牌请用: 纯mmj 纯绿", 
                                    TextStyle(font=DEFAULT_BOLD_FONT, size=24, color=(200, 75, 75)), use_real_line_count=True)

                # 表格
                gh, vsp, voffset = 120, 12, 18
                with VSplit().set_content_align('c').set_item_align('c').set_sep(16).set_padding(16).set_bg(roundrect_bg()):
                    if len(result_decks) > 0:
                        with HSplit().set_content_align('c').set_item_align('c').set_sep(16).set_padding(0):
                            th_style1 = TextStyle(font=DEFAULT_BOLD_FONT, size=28, color=(0, 0, 0))
                            th_style2 = TextStyle(font=DEFAULT_BOLD_FONT, size=28, color=(75, 75, 75))
                            th_main_sign = '∇'
                            tb_style = TextStyle(font=DEFAULT_BOLD_FONT, size=24, color=(70, 70, 70))

                            # 分数
                            if recommend_type not in ["bonus", "wl_bonus"]:
                                with VSplit().set_content_align('c').set_item_align('c').set_sep(vsp).set_padding(8):
                                    target_score = options.target == "score"
                                    text = score_name + th_main_sign if target_score else score_name
                                    style = th_style1 if target_score else th_style2
                                    TextBox(text, style).set_h(gh // 2).set_content_align('c')
                                    Spacer(h=6)
                                    for i, (deck, alg) in enumerate(zip(result_decks, result_algs)):
                                        with Frame().set_content_align('rb'):
                                            alg_offset = 0
                                            # 挑战分数差距
                                            if recommend_type in ['challenge', 'challenge_all']:
                                                alg_offset = 20
                                                dlt = challenge_score_dlt[i]
                                                color = (50, 150, 50) if dlt > 0 else (150, 50, 50)
                                                TextBox(f"{dlt:+d}", TextStyle(font=DEFAULT_FONT, size=15, color=color)).set_offset((0, -8-voffset*2))
                                            # 算法
                                            TextBox(alg.upper(), TextStyle(font=DEFAULT_FONT, size=12, color=(125, 125, 125))).set_offset((0, -8-voffset*2+alg_offset))
                                            # 分数
                                            score = deck.live_score if recommend_type == "no_event" else deck.score
                                            with Frame().set_content_align('c'):
                                                TextBox(str(score), tb_style).set_h(gh).set_content_align('c').set_offset((0, -voffset))

                            # 卡片
                            with VSplit().set_content_align('c').set_item_align('c').set_sep(vsp).set_padding(8):
                                TextBox("卡组", th_style2).set_h(gh // 2).set_content_align('c')
                                Spacer(h=6)
                                for deck in result_decks:
                                    with HSplit().set_content_align('c').set_item_align('c').set_sep(8).set_padding(0):
                                        for card in deck.cards:
                                            card_id = card.card_id
                                            character_id = (await ctx.md.cards.find_by_id(card_id))['characterId']
                                            event_bonus = card.event_bonus_rate
                                            ep1_read, ep2_read = card.episode1_read, card.episode2_read
                                            slv, sup = card.skill_level, int(card.skill_score_up)

                                            with VSplit().set_content_align('c').set_item_align('c').set_sep(4).set_padding(0).set_h(gh):
                                                with Frame().set_content_align('rt'):
                                                    card_key = f"{card_id}_{card.default_image}"
                                                    ImageBox(card_imgs[card_key], size=(None, 80))
                                                    if options.fixed_cards and card_id in options.fixed_cards \
                                                    or options.fixed_characters and character_id in options.fixed_characters:
                                                        TextBox(str(card_id), TextStyle(font=DEFAULT_FONT, size=10, color=WHITE)) \
                                                            .set_bg(RoundRectBg((200, 50, 50, 200), 2)).set_offset((-2, 0))
                                                    else:
                                                        TextBox(str(card_id), TextStyle(font=DEFAULT_FONT, size=10, color=(75, 75, 75))) \
                                                            .set_bg(RoundRectBg((255, 255, 255, 200), 2)).set_offset((-2, 0))
                                                    if card.has_canvas_bonus:
                                                        ImageBox(ctx.static_imgs.get(f"mysekai/icon_canvas.png"), size=(11, 11)) \
                                                                .set_offset((-32, 65))

                                                info_bg = RoundRectBg((255, 255, 255, 150), 2)
                                                with HSplit().set_content_align('c').set_item_align('c').set_sep(3).set_padding(0):
                                                    TextBox(f"SLv.{slv}", TextStyle(font=DEFAULT_FONT, size=12, color=(50, 50, 50))).set_bg(info_bg)
                                                    TextBox(f"↑{sup}%", TextStyle(font=DEFAULT_FONT, size=12, color=(50, 50, 50))).set_bg(info_bg)
                                                
                                                with HSplit().set_content_align('c').set_item_align('c').set_sep(3).set_padding(0):
                                                    show_event_bonus = event_bonus > 0
                                                    if show_event_bonus:
                                                        event_bonus_str = f"+{event_bonus:.1f}%" if int(event_bonus) != event_bonus else f"+{int(event_bonus)}%"
                                                        TextBox(event_bonus_str, TextStyle(font=DEFAULT_FONT, size=12, color=(50, 50, 50))).set_bg(info_bg)
                                                    read_fg, read_bg = (50, 150, 50, 255), (255, 255, 255, 255)
                                                    noread_fg, noread_bg = (150, 50, 50, 255), (255, 255, 255, 255)
                                                    none_fg, none_bg = (255, 255, 255, 255), (255, 255, 255, 255)
                                                    ep1_fg = none_fg if ep1_read is None else (read_fg if ep1_read else noread_fg)
                                                    ep1_bg = none_bg if ep1_read is None else (read_bg if ep1_read else noread_bg)
                                                    ep2_fg = none_fg if ep2_read is None else (read_fg if ep2_read else noread_fg)
                                                    ep2_bg = none_bg if ep2_read is None else (read_bg if ep2_read else noread_bg)
                                                    TextBox("前" if show_event_bonus else "前篇", TextStyle(font=DEFAULT_FONT, size=12, color=ep1_fg)).set_bg(info_bg)
                                                    TextBox("后" if show_event_bonus else "后篇", TextStyle(font=DEFAULT_FONT, size=12, color=ep2_fg)).set_bg(info_bg)

                            # 加成
                            if recommend_type not in ["challenge", "challenge_all", "no_event"]:
                                with VSplit().set_content_align('c').set_item_align('c').set_sep(vsp).set_padding(8):
                                    TextBox("加成", th_style2).set_h(gh // 2).set_content_align('c')
                                    Spacer(h=6)
                                    for deck in result_decks:
                                        if is_wl:
                                            bonus = f"{deck.event_bonus_rate:.1f}+{deck.support_deck_bonus_rate:.1f}%"
                                            total = f"{deck.event_bonus_rate+deck.support_deck_bonus_rate:.1f}%"
                                        else:
                                            bonus = None
                                            total = f"{deck.event_bonus_rate:.1f}%"
                                        with Frame().set_content_align('rb'):
                                            if bonus is not None:
                                                TextBox(bonus, TextStyle(font=DEFAULT_FONT, size=14, color=(150, 150, 150))).set_offset((0, -6-voffset*2))
                                            with Frame().set_content_align('c'):
                                                TextBox(total, tb_style).set_h(gh).set_content_align('c').set_offset((0, -voffset))

                            # 实效
                            if options.live_type in ['multi', 'cheerful']:
                                with VSplit().set_content_align('c').set_item_align('c').set_sep(vsp).set_padding(8):
                                    target_skill = options.target == "skill"
                                    text = "实效" + th_main_sign if target_skill else "实效"
                                    style = th_style1 if target_skill else th_style2
                                    TextBox(text, style).set_h(gh // 2).set_content_align('c')
                                    Spacer(h=6)
                                    for deck in result_decks:
                                        with Frame().set_content_align('rb'):
                                            if options.multi_live_teammate_score_up is not None:
                                                teammate_text = f"队友 {int(options.multi_live_teammate_score_up)}"
                                                TextBox(teammate_text, TextStyle(font=DEFAULT_FONT, size=14, color=(125, 125, 125))).set_offset((0, -8-voffset*2))
                                            with Frame().set_content_align('c'):
                                                TextBox(f"{deck.multi_live_score_up:.1f}%", tb_style).set_h(gh).set_content_align('c').set_offset((0, -voffset))

                            # 综合力和算法
                            if recommend_type not in ["bonus", "wl_bonus"]:
                                with VSplit().set_content_align('c').set_item_align('c').set_sep(vsp).set_padding(8):
                                    target_power = options.target == "power"
                                    text = "综合力" + th_main_sign if target_power else "综合力"
                                    style = th_style1 if target_power else th_style2
                                    TextBox(text, style).set_h(gh // 2).set_content_align('c')
                                    Spacer(h=6)
                                    for deck in result_decks:
                                        with Frame().set_content_align('rb'):
                                            if options.multi_live_teammate_power is not None:
                                                teammate_text = f"队友 {int(options.multi_live_teammate_power)}"
                                                TextBox(teammate_text, TextStyle(font=DEFAULT_FONT, size=14, color=(125, 125, 125))).set_offset((0, -8-voffset*2))
                                            with Frame().set_content_align('c'):
                                                TextBox(str(deck.total_power), tb_style).set_h(gh).set_content_align('c').set_offset((0, -voffset))
                    # 找不到结果
                    else:
                        TextBox("未找到符合条件的卡组", TextStyle(font=DEFAULT_BOLD_FONT, size=26, color=(255, 50, 50)))

                # 说明
                with VSplit().set_content_align('lt').set_item_align('lt').set_sep(4):
                    tip_style = TextStyle(font=DEFAULT_FONT, size=16, color=(20, 20, 20))
                    if recommend_type not in ["bonus", "wl_bonus"]:
                        TextBox(f"12星卡默认全满，34星及生日卡默认满级，oc的bfes花前技能活动组卡为平均值，挑战组卡为最大值", tip_style)
                    TextBox(f"功能移植并修改自33Kit https://3-3.dev/sekai/deck-recommend 算错概不负责", tip_style)
                    alg_and_cost_text = "本次组卡使用算法: "
                    for alg, cost in cost_times.items():
                        alg_name = RECOMMEND_ALG_NAMES[alg]
                        cost_time = f"{cost:.2f}s"
                        wait_time = f"{wait_times[alg]:.2f}s"
                        alg_and_cost_text += f"{alg_name} (等待{wait_time}/耗时{cost_time}) + "
                    alg_and_cost_text = alg_and_cost_text[:-3]
                    TextBox(alg_and_cost_text, tip_style)
                    TextBox(f"若发现组卡漏掉最优解可指定固定卡牌再尝试，发送\"{ctx.original_trigger_cmd}help\"获取详细帮助", tip_style)

    add_watermark(canvas)

    with Timer("deckrec:draw", logger):
        return await canvas.get_img()


# ======================= 指令处理 ======================= #

# 活动组卡
pjsk_event_deck = SekaiCmdHandler([
    "/pjsk event card", "/pjsk_event_card", "/pjsk_event_deck", "/pjsk event deck",
    "/活动组卡", "/活动组队", "/活动卡组",
])
pjsk_event_deck.check_cdrate(cd).check_wblist(gbl)
@pjsk_event_deck.handle()
async def _(ctx: SekaiHandlerContext):
    with Timer("deckrec", logger):
        return await ctx.asend_reply_msg(await get_image_cq(
            await compose_deck_recommend_image(
                ctx, ctx.user_id, 
                **(await extract_event_options(ctx, ctx.get_args()))
            ),
            low_quality=True,
        ))


# 挑战组卡
pjsk_challenge_deck = SekaiCmdHandler([
    "/pjsk challenge card", "/pjsk_challenge_card", "/pjsk_challenge_deck", "/pjsk challenge deck",
    "/挑战组卡", "/挑战组队", "/挑战卡组",
])
pjsk_challenge_deck.check_cdrate(cd).check_wblist(gbl)
@pjsk_challenge_deck.handle()
async def _(ctx: SekaiHandlerContext):
    return await ctx.asend_reply_msg(await get_image_cq(
        await compose_deck_recommend_image(
            ctx, ctx.user_id,
            **(await extract_challenge_options(ctx, ctx.get_args()))
        ),
        low_quality=True,
    ))


# 长草组卡
pjsk_no_event_deck = SekaiCmdHandler([
    "/pjsk_no_event_deck", "/pjsk no event deck", "/pjsk best deck", "/pjsk_best_deck",
    "/长草组卡", "/长草组队", "/长草卡组", "/最强卡组", "/最强组卡", "/最强组队",
])
pjsk_no_event_deck.check_cdrate(cd).check_wblist(gbl)
@pjsk_no_event_deck.handle()
async def _(ctx: SekaiHandlerContext):
    return await ctx.asend_reply_msg(await get_image_cq(
        await compose_deck_recommend_image(
            ctx, ctx.user_id,
            **(await extract_no_event_options(ctx, ctx.get_args()))
        ),
        low_quality=True,
    ))


# 指定属性和团名组卡
pjsk_deck = SekaiCmdHandler([
    "/pjsk deck", 
    "/组卡", "/组队", "/指定属性组卡", "/指定属性组队",
])
pjsk_deck.check_cdrate(cd).check_wblist(gbl)
@pjsk_deck.handle()
async def _(ctx: SekaiHandlerContext):
    return await ctx.asend_reply_msg(await get_image_cq(
        await compose_deck_recommend_image(
            ctx, ctx.user_id,
            **(await extract_unit_attr_spec_options(ctx, ctx.get_args()))
        ),
        low_quality=True,
    ))


# 加成组卡
pjsk_bonus_deck = SekaiCmdHandler([
    "/pjsk bonus deck", "/pjsk_bonus_deck", "/pjsk bonus card", "/pjsk_bonus_card",
    "/加成组卡", "/加成组队", "/加成卡组", "/控分组卡", "/控分组队", "/控分卡组",
])
pjsk_bonus_deck.check_cdrate(cd).check_wblist(gbl)
@pjsk_bonus_deck.handle()
async def _(ctx: SekaiHandlerContext):
    return await ctx.asend_reply_msg(await get_image_cq(
        await compose_deck_recommend_image(
            ctx, ctx.user_id,
            **(await extract_bonus_options(ctx, ctx.get_args()))
        ),
        low_quality=True,
    ))


# 实效计算
pjsk_score_up = CmdHandler([
    "/实效", "/pjsk_score_up", "/pjsk score up", "/倍率", "/时效",
], logger)
pjsk_score_up.check_cdrate(cd).check_wblist(gbl)
@pjsk_score_up.handle()
async def _(ctx: SekaiHandlerContext):
    try:
        args = ctx.get_args().strip().split()
        values = list(map(float, args))
        assert len(values) == 5
    except:
        raise ReplyException(f"使用方式: {ctx.trigger_cmd} 100 100 100 100 100") 
    res = values[0] + (values[1] + values[2] + values[3] + values[4]) / 5.
    return await ctx.asend_reply_msg(f"实效: {res:.1f}%")