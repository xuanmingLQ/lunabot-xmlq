from .utils import *
from .master import MasterDataManager
from .gameapi import get_gameapi_config, request_gameapi, close_session
from .sql import insert_rankings, Ranking
from tenacity import retry, wait_fixed, stop_after_attempt
from src.utils.data import get_data_path


set_log_level('INFO')

ALL_SERVER_REGIONS = ['jp', 'cn', 'tw', 'kr', 'en']

RECORD_TIME_AFTER_EVENT_END_CFG = config.item('sk.record_time_after_event_end_minutes')
SK_RECORD_INTERVAL_CFG = config.item('sk.record_interval_seconds')

mds = MasterDataManager(get_data_path('sekai/assets/masterdata'))

latest_rankings_cache: dict[str, dict[int, dict[int, Ranking]]] = {}


# ================================ 处理逻辑 ================================ #

def get_wl_chapter_cid(region: str, wl_id: int) -> Optional[int]:
    """获取wl_id对应的角色cid，wl_id对应普通活动则返回None"""
    event_id = wl_id % 1000
    chapter_id = wl_id // 1000
    if chapter_id == 0:
        return None
    chapters = mds.get(region, 'worldBlooms').find_by('eventId', event_id, mode='all')
    assert chapters, f"活动{region}-{event_id}并不是WorldLink活动"
    chapter = find_by(chapters, "chapterNo", chapter_id)
    assert chapter, f"活动{region}-{event_id}并没有章节{chapter_id}"
    cid = chapter.get('gameCharacterId', None)
    return cid

def get_current_event(region: str, fallback: Optional[str] = None) -> dict:
    """
    获取当前活动 当前无进行中活动时 fallback = None:返回None prev:选择上一个 next:选择下一个 prev_first:优先选择上一个 next_first: 优先选择下一个
    """
    assert fallback is None or fallback in ("prev", "next", "prev_first", "next_first")
    events = sorted(mds.get(region, 'events').get(), key=lambda x: x['aggregateAt'], reverse=False)
    now = datetime.now()
    prev_event, cur_event, next_event = None, None, None
    for event in events:
        start_time = datetime.fromtimestamp(event['startAt'] / 1000)
        end_time = datetime.fromtimestamp(event['aggregateAt'] / 1000 + 1)
        if start_time <= now <= end_time:
            cur_event = event
        if end_time < now:
            prev_event = event
        if not next_event and start_time > now:
            next_event = event
    if fallback is None or cur_event:
        return cur_event
    if fallback == "prev" or (fallback == "prev_first" and prev_event):
        return prev_event
    if fallback == "next" or (fallback == "next_first" and next_event):
        return next_event
    return prev_event or next_event

def parse_rankings(region: str, event_id: int, data: dict) -> list[Ranking]:
    """从榜线数据解析Rankings"""
    data_top100 = data.get('top100', {})
    data_border = data.get('border', {})
    assert data_top100, "获取榜线Top100数据失败"
    assert data_border, "获取榜线Border数据失败"

    now = datetime.now()

    # 普通活动
    if event_id < 1000:
        top100 = [Ranking.from_sk(item, now) for item in data_top100['rankings']]
        border = [Ranking.from_sk(item, now) for item in data_border['borderRankings'] if item['rank'] != 100]
    
    # WL活动
    else:
        cid = get_wl_chapter_cid(region, event_id)
        top100_rankings = find_by(data_top100.get('userWorldBloomChapterRankings', []), 'gameCharacterId', cid)
        top100 = [Ranking.from_sk(item, now) for item in top100_rankings['rankings']]
        border_rankings = find_by(data_border.get('userWorldBloomChapterRankingBorders', []), 'gameCharacterId', cid)
        border = [Ranking.from_sk(item, now) for item in border_rankings['borderRankings'] if item['rank'] != 100]

    for item in top100:
        item.uid = str(item.uid)
    for item in border:
        item.uid = str(item.uid)
    
    return top100 + border

def get_wl_events(region: str, event_id: int) -> list[dict]:
    """获取event_id对应的所有wl_event（时间顺序），如果不是wl则返回空列表"""
    event = mds.get(region, 'events').find_by_id(event_id)
    chapters = mds.get(region, 'worldBlooms').find_by('eventId', event['id'], mode='all')
    if not chapters:
        return []
    wl_events = []
    for chapter in chapters:
        wl_event = event.copy()
        wl_event['id'] = chapter['chapterNo'] * 1000 + event['id']
        wl_event['startAt'] = chapter['chapterStartAt']
        wl_event['aggregateAt'] = chapter['aggregateAt']
        wl_event['wl_cid'] = chapter.get('gameCharacterId', None)
        wl_events.append(wl_event)
    return sorted(wl_events, key=lambda x: x['startAt'])


# ================================ 榜线更新 ================================ #

