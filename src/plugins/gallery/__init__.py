from ..utils import *
from enum import Enum
import zipfile


config = Config('gallery')
logger = get_logger('Gallery')
file_db = get_file_db('data/gallery/gallery.json', logger)
cd = ColdDown(file_db, logger)
gbl = get_group_black_list(file_db, logger, 'gallery')

THUMBNAIL_SIZE = (64, 64)
SIZE_LIMIT_MB_CFG = config.item('size_limit_mb')
PHASH_DIFFERENCE_THRESHOLD_CFG = config.item('phash_difference_threshold')
GALLERY_PICS_DIR = 'data/gallery/{name}/'
PIC_EXTS = ['.jpg', '.jpeg', '.png', '.gif']
ADD_LOG_FILE = 'data/gallery/add.log'

# ======================= 逻辑处理 ======================= # 

class GalleryMode(Enum):
    Edit = 'edit'
    View = 'view'
    Off = 'off'


@dataclass
class GalleryPic:
    gall_name: str
    pid: int
    path: str
    phash: str
    thumb_path: str | None = None

    def ensure_thumb(self):
        try:
            if self.thumb_path is None:
                name = os.path.basename(self.path)
                self.thumb_path = os.path.join(os.path.dirname(self.path), f"{name}_thumb.jpg")
            if not os.path.exists(self.thumb_path):
                img = Image.open(self.path).convert('RGB')
                img.thumbnail(THUMBNAIL_SIZE)
                img.save(self.thumb_path, format='JPEG', optimize=True, quality=85)
        except Exception as e:
            logger.warning(f'生成画廊图片 {self.pid} 缩略图失败: {e}')
            self.thumb_path = None


class GalleryPicRepeatedException(Exception):
    def __init__(self, pid: int):
        super().__init__(f'画廊中已存在相似图片(pid={pid})')
        self.pid = pid


@dataclass
class Gallery:
    name: str
    aliases: list[str]
    mode: GalleryMode
    pics_dir: str
    cover_pid: int | None = None
    pics: list[GalleryPic] = field(default_factory=list)


