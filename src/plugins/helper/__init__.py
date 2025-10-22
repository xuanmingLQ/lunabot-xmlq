from ..utils import *
import glob

config = Config('helper')
logger = get_logger('Helper')
file_db = get_file_db('data/helper/db.json', logger)
gbl = get_group_black_list(file_db, logger, 'helper')
cd = ColdDown(file_db, logger)


HELP_DOCS_WEB_URL = "https://github.com/NeuraXmy/lunabot/blob/master/helps/{name}.md"
HELP_DOCS_PATH = "helps/{name}.md"

HELP_IMG_SCALE = 0.8
HELP_IMG_WIDTH = 600
HELP_IMG_INTERSECT = 20

help = CmdHandler(['/help', '/帮助'], logger, block=True, priority=99999)
help.check_wblist(gbl).check_cdrate(cd)
@help.handle()
async def _(ctx: HandlerContext):
    args = ctx.get_args().strip()

    help_doc_paths = glob.glob(HELP_DOCS_PATH.format(name='*'))
    help_names = []
    help_decs = []
    for path in help_doc_paths:
        try:
            if path.endswith('main.md'): continue
            with open(path, 'r') as f:
                first_line = f.readline().strip()
            help_decs.append(first_line.split()[1])
            help_names.append(Path(path).stem)
        except:
            pass

    if not args or args not in help_names:
        msg = "【Lunabot使用帮助】\n"
        msg += "发送 \"/help 英文服务名\" 查看各服务的详细帮助\n"
        msg += f"例如发送 \"/help {help_names[0]}\" 查看\"{help_decs[0]}\"的帮助\n"
        msg += "\n可查询的服务列表:\n"
        for name, desc in sorted(zip(help_names, help_decs)):
            msg += f"{name} - {desc}\n"
        msg += f"\n或前往网页查看帮助文档:\n"
        msg += HELP_DOCS_WEB_URL.format(name='main')
        return await ctx.asend_fold_msg_adaptive(msg, need_reply=False)
    else:
        try:
            # 尝试从缓存读取
            doc_path = HELP_DOCS_PATH.format(name=args)
            doc_mtime = os.path.getmtime(doc_path)
            cache_mtime = file_db.get('help_img_cache_mtime', {})
            cache_path = create_parent_folder(f"data/helper/cache/{args}.png")
            if Path(cache_path).exists() and doc_mtime <= cache_mtime.get(args, 0):
                return await ctx.asend_reply_msg(await get_image_cq(cache_path, low_quality=True))
            else:
                logger.info(f"缓存 {args} 帮助文档不存在或已过期，重新渲染")
                doc_text = Path(doc_path).read_text()
                image = await markdown_to_image(doc_text, width=HELP_IMG_WIDTH)
                image = image.resize((int(image.width * HELP_IMG_SCALE), int(image.height * HELP_IMG_SCALE)))
                # 如果长度过长，截成几段再横向拼接发送
                max_height = HELP_IMG_WIDTH * 3
                if image.height > max_height:
                    n = math.floor(math.sqrt(image.height * image.width) / image.width)
                    height = math.ceil(image.height / n)
                    images = []
                    for i in range(0, image.height, height):
                        bbox = [0, i, image.width, i + height]
                        if bbox[1] > 0:
                            bbox[1] = bbox[1] - HELP_IMG_INTERSECT
                        images.append(image.crop(bbox))
                    image = await run_in_pool(concat_images, images, 'h')
                # 保存缓存
                image.save(cache_path)
                cache_mtime[args] = doc_mtime
                file_db.set(f'help_img_cache_mtime', cache_mtime)
                return await ctx.asend_reply_msg(await get_image_cq(image, low_quality=True))

        except Exception as e:
            logger.print_exc(f"渲染 {doc_path} 帮助文档失败")
            return await ctx.asend_reply_msg(f"帮助文档渲染失败, 前往网页获取帮助文档:\n{HELP_DOCS_WEB_URL.format(name=args)}")
            

