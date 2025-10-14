from ..utils import *
from ..water import calc_phash
from enum import Enum


config = Config('gallery')
logger = get_logger('Gallery')
file_db = get_file_db('data/gallery/gallery.json', logger)
cd = ColdDown(file_db, logger)
gbl = get_group_black_list(file_db, logger, 'gallery')

THUMBNAIL_SIZE = (64, 64)
SIZE_LIMIT_MB = 3
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


@dataclass
class Gallery:
    name: str
    aliases: list[str]
    mode: GalleryMode
    pics_dir: str
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
        for g in self.galleries.values():
            for p in g.pics:
                if p.pid == pid:
                    return p
        if raise_if_nofound:
            raise ReplyException(f'画廊图片pid={pid}不存在')
        return None

    async def async_add_pic(self, name_or_alias: str, img_path: str) -> int:
        """
        向画廊添加一张图片，将会直接拷贝img_path的图片，返回图片ID
        """
        g = self.find_gall(name_or_alias)
        assert g is not None, f'画廊\"{name_or_alias}\"不存在'
    
        phash = await calc_phash(img_path)
        for p in g.pics:
            assert p.phash != phash, f'画廊\"{g.name}\"已存在相似图片(pid={p.pid})'

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

        self._save()
        return self.pid_top

    def del_pic(self, pid: int):
        """
        从画廊删除一张图片
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
            phash = await calc_phash(file)
            if any(p.phash == phash for p in g.pics):
                continue
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
        pid = int(ctx.get_args().strip())
    except:
        raise ReplyException('使用方式: /gall del 图片ID')
    GalleryManager.get().del_pic(pid)
    await ctx.asend_reply_msg(f'图片pid={pid}删除成功')


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
], logger)
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
    args = ctx.get_args().strip()
    if not args:
        raise ReplyException('使用方式: /看 画廊名称 或 /看 图片ID')

    pic, name = None, None
    try: 
        pic = GalleryManager.get().find_pic(int(args), raise_if_nofound=True)
        name = pic.gall_name
    except: 
        pic = None
        name = args

    g = GalleryManager.get().find_gall(name, raise_if_nofound=True)
    is_super = check_superuser(ctx.event)
    if not is_super and g.mode == GalleryMode.Off:
        raise ReplyException(f'画廊\"{name}\"已关闭')

    if pic is None:
        if not g.pics:
            raise ReplyException(f'画廊\"{name}\"没有图片')
        pic = random.choice(g.pics)

    await ctx.asend_msg(await get_image_cq(pic.path, send_local_file_as_is=True))


gall_add = CmdHandler([
    '/gall add', '/gall upload', '/上传', '/添加',
], logger)
gall_add.check_cdrate(cd).check_wblist(gbl)
@gall_add.handle()
async def _(ctx: HandlerContext):
    name = ctx.get_args().strip()
    g = GalleryManager.get().find_gall(name, raise_if_nofound=True)

    is_super = check_superuser(ctx.event)
    if not is_super and g.mode != GalleryMode.Edit:
        raise ReplyException(f'画廊\"{name}\"不允许上传图片')
    
    image_datas = await ctx.aget_image_datas()
    ok_list, err_msg = [], ""
    for i, data in enumerate(image_datas, 1):
        try:
            async with TempDownloadFilePath(data['url'], 'png') as path:
                filesize_mb = os.path.getsize(path) / (1024 * 1024)
                if filesize_mb > SIZE_LIMIT_MB:
                    raise Exception(f"第{i}张图片大小{filesize_mb:.2f}MB超过限制{SIZE_LIMIT_MB}MB")
                with TempFilePath('gif') as gif_path:
                    # 如果是表情并且是静态图，可能获取到jpg，手动转换为gif
                    img = open_image(path)
                    if data.get('sub_type', 1) == 1 and not is_animated(img):
                        save_transparent_static_gif(img, gif_path)
                        path = gif_path
                    pid = await GalleryManager.get().async_add_pic(name, path)
            ok_list.append(pid)
            with open(ADD_LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | @{ctx.event.user_id} upload pid={pid} to \"{name}\"\n")
        except Exception as e:
            logger.print_exc(f"上传第{i}张图片到画廊\"{name}\"失败")
            err_msg += f"上传第{i}张图片失败: {get_exc_desc(e)}\n"
    
    msg = f"成功上传{len(ok_list)}张图片到画廊\"{name}\"\n" + err_msg
    return await ctx.asend_reply_msg(msg.strip())


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
        msg = ""
        for g in galls.values():
            msg += f"【{g.name}】\n"
            msg += f"{len(g.pics)}张图片 模式:{g.mode.value}\n"
            if g.aliases:
                msg += f"别名: {', '.join(g.aliases)}\n"
        return await ctx.asend_fold_msg_adaptive(msg.strip())
    
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