class GalleryManager:
    _mgr: 'GalleryManager' = None

    def __init__(self):
        self.pid_top = 0
        self.galleries: dict[str, Gallery] = {}

    def _load(self):
        self.pid_top = file_db.get('pid_top', 0)
        self.galleries = {}
        for name, g in file_db.get('galleries', {}).items():
            pics = [GalleryPic(**p) for p in g.get('pics', [])]
            self.galleries[name] = Gallery(
                name=g['name'],
                aliases=g.get('aliases', []),
                cover_pid=g.get('cover_pid', None),
                mode=GalleryMode(g.get('mode', 'edit')),
                pics_dir=g['pics_dir'],
                pics=pics,
            )
        logger.info(f'成功加载{len(self.galleries)}个画廊, pid_top={self.pid_top}')

    def _save(self):
        file_db.set('pid_top', self.pid_top)
        file_db.set('galleries', { name: asdict(g) for name, g in self.galleries.items() })
        file_db.save()

    def _check_name(self, name: str) -> bool:
        if not name or len(name) > 32:
            return False
        if any(c in name for c in r'\/:*?"<>| '):
            return False
        if name.isdigit():
            return False
        return True

    async def _calc_hash(self, path: str):
        image = Image.open(path)
        def calc(image):
            # 如果存在A通道：alphablend到纯白色背景上
            if image.mode in ('RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info):
                image = image.convert('RGBA').resize((64, 64), Image.Resampling.BILINEAR)
                bg = Image.new("RGBA", image.size, (255, 255, 255, 255))
                bg.alpha_composite(image)
                image = bg
            image = image.convert('RGB')
            # 缩小尺寸并转为灰度图
            image = image.resize((16, 16), Image.Resampling.BILINEAR).convert('L')
            # 转为base64字符串
            return image.tobytes().hex()
        return await run_in_pool(calc, image)

    async def _is_sim_hash(self, phash1: str, phash2: str, threshold: int) -> bool:
        def calc():
            img1 = np.frombuffer(bytes.fromhex(phash1), dtype=np.uint8)
            img2 = np.frombuffer(bytes.fromhex(phash2), dtype=np.uint8)
            diff = np.sum(np.abs(img1.astype(np.int16) - img2.astype(np.int16)))
            return diff <= threshold
        return await run_in_pool(calc)
    
    async def _check_duplicated(self, phash: str, gallery: Gallery) -> int | None:
        for p in gallery.pics:
            if await self._is_sim_hash(phash, p.phash, PHASH_DIFFERENCE_THRESHOLD_CFG.get()):
                return p.pid
        return None

    

    @classmethod
    def get(cls) -> 'GalleryManager':
        if cls._mgr is None:
            cls._mgr = GalleryManager()
            cls._mgr._load()
        return cls._mgr


    def get_all_galls(self) -> dict[str, Gallery]:
        """
        获取所有画廊
        """
        return self.galleries

    def find_gall(self, name_or_alias: str, raise_if_nofound: bool = False) -> Gallery | None:
        """
        通过名称或别名查找画廊
        """
        for g in self.galleries.values():
            if g.name == name_or_alias or name_or_alias in g.aliases:
                return g
        if raise_if_nofound:
            if not name_or_alias:
                raise ReplyException('画廊名称不能为空')
            raise ReplyException(f'画廊\"{name_or_alias}\"不存在')
        return None

    def open_gall(self, name: str):
        """
        创建一个新画廊
        """
        assert self._check_name(name), f'画廊名称\"{name}\"无效'
        assert self.find_gall(name) is None, f'画廊\"{name}\"已存在'
        gall = Gallery(
            name=name,
            aliases=[],
            mode=GalleryMode.Edit,
            pics_dir=GALLERY_PICS_DIR.format(name=name),
            pics=[],
        )
        self.galleries[name] = gall
        self._save()

    def close_gall(self, name_or_alias: str):
        """
        删除一个画廊
        """
        g = self.find_gall(name_or_alias)
        assert g is not None, f'画廊\"{name_or_alias}\"不存在'
        self.galleries.pop(g.name)
        self._save()

    def add_gall_alias(self, name_or_alias: str, alias: str):
        """
        为画廊添加一个别名
        """
        assert self._check_name(alias), f'别名\"{alias}\"无效'
        g = self.find_gall(name_or_alias)
        assert g is not None, f'画廊\"{name_or_alias}\"不存在'
        assert self.find_gall(alias) is None, f'别名\"{alias}\"已被占用'
        g.aliases.append(alias)
        self._save()

    def del_gall_alias(self, name_or_alias: str, alias: str):
        """
        删除画廊的一个别名
        """
        g = self.find_gall(name_or_alias)
        assert g is not None, f'画廊\"{name_or_alias}\"不存在'
        assert alias in g.aliases, f'别名\"{alias}\"不存在'
        g.aliases.remove(alias)
        self._save()

    def change_gall_mode(self, name_or_alias: str, mode: GalleryMode) -> tuple[GalleryMode, GalleryMode]:
        """
        修改画廊的模式，返回(旧模式, 新模式)
        """
        g = self.find_gall(name_or_alias)
        assert g is not None, f'画廊\"{name_or_alias}\"不存在'
        old_mode = g.mode
        g.mode = mode
        self._save()
        return old_mode, g.mode

    def find_pic(self, pid: int, raise_if_nofound: bool = False) -> GalleryPic | None:
        """
        通过图片ID查找图片
        """
        if pid < 0:
            pids = []
            for g in self.galleries.values():
                for p in g.pics:
                    pids.append(p.pid)
            pids.sort()
            if pid < -len(pids):
                if raise_if_nofound:
                    raise ReplyException(f'画廊仅有{len(pids)}张图片')
                return None
            pid = pids[pid]
        for g in self.galleries.values():
            for p in g.pics:
                if p.pid == pid:
                    return p
        if raise_if_nofound:
            raise ReplyException(f'画廊图片pid={pid}不存在')
        return None

    async def async_add_pic(self, name_or_alias: str, img_path: str, check_duplicated: bool = True) -> int:
        """
        向画廊添加一张图片，将会直接拷贝img_path的图片，返回图片ID
        """
        g = self.find_gall(name_or_alias)
        assert g is not None, f'画廊\"{name_or_alias}\"不存在'
    
        phash = await self._calc_hash(img_path)
        if check_duplicated:
            if sim_pid := await self._check_duplicated(phash, g):
                raise GalleryPicRepeatedException(sim_pid)

        self.pid_top += 1
        _, ext = os.path.splitext(os.path.basename(img_path))
        time_str = datetime.now().strftime('%Y-%m-%d_%H-%M%-S')
        dst_path = create_parent_folder(os.path.join(g.pics_dir, f"{time_str}_{self.pid_top}{ext}"))
        shutil.copy2(img_path, dst_path)

        pic = GalleryPic(
            gall_name=g.name, 
            pid=self.pid_top, 
            path=dst_path, 
            phash=phash,
        )
        g.pics.append(pic)
        pic.ensure_thumb()

        self._save()
        return self.pid_top

    async def async_replace_pic(self, pid: int, img_path: str, check_duplicated: bool = True) -> int:
        """
        替换画廊中的一张图片，返回图片ID
        """
        p = self.find_pic(pid)
        assert p is not None, f'图片ID {pid} 不存在'
        g = self.find_gall(p.gall_name)
        assert g is not None, f'图片ID {pid} 所属画廊\"{p.gall_name}\"不存在'

        phash = await self._calc_hash(img_path)
        if check_duplicated:
            if sim_pid := await self._check_duplicated(phash, g):
                if sim_pid != pid:
                    raise GalleryPicRepeatedException(sim_pid)

        # 删除旧文件
        try:
            if os.path.exists(p.path):
                os.remove(p.path)
            if p.thumb_path and os.path.exists(p.thumb_path):
                os.remove(p.thumb_path)
        except Exception as e:
            logger.warning(f'删除画廊图片 {pid} 文件失败: {get_exc_desc(e)}')

        # 复制新文件
        _, ext = os.path.splitext(os.path.basename(img_path))
        time_str = datetime.now().strftime('%Y-%m-%d_%H-%M%-S')
        dst_path = create_parent_folder(os.path.join(g.pics_dir, f"{time_str}_{p.pid}{ext}"))
        shutil.copy2(img_path, dst_path)

        # 更新信息
        p.path = dst_path
        p.phash = phash
        p.thumb_path = None
        p.ensure_thumb()

        self._save()
        return p.pid

    def del_pic(self, pid: int) -> int:
        """
        从画廊删除一张图片，返回被删除的图片ID
        """
        p = self.find_pic(pid)
        assert p is not None, f'图片ID {pid} 不存在'
        g = self.find_gall(p.gall_name)
        g.pics.remove(p)
        try:
            if os.path.exists(p.path):
                os.remove(p.path)
            if p.thumb_path and os.path.exists(p.thumb_path):
                os.remove(p.thumb_path)
        except Exception as e:
            logger.warning(f'删除画廊图片 {pid} 文件失败: {get_exc_desc(e)}')
        self._save()
        return p.pid

    async def async_reload_gall(self, name_or_alias: str) -> tuple[list[int], list[int]]:
        """
        从画廊的图片目录重新加载图片，返回[新加载的图片pids, 失效的图片pids]
        """
        g = self.find_gall(name_or_alias)
        assert g is not None, f'画廊\"{name_or_alias}\"不存在'
        new_pids, del_pids = [], []
        # 检查新增的图片
        for file in glob.glob(os.path.join(g.pics_dir, '*')):
            if '_thumb' in file:
                continue
            for p in g.pics:
                if os.path.abspath(p.path) == os.path.abspath(file):
                    continue
            phash = await self._calc_hash(file)

            _, ext = os.path.splitext(os.path.basename(file))
            if ext.lower() in PIC_EXTS:
                self.pid_top += 1
                pic = GalleryPic(
                    gall_name=g.name, 
                    pid=self.pid_top, 
                    path=file,
                    phash=phash,
                )
                g.pics.append(pic)
                new_pids.append(pic.pid)
        # 检查失效的图片
        for pic in g.pics[:]:
            if not os.path.exists(pic.path):
                g.pics.remove(pic)
                del_pids.append(pic.pid)
        self._save()
        return new_pids, del_pids
    
    def set_cover_pic(self, name_or_alias: str, pid: int):
        """
        设置画廊封面图片
        """
        g = self.find_gall(name_or_alias)
        assert g is not None, f'画廊\"{name_or_alias}\"不存在'
        p = self.find_pic(pid)
        assert p is not None and p.gall_name == g.name, f'图片pid={pid}不属于画廊\"{g.name}\"'
        g.cover_pid = pid
        self._save()

    async def async_check_gallery(self, name_or_alias: str, rehash: bool) -> dict[int, list[int]]:
        """
        重新检查画廊重复图片，返回一个字典，key为首个图片id，value为重复图片id列表
        """
        g = self.find_gall(name_or_alias)
        assert g is not None, f'画廊\"{name_or_alias}\"不存在'
        
        ret: dict[int, tuple[str, list[int]]] = {}

        for pic in g.pics[:]:
            if rehash:
                phash = await self._calc_hash(pic.path)
                pic.phash = phash
            else:
                phash = pic.phash

            sim_pid = None
            for k, v in ret.items():
                phash2 = v[0]
                if await self._is_sim_hash(phash, phash2, PHASH_DIFFERENCE_THRESHOLD_CFG.get()):
                    sim_pid = k
                    break

            if sim_pid is not None:
                ret[sim_pid][1].append(pic.pid)
            else:
                ret[pic.pid] = (phash, [])

        if rehash:
            self._save()
        ret = { k : v[1] for k, v in ret.items() if v[1] }
        return ret


# 处理本地文件用于添加到画廊
def process_image_for_gallery(path: str, sub_type: int):
    img = open_image(path)
    # 如果是表情并且是静态图，可能获取到jpg，需要手动转换为静态gif
    need_to_gif = (sub_type and not is_animated(img))

    # 根据限制进行缩放
    scaled = False
    size_limit = SIZE_LIMIT_MB_CFG.get()
    filesize_mb = os.path.getsize(path) / (1024 * 1024)
    if filesize_mb > size_limit:
        pixels = get_image_pixels(img)
        img = limit_image_by_pixels(img, int(pixels * size_limit / filesize_mb))
        scaled = True

    if need_to_gif:
        # 转换为静态gif
        save_transparent_static_gif(img, path)
    elif scaled:
        if is_animated(img):
            save_transparent_gif(img, get_gif_duration(img), path)
        else:
            img.save(path)
        new_size_mb = os.path.getsize(path) / (1024 * 1024)
        logger.info(f"缩放过大的图片 {filesize_mb:.2f}M -> {new_size_mb:.2f}M")


# ======================= 指令处理 ======================= # 

gall_open = CmdHandler([
    '/gall open',
], logger)
gall_open.check_cdrate(cd).check_wblist(gbl).check_superuser()
@gall_open.handle()
async def _(ctx: HandlerContext):
    name = ctx.get_args().strip()
    GalleryManager.get().open_gall(name)
    await ctx.asend_reply_msg(f'画廊\"{name}\"创建成功')


gall_close = CmdHandler([
    '/gall close',
], logger)
gall_close.check_cdrate(cd).check_wblist(gbl).check_superuser()
@gall_close.handle()
async def _(ctx: HandlerContext):
    name = ctx.get_args().strip()
    GalleryManager.get().close_gall(name)
    await ctx.asend_reply_msg(f'画廊\"{name}\"删除成功')


gall_mode = CmdHandler([
    '/gall mode',
], logger)
gall_mode.check_cdrate(cd).check_wblist(gbl).check_superuser()
@gall_mode.handle()
async def _(ctx: HandlerContext):
    args = ctx.get_args().strip().split()
    if len(args) == 1:
        mode = GalleryManager.get().find_gall(args[0], raise_if_nofound=True).mode.value
        return await ctx.asend_reply_msg(f'画廊\"{args[0]}\"当前模式: {mode}')
    if len(args) > 2:
        raise ReplyException('使用方式: /gall mode 画廊名称 模式(edit/view/off)')
    name, mode = args
    old, new = GalleryManager.get().change_gall_mode(name, GalleryMode(mode))
    await ctx.asend_reply_msg(f'画廊\"{name}\"模式修改成功: {old.value} -> {new.value}')


gall_del = CmdHandler([
    '/gall del', '/gall remove',
], logger)
gall_del.check_cdrate(cd).check_wblist(gbl).check_superuser()
@gall_del.handle()
async def _(ctx: HandlerContext):
    try:
        pids = [int(s) for s in ctx.get_args().strip().split()]
    except:
        raise ReplyException('使用方式: /gall del ID1 ID2...')
    pids = [GalleryManager.get().del_pic(p) for p in pids]
    await ctx.asend_reply_msg(f'图片pid={",".join(str(p) for p in pids)}删除成功')


gall_reload = CmdHandler([
    '/gall reload', '/gall update',
], logger)
gall_reload.check_cdrate(cd).check_wblist(gbl).check_superuser()
@gall_reload.handle()
async def _(ctx: HandlerContext):
    name = ctx.get_args().strip()
    new_pids, del_pids = await GalleryManager.get().async_reload_gall(name)
    msg = f'画廊\"{name}\"重新加载完成\n新增图片: {len(new_pids)}张\n失效图片: {len(del_pids)}张'
    await ctx.asend_reply_msg(msg)


gall_alias_add = CmdHandler([
    '/gall alias add', '/gall add alias',
], logger, priority=200)
gall_alias_add.check_cdrate(cd).check_wblist(gbl).check_superuser()
@gall_alias_add.handle()
async def _(ctx: HandlerContext):
    args = ctx.get_args().strip().split()
    if len(args) != 2:
        raise ReplyException('使用方式: /gall alias add 画廊名称 别名')
    name, alias = args
    GalleryManager.get().add_gall_alias(name, alias)
    await ctx.asend_reply_msg(f'画廊\"{name}\"添加别名\"{alias}\"成功')


gall_alias_del = CmdHandler([
    '/gall alias del', '/gall alias remove', '/gall del alias', '/gall remove alias',
], logger)
gall_alias_del.check_cdrate(cd).check_wblist(gbl).check_superuser()
@gall_alias_del.handle()
async def _(ctx: HandlerContext):
    args = ctx.get_args().strip().split()
    if len(args) != 2:
        raise ReplyException('使用方式: /gall alias del 画廊名称 别名')
    name, alias = args
    GalleryManager.get().del_gall_alias(name, alias)
    await ctx.asend_reply_msg(f'画廊\"{name}\"删除别名\"{alias}\"成功')


gall_pick = CmdHandler([
    '/gall pick', '/看',
], logger)
gall_pick.check_cdrate(cd).check_wblist(gbl)
@gall_pick.handle()
async def _(ctx: HandlerContext):
    limit = config.get('pick_limit')
    HELP = """
使用方式: 
/看 画廊名称 
/看 画廊名称 x2
/看 pid1 pid2...
""".strip()

    args = ctx.get_args().strip()
    if not args:
        raise ReplyException(HELP)

    pics, names = None, None
    try: 
        pids = [int(x) for x in args.split()]
        pics = [GalleryManager.get().find_pic(pid, raise_if_nofound=True) for pid in pids]
        names = [pic.gall_name for pic in pics]
    except: 
        pics = None
        num = 1
        if 'x' in args:
            args, num_str = args.rsplit('x', 1)
            try: num = int(num_str)
            except: raise ReplyException(HELP)
            assert_and_reply(1 <= num <= limit, f'一次查看图片数量必须在1到{limit}之间')
        names = [args.strip()]

    for name in names:
        g = GalleryManager.get().find_gall(name, raise_if_nofound=True)
        is_super = check_superuser(ctx.event)
        if not is_super and g.mode == GalleryMode.Off:
            raise ReplyException(f'画廊\"{name}\"已关闭')

    if pics is None:
        if not g.pics:
            raise ReplyException(f'画廊\"{name}\"没有图片')
        pics = [random.choice(g.pics) for _ in range(num)]

    if len(pics) > limit:
        raise ReplyException(f'一次最多查看{limit}张图片')

    await ctx.asend_msg(''.join([await get_image_cq(p.path, send_local_file_as_is=True) for p in pics]))


gall_add = CmdHandler([
    '/gall add', '/gall upload', '/上传', '/添加',
], logger)
gall_add.check_cdrate(cd).check_wblist(gbl)
@gall_add.handle()
async def _(ctx: HandlerContext):
    args = ctx.get_args().strip()

    check_duplicated = True
    if 'force' in args:
        check_duplicated = False
        args = args.replace('force', '').strip()

    name = args
    g = GalleryManager.get().find_gall(name, raise_if_nofound=True)

    is_super = check_superuser(ctx.event)
    if not is_super and g.mode != GalleryMode.Edit:
        raise ReplyException(f'画廊\"{name}\"不允许上传图片')

    await ctx.block(name)
    
    image_datas = await ctx.aget_image_datas()
    ok_list, err_msg = [], ""
    repeats: list[tuple[Image.Image, int]] = []
    REPEAT_IMAGE_SHOW_SIZE = (128, 128)
    for i, data in enumerate(image_datas, 1):
        async with TempDownloadFilePath(data['url'], 'gif') as path:
            try:
                await run_in_pool(process_image_for_gallery, path, data.get('sub_type', 1))
                pid = await GalleryManager.get().async_add_pic(name, path, check_duplicated=check_duplicated)
                ok_list.append(pid)
                with open(ADD_LOG_FILE, 'a', encoding='utf-8') as f:
                    f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | @{ctx.event.user_id} upload pid={pid} to \"{name}\"\n")
            except GalleryPicRepeatedException as e:
                img = open_image(path)
                img.thumbnail(REPEAT_IMAGE_SHOW_SIZE)
                repeats.append((img, e.pid))
            except Exception as e:
                logger.print_exc(f"上传第{i}张图片到画廊\"{name}\"失败")
                err_msg += f"上传第{i}张图片失败: {get_exc_desc(e)}\n"

    repeat_img = None
    if repeats:
        with Canvas(bg=FillBg((230, 240, 255, 255))).set_padding(8) as canvas:
            with VSplit().set_padding(0).set_sep(16).set_item_align('lt').set_content_align('lt'):
                TextBox(f"查重错误可使用\"/上传 force\"强制上传图片", TextStyle(DEFAULT_FONT, 16, BLACK))
                with Grid(row_count=int(math.sqrt(len(repeats) * 2)), hsep=8, vsep=8).set_item_align('t').set_content_align('t'):
                    for img, pid in repeats:
                        img2 = None
                        pic = GalleryManager.get().find_pic(pid, raise_if_nofound=False)
                        if pic and os.path.exists(pic.path):
                            img2 = open_image(pic.path)
                            img2.thumbnail(REPEAT_IMAGE_SHOW_SIZE)
                        with HSplit().set_padding(0).set_sep(4):
                            with VSplit().set_padding(0).set_sep(4).set_content_align('c').set_item_align('c'):
                                ImageBox(image=img, size=REPEAT_IMAGE_SHOW_SIZE, image_size_mode='fit').set_content_align('c')
                                TextBox(f"待上传图片", TextStyle(DEFAULT_FONT, 16, BLACK))
                            with VSplit().set_padding(0).set_sep(4).set_content_align('c').set_item_align('c'):
                                if img2:
                                    ImageBox(image=img2, size=REPEAT_IMAGE_SHOW_SIZE, image_size_mode='fit').set_content_align('c')
                                else:
                                    Spacer(w=REPEAT_IMAGE_SHOW_SIZE[0], h=REPEAT_IMAGE_SHOW_SIZE[1])
                                TextBox(f"pid: {pid}", TextStyle(DEFAULT_FONT, 16, BLACK))
                                
        repeat_img = await canvas.get_img()
    
    msg = f"成功上传{len(ok_list)}/{len(image_datas)}张图片到画廊\"{name}\"\n" + err_msg
    if repeats:
        msg += f"{len(repeats)}张图片与已有图片重复:"
        msg += await get_image_cq(repeat_img, low_quality=True)
    msg += "画廊主要收录表情/梗图，请勿上传可能有争议的图片"
    return await ctx.asend_fold_msg_adaptive(msg.strip())


