from ..utils import *
from .common import *
from .handler import SekaiHandlerContext


# 通过角色ID获取角色头像
def get_chara_icon_by_chara_id(cid: int, size: int = None, raise_exc=True, default=None, unit=None):
    """
    通过角色ID获取角色头像
    """
    nickname = CHARACTER_FIRST_NICKNAME.get(cid)
    if not nickname:
        if raise_exc: raise Exception(f"要获取的icon的角色ID={cid}错误")
        else: return default
    path = f"chara_icon/{nickname}"
    if unit is not None and unit != "piapro" and nickname == "miku":
        path += f"_{unit}"
    path += ".png"
    img = SekaiHandlerContext.from_region('jp').static_imgs.get(path)
    if size is not None:
        img = img.resize((size, size))
    return img
    
# 通过角色昵称获取角色头像
def get_chara_icon_by_nickname(nickname: str, size: int = None, raise_exc=True, default=None, unit=None):
    """
    通过角色昵称获取角色头像
    """
    cid = get_cid_by_nickname(nickname)
    if not cid:
        if raise_exc: raise Exception(f"要获取的icon的角色昵称错误")
        else: return default
    return get_chara_icon_by_chara_id(cid, size, raise_exc, default, unit)

# 获取团logo
def get_unit_logo(unit: str, size: int = None):
    img = SekaiHandlerContext.from_region('jp').static_imgs.get(f"logo_{unit}.png")
    if size is not None:
        img = img.resize((size, size))
    return img

# 获取团图标
def get_unit_icon(unit: str, size: int = None):
    img = SekaiHandlerContext.from_region('jp').static_imgs.get(f"icon_{unit}.png")
    if size is not None:
        img = img.resize((size, size))
    return img

# 获取属性图标
def get_attr_icon(attr: str, size: int = None):
    img = SekaiHandlerContext.from_region('jp').static_imgs.get(f"card/attr_icon_{attr}.png")
    if size is not None:
        img = img.resize((size, size))
    return img