class EventTracker:
    def __init__(self, region: str):
        self.region = region


    def info(self, *args, **kwargs):
        info(f"[{self.region.upper()}]", *args, **kwargs)

    def warning(self, *args, **kwargs):
        warning(f"[{self.region.upper()}]", *args, **kwargs)

    def error(self, *args, **kwargs):
        error(f"[{self.region.upper()}]", *args, **kwargs)
    
    def debug(self, *args, **kwargs):
        debug(f"[{self.region.upper()}]", *args, **kwargs)


    @retry(wait=wait_fixed(3), stop=stop_after_attempt(3), reraise=True)
    async def request_rankings(self, eid: int, url: str) -> Optional[dict]:
        """
        请求榜线数据
        """
        try:
            t = datetime.now().timestamp()
            data = await request_gameapi(url.format(event_id=eid))
            self.info(f"请求 {eid} 榜线数据成功, 耗时 {(datetime.now().timestamp() - t):.2f}s")
            return data
        except Exception:
            self.error(f"请求榜线数据失败")
            return None
        

    async def update_rankings(self, eid: int, data: dict) -> bool:
        """
        更新总榜或WL单榜，返回是否更新成功
        """
        region = self.region
        try:
            # 插入数据库
            rankings = parse_rankings(region, eid, data)

            # 和缓存进行比对并更新缓存，仅插入有更新的榜线（玩家和分数都没有变化则不插入）
            if region not in latest_rankings_cache:
                latest_rankings_cache[region] = {}
            if eid not in latest_rankings_cache[region]:
                latest_rankings_cache[region][eid] = {}

            rankings_to_insert: list[Ranking] = []
            for item in rankings:
                last_item = latest_rankings_cache[region][eid].get(item.rank, None)
                if not last_item or last_item.score != item.score or last_item.uid != item.uid:
                    latest_rankings_cache[region][eid][item.rank] = item
                    rankings_to_insert.append(item)

            # 插入数据库
            if rankings_to_insert:
                await insert_rankings(region, eid, rankings_to_insert)

            self.info(f"插入 {eid} 榜线数据成功，新记录数: {len(rankings)}")
            return True

        except Exception as e:
            self.error(f"插入 {eid} 榜线数据失败: {get_exc_desc(e)}")
            return False


    async def update_region_ranking_task(self):
        """更新一次指定服务器的榜线数据"""
        region = self.region
        url = get_gameapi_config(region).ranking_api_url
        if not url:
            return
            
        # 获取当前运行中的活动
        try:
            if not (event := get_current_event(region, fallback="prev")):
                self.info(f"当前无进行中或已结束活动，跳过榜线更新")
                return
            if datetime.now() > datetime.fromtimestamp(event['aggregateAt'] / 1000 + RECORD_TIME_AFTER_EVENT_END_CFG.get() * 60):
                self.info(f"当前活动 {event['id']} 已过榜线记录时间，跳过榜线更新")
                return
        except Exception as e:
            self.warning(f"检查当前活动时失败: {get_exc_desc(e)}")
            return

        # 清空并非当前活动的缓存榜线数据
        event_id = event['id']
        for key in list(latest_rankings_cache.get(region, {}).keys()):
            if key % 1000 != event_id:
                latest_rankings_cache[region].pop(key)
                self.info(f"清除非当前活动 {key} 的榜线缓存数据")

        data = await self.request_rankings(event_id, url)

        if not data:
            return

        tasks = []
        # 总榜
        tasks.append(self.update_rankings(event_id, data))
        # WL单榜
        wl_events = get_wl_events(region, event_id)
        if wl_events and len(wl_events) > 1:
            for wl_event in wl_events:
                if datetime.now() > datetime.fromtimestamp(wl_event['aggregateAt'] / 1000 + RECORD_TIME_AFTER_EVENT_END_CFG.get() * 60):
                    continue
                tasks.append(self.update_rankings(wl_event['id'], data))

        if not tasks: return
        await asyncio.gather(*tasks)


    async def start_track(self):
        self.info(f"榜线更新任务已启动")
        next_record_time = datetime.now()
        while True:
            try:
                while datetime.now() < next_record_time:
                    await asyncio.sleep(0.5)
                start = datetime.now()
                self.info(f"启动榜线更新...")
                await self.update_region_ranking_task()
                now = datetime.now()
                next_record_time = start + timedelta(seconds=get_cfg_or_value(SK_RECORD_INTERVAL_CFG))
                self.info(f"完成榜线更新 ({(now - start).total_seconds():.2f}s, next: {next_record_time.strftime('%Y-%m-%d %H:%M:%S')})")
            except asyncio.CancelledError:
                break
        await close_session()



async def main():
    trackers = { region: EventTracker(region) for region in ALL_SERVER_REGIONS }
    tasks = []
    for region in ALL_SERVER_REGIONS:
        tasks.append(trackers[region].start_track())
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    print("\nStarting Event Tracker...")
    asyncio.run(main())