gall_list = CmdHandler([
    '/gall list', '/看所有',
], logger)
gall_list.check_cdrate(cd).check_wblist(gbl)
@gall_list.handle()
async def _(ctx: HandlerContext):
    name = ctx.get_args().strip()
    
    # 列出所有画廊
    if not name:
        galls = GalleryManager.get().get_all_galls()
        if not galls:
            return await ctx.asend_reply_msg('当前没有任何画廊')
        
        with Canvas(bg=FillBg((230, 240, 255, 255))).set_padding(8) as canvas:
            with Grid(row_count=int(math.sqrt(len(galls))), hsep=8, vsep=8).set_item_align('t').set_content_align('t'):
                for name, g in galls.items():
                    cover: GalleryPic = GalleryManager.get().find_pic(g.cover_pid or 0)
                    if not cover and g.pics:
                        cover = g.pics[0]

                    total_size = 0
                    for p in glob.glob(os.path.join(g.pics_dir, '*')):
                        if os.path.isfile(p):
                            total_size += os.path.getsize(p)
                    total_size = total_size / (1024 * 1024)
                    if total_size < 1024:
                        size_text = f"{total_size:.1f}M"
                    else:
                        size_text = f"{total_size/1024:.1f}G"

                    with VSplit().set_padding(0).set_sep(4).set_content_align('c').set_item_align('c'):
                        if cover:
                            cover.ensure_thumb()
                            ImageBox(image=open_image(cover.thumb_path), 
                                     size=(THUMBNAIL_SIZE[0]*2, THUMBNAIL_SIZE[1]*2), image_size_mode='fit').set_content_align('c')
                        else:
                            Spacer(w=THUMBNAIL_SIZE[0]*2, h=THUMBNAIL_SIZE[1]*2)
                        TextBox(f"{name}", TextStyle(DEFAULT_BOLD_FONT, 24, BLACK))
                        text = f"{len(g.pics)}张 ({size_text})"
                        if g.mode != GalleryMode.Edit:
                            text += f" [{g.mode.value}]"
                        TextBox(text, TextStyle(DEFAULT_FONT, 20, BLACK))
                        TextBox(f"别名: {', '.join(g.aliases) if g.aliases else '无'}", TextStyle(DEFAULT_FONT, 12, (50, 50, 50)), use_real_line_count=True) \
                            .set_w(THUMBNAIL_SIZE[0] * 2).set_content_align('c')
                        
        return await ctx.asend_msg(
            await get_image_cq(
                await canvas.get_img(),
                low_quality=True,
            )
        )
    
    # 列出指定画廊的图片
    g = GalleryManager.get().find_gall(name, raise_if_nofound=True)
    is_super = check_superuser(ctx.event)
    if not is_super and g.mode == GalleryMode.Off:
        raise ReplyException(f'画廊\"{name}\"已关闭')
    
    assert_and_reply(g.pics, f'画廊\"{name}\"没有图片')
    
    with Canvas(bg=FillBg((230, 240, 255, 255))).set_padding(8) as canvas:
        with Grid(row_count=int(math.sqrt(len(g.pics))), hsep=4, vsep=4):
            for pic in g.pics:
                pic.ensure_thumb()
                with VSplit().set_padding(0).set_sep(2).set_content_align('c').set_item_align('c'):
                    if pic.thumb_path and os.path.exists(pic.thumb_path):
                        ImageBox(pic.thumb_path, size=THUMBNAIL_SIZE, image_size_mode='fit').set_content_align('c')
                    else:
                        Spacer(w=THUMBNAIL_SIZE[0], h=THUMBNAIL_SIZE[1])
                    TextBox(f"{pic.pid}", TextStyle(DEFAULT_FONT, 12, BLACK))

    return await ctx.asend_reply_msg(
        await get_image_cq(
            await canvas.get_img(),
            low_quality=True,
        )
    )