# sekai默认背景
class SekaiBg(WidgetBg):
    def __init__(self, time_color, main_hue: float=None, size_fixed_rate: float=0.0):
        super().__init__()
        self.time_color = time_color
        self.main_hue = main_hue
        self.size_fixed_rate = size_fixed_rate

    def draw(self, p: Painter):
        timecolors = [
            (0,  0.57, 4.0, 0.1),
            (5,  0.57, 2.0, 0.2),
            (9,  0.57, 1.0, 0.8),
            (12, 0.57, 1.0, 1.0),
            (15, 0.57, 1.0, 0.8),
            (19, 0.57, 2.0, 0.2),
            (24, 0.57, 4.0, 0.1),
        ]
        def get_timecolor(t: datetime):
            if t.hour < timecolors[0][0]:
                return timecolors[0][1:]
            elif t.hour >= timecolors[-1][0]:
                return timecolors[-1][1:]
            for i in range(0, len(timecolors) - 1):
                if t.hour >= timecolors[i][0] and t.hour < timecolors[i + 1][0]:
                    hour1, h1, s1, l1 = timecolors[i]
                    hour2, h2, s2, l2 = timecolors[i + 1]
                    t1 = datetime(t.year, t.month, t.day, hour1)
                    if hour2 == 24: t2 = datetime(t.year, t.month, t.day + 1, 0)
                    else:           t2 = datetime(t.year, t.month, t.day, hour2)
                    x = (t - t1) / (t2 - t1)
                    return (
                        h1 + (h2 - h1) * x,
                        s1 + (s2 - s1) * x,
                        l1 + (l2 - l1) * x,
                    ) 

        w, h = p.w, p.h
        if self.time_color:
            mh, ms, ml = get_timecolor(datetime.now())
        else:
            mh = self.main_hue
            ms = 1.0
            ml = 1.0
        size_fixed_rate = self.size_fixed_rate

        def h2c(h, s, l, a=255):
            h = (h + 1.0) % 1.0 
            r, g, b = colorsys.hls_to_rgb(h, l * ml, s * ms)
            return [int(255 * c) for c in (r, g, b)] + [a]

        ofs, s = 0.025, 4
        bg = LinearGradient(
            c1=h2c(mh, 0.5, 1.0), c2=h2c(mh + ofs, 0.9, 0.5),
            p1=(0, 1), p2=(1, 0)
        ).get_img((w // s, h // s))
        bg.alpha_composite(LinearGradient(
            c1=h2c(mh, 0.9, 0.7, 100), c2=h2c(mh - ofs, 0.5, 0.5, 100),
            p1=(0, 0), p2=(1, 1)
        ).get_img((w // s, h // s)))
        bg.alpha_composite(Image.new("RGBA", (w // s, h // s), (255, 255, 255, 100)))
        bg = bg.resize((w, h), Image.LANCZOS)

        tri1 = Image.new("RGBA", (64, 64), (255, 255, 255, 0))
        draw = ImageDraw.Draw(tri1)
        draw.polygon([(0, 0), (64, 32), (32, 64)], fill=WHITE)

        tri2 = Image.new("RGBA", (64, 64), (255, 255, 255, 0))
        draw = ImageDraw.Draw(tri2)
        draw.polygon([(0, 0), (64, 32), (32, 64)], outline=WHITE, width=4)

        def draw_tri(x, y, rot, size, color, type):
            img = tri1 if type == 0 else tri2
            img = img.resize((size, size), Image.BILINEAR)
            img = img.rotate(rot, expand=True)
            img = ImageChops.multiply(img, Image.new("RGBA", img.size, color))
            bg.alpha_composite(img, (int(x) - img.width // 2, int(y) - img.height // 2))

        preset_colors = [
            (255, 189, 246),
            (183, 246, 255),
            (255, 247, 146),
        ]

        factor = min(w, h) / 2048 * 1.5
        size_factor = (1.0 + (factor - 1.0) * (1.0 - size_fixed_rate))
        dense_factor = 1.0 + (factor * factor - 1.0) * size_fixed_rate

        def rand_tri(num, sz):
            for i in range(num):
                x = random.uniform(0, w)
                y = random.uniform(0, h)
                if x < 0 or x >= w or y < 0 or y >= h:
                    continue
                rot = random.uniform(0, 360)
                size = max(1, min(1000, int(random.normalvariate(sz[0], sz[1]))))
                dist = (((x - w // 2) / w * 2) ** 2 + ((y - h // 2) / h * 2) ** 2)
                size = int(size * dist)
                size_alpha_factor, std_size = 1.0, 32 * size_factor
                if size < std_size:
                    size_alpha_factor = size / std_size
                if size > std_size:
                    size_alpha_factor = 1.0 - (size - std_size * 1.5) / (std_size * 1.5)
                alpha = int(random.normalvariate(50, 200) * max(0, min(1.2, size_alpha_factor)))
                if alpha <= 0:
                    continue
                color = random.choice(preset_colors + [(255, 255, 255)] * 0)
                color = (*color, alpha)
                type = i % 3 // 2
                draw_tri(x, y, rot, size, color, type)

        rand_tri(int(100 * dense_factor), (48 * size_factor, 16 * size_factor))
        rand_tri(int(1000 * dense_factor), (16 * size_factor, 16 * size_factor))

        p.paste(bg, (0, 0))


SEKAI_BLUE_BG = SekaiBg(True)
SEKAI_RED_BG = SekaiBg(False, main_hue=0.05)

BG_PADDING = 20
WIDGET_BG_COLOR = (255, 255, 255, 150)
WIDGET_BG_RADIUS = 10


blurglass_enabled = True

def set_blurglass_enabled(enabled: bool):
    global blurglass_enabled
    blurglass_enabled = enabled

def get_blurglass_enabled() -> bool:
    global blurglass_enabled
    return blurglass_enabled

# 统一的半透明白色圆角矩形背景
def roundrect_bg(fill=WIDGET_BG_COLOR, radius=WIDGET_BG_RADIUS, alpha=None, blurglass=None):
    """
    统一的半透明白色圆角矩形背景
    """
    global blurglass_enabled
    if blurglass is None:
        blurglass = blurglass_enabled
    if alpha is not None:
        fill = (*fill[:3], alpha)
    return RoundRectBg(fill, radius, blurglass=blurglass)


COMMON_BG_NAMES = [
    "bg/title_background.png",
    "bg/bg_area_1.png",
    "bg/bg_area_2.png",
    "bg/bg_area_3.png",
    "bg/bg_area_4.png",
    "bg/bg_area_11.png",
    "bg/bg_area_12.png",
    "bg/bg_area_13.png",
]
GROUP_BG_NAMES = {
    UNIT_LN:   ["bg/bg_area_5.png",  "bg/bg_area_17.png", "bg/bg_light_sound.png"],
    UNIT_MMJ:  ["bg/bg_area_7.png",  "bg/bg_area_18.png", "bg/bg_idol.png"],
    UNIT_VBS:  ["bg/bg_area_8.png",  "bg/bg_area_19.png", "bg/bg_street.png"],
    UNIT_WS:   ["bg/bg_area_9.png",  "bg/bg_area_20.png", "bg/bg_theme_park.png"],
    UNIT_25:   ["bg/bg_area_10.png", "bg/bg_area_21.png", "bg/bg_school_refusal.png"],
    UNIT_VS:   ["bg/bg_virtual_singer.png"]
}

# 随机选择团队背景
def random_unit_bg(unit: str = None):
    """
    随机选择团队背景
    unit为None时随机选择一个通用背景
    """
    ctx = SekaiHandlerContext.from_region('jp')
    if unit is None:
        bg_name = random.choice(COMMON_BG_NAMES)
        img = ctx.static_imgs.get(bg_name)
    else:
        bg_name = random.choice(GROUP_BG_NAMES.get(unit, COMMON_BG_NAMES))
        img = ctx.static_imgs.get(bg_name)
    return ImageBg(img)


DEFAULT_WATERMARK = "Designed & generated by NeuraXmy(ルナ茶)'s lunabot"

# 在画布上添加水印
def add_watermark(canvas: Canvas, text: str=DEFAULT_WATERMARK, size=12):
    """
    在画布上添加水印
    """
    frame_watermark = Frame().set_content_align('rb').set_padding(0)
    frame_canvas = Frame().set_content_align(canvas.get_content_align()).set_padding(0).set_size((canvas.w, canvas.h))
    s1 = TextStyle(font=DEFAULT_FONT, size=size, color=(255, 255, 255, 256))
    s2 = TextStyle(font=DEFAULT_FONT, size=size, color=(75, 75, 75, 256))
    offset1 = (int(16 - BG_PADDING * 0.5), 16)
    offset2 = (offset1[0] + 1, offset1[1] + 1)
    text1 = TextBox(text, style=s1).set_omit_parent_bg(True).set_offset(offset1)
    text2 = TextBox(text, style=s2).set_omit_parent_bg(True).set_offset(offset2)
    items = canvas.items
    canvas.set_items([])
    canvas.set_padding(BG_PADDING)
    for item in items:
        frame_canvas.add_item(item)
    frame_watermark.add_item(frame_canvas)
    frame_watermark.add_item(text2)
    frame_watermark.add_item(text1)
    canvas.add_item(frame_watermark).set_size(None)


DIFF_COLORS = {
    "easy": (102, 221, 17, 255),
    "normal": (51,187, 238, 255),
    "hard": (255, 170, 0, 255),
    "expert": (238, 68, 102, 255),
    "master": (187, 51, 238, 255),
    "append": LinearGradient((182, 144, 247, 255), (243, 132, 220, 255), (0, 0), (1, 1)),
}
PLAY_RESULT_COLORS = {
    'not_clear': (69, 67, 104, 255),
    'clear': (255, 226, 118, 255),
    'fc': (253, 167, 249, 255),
    'ap': (63, 230, 228, 255),
}

