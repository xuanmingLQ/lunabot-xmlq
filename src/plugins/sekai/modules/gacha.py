from ...utils import *
from ..common import *
from ..handler import *
from ..asset import *
from ..draw import *
from .card import (
    get_card_full_thumbnail,
)


GACHA_LIST_PAGE_SIZE_CFG = config.item('gacha.list_page_size')


@dataclass
class GachaBehavior:
    type: str
    spin_count: int
    cost_type: Optional[int]
    cost_id: Optional[int]
    cost_quantity: Optional[int]
    execute_limit: Optional[int]
    colorful_pass: bool

@dataclass
class GachaCard:
    id: int
    weight: int
    is_wish: bool
    is_pickup: bool

@dataclass
class GachaCardRarityRate:
    rarity: str
    rate: int
    lottery_type: str

@dataclass
class Gacha:
    id: int
    name: str
    type: str
    summary: str
    desc: str
    start_at: datetime
    end_at: datetime
    asset_name: str
    rarity_rates: List[GachaCardRarityRate] = field(default_factory=list)
    behaviors: List[GachaBehavior] = field(default_factory=list)
    cards: List[GachaCard] = field(default_factory=list)

    def __contains__(self, key):
        return key == 'id'
    
    def __getitem__(self, key: str):
        return self.id if key == 'id' else None


@dataclass
class GachaFilter:
    page: Optional[int] = None
    year: Optional[int] = None
    card_id: Optional[int] = None



# ======================= 处理逻辑 ======================= #

@MasterDataManager.map_function("gachas")
def gachas_map_fn(gachas):
    ret: List[Gacha] = []
    for item in gachas:
        g = Gacha(
            id=item['id'],
            name=item['name'],
            type=item['gachaType'],
            summary=item['gachaInformation']['summary'],
            desc=item['gachaInformation']['description'],
            start_at=datetime.fromtimestamp(item['startAt'] / 1000),
            end_at=datetime.fromtimestamp(item['endAt'] / 1000 + 1),
            asset_name=item['assetbundleName'],
        )
        for rate in item['gachaCardRarityRates']:
            g.rarity_rates.append(GachaCardRarityRate(
                rarity=rate['cardRarityType'],
                rate=rate['rate'],
                lottery_type=rate['lotteryType'],
            ))
        for behavior in item['gachaBehaviors']:
            g.behaviors.append(GachaBehavior(
                type=behavior['gachaBehaviorType'],
                spin_count=behavior['spinCount'],
                cost_type=behavior.get('costResourceType'),
                cost_id=behavior.get('costResourceId'),
                cost_quantity=behavior.get('costResourceQuantity'),
                execute_limit=behavior.get('executeLimit'),
                colorful_pass=behavior.get('gachaSpinnableType', None) == "colorful_pass",
            ))
        pickup_ids = set()
        for pickup in item['gachaPickups']:
            pickup_ids.add(pickup['cardId'])
        for card in item['gachaDetails']:
            g.cards.append(GachaCard(
                id=card['cardId'],
                weight=card['weight'],
                is_wish=card.get('isWish', False),
                is_pickup=card['cardId'] in pickup_ids,
            ))
        ret.append(g)
    return ret

async def get_gacha_banner(ctx: SekaiHandlerContext, gacha_or_gacha_id: Union[Gacha, int]) -> Optional[Image.Image]:
    if isinstance(gacha_or_gacha_id, Gacha):
        gacha_id = gacha_or_gacha_id.id
    else:
        gacha_id = gacha_or_gacha_id
    banner_path = f'home/banner/banner_gacha{gacha_id}/banner_gacha{gacha_id}.png'
    return await ctx.rip.img(banner_path, use_img_cache=True)

async def get_gacha_logo(ctx: SekaiHandlerContext, gacha_or_gacha_id: Union[Gacha, int]) -> Optional[Image.Image]:
    if isinstance(gacha_or_gacha_id, Gacha):
        gacha = gacha_or_gacha_id
    else:
        gacha = await ctx.md.gachas.find_by_id(gacha_or_gacha_id)
        assert_and_reply(gacha, f"找不到卡池{ctx.region.upper()}-{gacha_or_gacha_id}")
    return await ctx.rip.img(f"gacha/{gacha.asset_name}/logo/logo.png", use_img_cache=True)

# 解析查单个卡池指令参数
async def parse_search_gacha_args(ctx: SekaiHandlerContext, args: str) -> Optional[Gacha]:
    if not args:
        return None
    index = None
    try:
        index = int(args)
    except ValueError:
        pass
    if index is not None:
        if index >= 0:
            gacha = await ctx.md.gachas.find_by_id(index)
            assert_and_reply(gacha, f"找不到卡池{ctx.region.upper()}-{index}")
            return gacha
        else:
            index = -index
            gachas = [
                g for g in sorted(await ctx.md.gachas.get(), key=lambda g: g.start_at, reverse=True)
                if datetime.now() >= g.start_at
            ]
            assert_and_reply(index <= len(gachas), f"找不到最近的第{index}个卡池")
            return gachas[index - 1]
    return None