gall_log = CmdHandler([
    '/gall log',
], logger)
gall_log.check_cdrate(cd).check_wblist(gbl).check_superuser()
@gall_log.handle()
async def _(ctx: HandlerContext):
    try: 
        pid = int(ctx.get_args().strip())
    except:
        raise ReplyException('使用方式: /gall log pid')

    lines = []
    if os.path.exists(ADD_LOG_FILE):
        with open(ADD_LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    
    for line in lines:
        if f'pid={pid}' in line:
            return await ctx.asend_reply_msg(line.strip())
        
    raise ReplyException(f'pid={pid}的上传记录不存在')
    

gall_download = CmdHandler([
    '/gall download', 
], logger)
gall_download.check_cdrate(cd).check_wblist(gbl).check_superuser().check_group()
@gall_download.handle()
async def _(ctx: HandlerContext):
    name = ctx.get_args().strip()
    g = GalleryManager.get().find_gall(name, raise_if_nofound=True)
    assert_and_reply(g.pics, f'画廊\"{name}\"没有图片')

    with TempFilePath(".zip", remove_after=timedelta(minutes=5)) as zip_path:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for pic in g.pics:
                arcname = os.path.basename(pic.path)
                zipf.write(pic.path, arcname)
        
        filesize = os.path.getsize(zip_path) / (1024 * 1024)
        await ctx.asend_reply_msg(f'正在发送画廊\"{name}\"所有{len(g.pics)}张图片的压缩包({filesize:.2f}M)...')

        await upload_group_file(
            ctx.bot,
            ctx.group_id,
            zip_path,
            f"{name}-{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
        )


gall_cover = CmdHandler([
    '/gall cover', 
], logger)
gall_cover.check_cdrate(cd).check_wblist(gbl).check_superuser()
@gall_cover.handle()
async def _(ctx: HandlerContext):
    args = ctx.get_args().strip().split()
    if len(args) != 2:
        raise ReplyException('使用方式: /gall cover 画廊名称 图片ID')
    name, pid_str = args
    try:
        pid = int(pid_str)
    except:
        raise ReplyException('图片ID必须是整数')

    GalleryManager.get().set_cover_pic(name, pid)
    await ctx.asend_reply_msg(f'画廊\"{name}\"封面图片设置为pid={pid}成功')


gall_check = CmdHandler([
    '/gall check', 
], logger)
gall_check.check_cdrate(cd).check_wblist(gbl).check_superuser()
@gall_check.handle()
async def _(ctx: HandlerContext):
    name = ctx.get_args().strip()

    rehash = False
    if 'rehash' in name:
        rehash = True
        name = name.replace('rehash', '').strip()

    all = False
    if name == 'all':
        all = True
        name = name.replace('all', '').strip()

    async def check(name: str):
        if rehash:
            msg = f'正在为画廊\"{name}\"重新计算hash并检查重复图片...'
        else:
            msg = f'正在为画廊\"{name}\"检查重复图片...'
        await ctx.asend_reply_msg(msg)
        res = await GalleryManager.get().async_check_gallery(name, rehash=rehash)

        if not res:
            return await ctx.asend_reply_msg(f'画廊\"{name}\"重新计算hash完成，未发现重复图片')

        REPEAT_IMAGE_SHOW_SIZE = (128, 128)
        with Canvas(bg=FillBg((230, 240, 255, 255))).set_padding(8) as canvas:
            with VSplit().set_padding(16).set_sep(8).set_item_align('lt').set_content_align('lt'):
                for first_pid, repeat_pids in res.items():
                    pids = [first_pid] + repeat_pids
                    with HSplit().set_padding(0).set_sep(4).set_item_align('lt').set_content_align('lt'):
                        for pid in pids:
                            img = None
                            pic = GalleryManager.get().find_pic(pid, raise_if_nofound=False)
                            def open_img():
                                if pic and os.path.exists(pic.path):
                                    img = open_image(pic.path)
                                    img.thumbnail(REPEAT_IMAGE_SHOW_SIZE)
                                    return img
                                return None
                            img = await run_in_pool(open_img)
                            with VSplit().set_padding(0).set_sep(4).set_content_align('c').set_item_align('c'):
                                if img:
                                    ImageBox(image=img, size=REPEAT_IMAGE_SHOW_SIZE, image_size_mode='fit').set_content_align('c')
                                else:
                                    Spacer(w=REPEAT_IMAGE_SHOW_SIZE[0], h=REPEAT_IMAGE_SHOW_SIZE[1])
                                TextBox(f"pid: {pid}", TextStyle(DEFAULT_FONT, 16, BLACK))
        
        repeat_img = await canvas.get_img()
        if rehash:
            msg = f'画廊\"{name}\"重新计算hash完成，发现重复图片组共{len(res)}组:\n'
        else:
            msg = f'画廊\"{name}\"检查完成，发现重复图片组共{len(res)}组:\n'
        msg += await get_image_cq(repeat_img, low_quality=True)
        msg += f'推荐移除的重复图片pid:'
        for first_pid, repeat_pids in res.items():
            msg += '\n' + ' '.join(str(pid) for pid in repeat_pids)
        return await ctx.asend_fold_msg_adaptive(msg.strip())
    
    if all:
        galls = GalleryManager.get().get_all_galls()
        for name in galls.keys():
            await check(name)
    else:
        await check(name)


gall_replace = CmdHandler([
    '/gall replace', 
], logger)
gall_replace.check_cdrate(cd).check_wblist(gbl).check_superuser()
@gall_replace.handle()
async def _(ctx: HandlerContext):
    args = ctx.get_args().strip()

    try:
        check_duplicated = True
        if 'force' in args:
            check_duplicated = False
            args.remove('force')
        pid = int(args)
    except:
        raise ReplyException('使用方式: /gall replace pid')

    image_data = await ctx.aget_image_datas(return_first=True, max_count=1)
    if not image_data:
        raise ReplyException('请附加要替换的图片')
    
    async with TempDownloadFilePath(image_data['url'], 'gif') as path:
        await run_in_pool(process_image_for_gallery, path, image_data.get('sub_type', 1))
        try:
            pid = await GalleryManager.get().async_replace_pic(pid, path, check_duplicated=check_duplicated)
        except GalleryPicRepeatedException as e:
            raise ReplyException(f'替换失败: 画廊中已存在相似图片(pid={e.pid})')

    await ctx.asend_reply_msg(f'成功替换图片pid={pid}')
    