# 解析查多个卡池指令参数
async def parse_search_multiple_gacha_args(ctx: SekaiHandlerContext, args: str) -> Tuple[GachaFilter, str]:
    year, args = extract_year(args)

    card_id = None
    match = re.match(r'card(\d+)', args)
    if match:
        card_id = int(match.group(1))
        args = args.replace(match.group(0), '').strip()

    page = None
    match = re.match(r'p(\d+)', args)
    if match:
        page = int(match.group(1))
        args = args.replace(match.group(0), '').strip()
    match = re.match(r'(\d+)页', args)
    if match:
        page = int(match.group(1))
        args = args.replace(match.group(0), '').strip()

    return GachaFilter(
        page=page,
        year=year,
        card_id=card_id,
    ), args.strip()
    
# 合成卡池一览图片
async def compose_gacha_list_image(ctx: SekaiHandlerContext, filter: GachaFilter = None):
    filter = filter or GachaFilter()
    gachas: List[Gacha] = []
    for gacha in await ctx.md.gachas.get():
        g: Gacha = gacha
        if filter.card_id and not find_by_predicate(g.cards, lambda c: c.id == filter.card_id):
            continue
        if filter.year and g.start_at.year != filter.year:
            continue
        gachas.append(g)
    assert_and_reply(gachas, "找到没有符合条件的卡池")
    gachas.sort(key=lambda g: g.start_at)

    page_size = GACHA_LIST_PAGE_SIZE_CFG.get()
    total_pages = math.ceil(len(gachas) / page_size)
    page = max(1, min(filter.page, total_pages)) if filter.page is not None else total_pages
    start_index = (page - 1) * page_size
    gachas = gachas[start_index:start_index+page_size]
    logos = await batch_gather(*[get_gacha_logo(ctx, g) for g in gachas])

    row_count = math.ceil(math.sqrt(len(gachas)))
    style1 = TextStyle(font=DEFAULT_HEAVY_FONT, size=10, color=(50, 50, 50))
    style2 = TextStyle(font=DEFAULT_FONT,       size=10, color=(70, 70, 70))

    with Canvas(bg=SEKAI_BLUE_BG).set_padding(BG_PADDING) as canvas:
        TextBox(f"卡池按时间顺序排列，黄色为开放中卡池，第 {page}/{total_pages} 页", TextStyle(font=DEFAULT_FONT, size=10, color=(0, 0, 100))) \
            .set_offset((0, 4 - BG_PADDING))
        with Grid(row_count=row_count, vertical=True).set_sep(8, 2).set_item_align('c').set_content_align('c'):
            for g, logo in zip(gachas, logos):
                now = datetime.now()
                bg_color = WIDGET_BG_COLOR
                if g.start_at <= now <= g.end_at:
                    bg_color = (255, 250, 220, 200)
                elif now > g.end_at:
                    bg_color = (220, 220, 220, 200)
                bg = roundrect_bg(bg_color, 5)
                with HSplit().set_padding(4).set_sep(4).set_item_align('lt').set_content_align('lt').set_bg(bg):
                    with VSplit().set_padding(0).set_sep(2).set_item_align('lt').set_content_align('lt'):
                        ImageBox(logo, size=(None, 60))
                        TextBox(f"【{g.id}】{g.name}", style1, line_count=2, use_real_line_count=False).set_w(130)
                        TextBox(f"S {g.start_at.strftime('%Y-%m-%d %H:%M')}", style2)
                        TextBox(f"T {g.end_at.strftime('%Y-%m-%d %H:%M')}", style2)

    add_watermark(canvas)
    return await canvas.get_img()


# ======================= 指令处理 ======================= #
        
# 查活动
pjsk_gacha = SekaiCmdHandler([
    "/pjsk gacha", "/卡池列表", "/卡池一览", "/卡池", "/查卡池", 
])
pjsk_gacha.check_cdrate(cd).check_wblist(gbl)
@pjsk_gacha.handle()
async def _(ctx: SekaiHandlerContext):
    args = ctx.get_args().strip()
    
    # 查单卡池
    gacha = await parse_search_gacha_args(ctx, args)
    if gacha:
        raise NotImplementedError("单卡池查询功能尚未实现")
    
    # 查多个卡池
    filter, args = await parse_search_multiple_gacha_args(ctx, args)
    assert_and_reply(not args, f"""
查卡池参数错误
单个卡池参数: 使用卡池编号，或负数表示最近卡池
多个卡池参数:
去年/25年: 查指定年份的卡池
card123: 查包含指定卡牌123的卡池
p2: 查第二页卡池
""".strip())

    return await ctx.asend_reply_msg(await get_image_cq(
        await compose_gacha_list_image(ctx, filter),
        low_quality=True,
    ))
