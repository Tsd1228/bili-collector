#!/usr/bin/env python3
"""
B站数据综合分析报告

读取收藏夹 + 动态数据，生成分区/梗分析报告
"""

import json
import os
import re
import sys
from collections import defaultdict, Counter
from pathlib import Path

os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# 便携模式
_base_dir = Path(__file__).parent.resolve()
if os.environ.get("BILI_PORTABLE", "1") == "0":
    _base_dir = Path.home() / ".bilibili_fav"

BILI_FAV_HOME = _base_dir
UID_FILE = BILI_FAV_HOME / "bili_uid.txt"


def get_uid() -> str:
    if UID_FILE.exists():
        return UID_FILE.read_text().strip()
    return "229558048"


REPORT_LINES = []


def p(text=""):
    REPORT_LINES.append(text)
    try:
        print(text)
    except UnicodeEncodeError:
        print(str(text).encode('utf-8', errors='replace').decode('gbk', errors='replace'))


# =============================================================================
#  分区规则
# =============================================================================
I = re.IGNORECASE

ZONE_RULES = [
    # ===== 鬼畜区 =====
    (r"哈基米|基米(?![^贵金])|HACHIMI|基咪|基米唱片|十面基米|星基穿越|夜来哈"
     r"|牵私人戏|哈基米重度依赖|HACHIMI OVERDOSE|Highscore"
     r"|热爱105[度°]C的哈基米|基米的随波逐流|神人的随波逐流"
     r"|哈基米音乐|哈基米PV|哈基米山歌|哈基米是数据线之奴隶"
     r"|曼波|傻不啦叽|哈\s?异\s?常",
     "[鬼畜区]", "哈基米宇宙"),

    (r"音MAD|鬼畜调教|人力VOCALOID|霍全甲|对口型"
     r"|金坷垃|诸葛亮骂王朗|梁非凡|兄贵|哲学♂"
     r"|三国鬼畜|全明星|鬼畜翻唱",
     "[鬼畜区]", "音MAD/鬼畜调教"),

    (r"霍全甲|神人|恶搞|洗脑|空耳|填词|remix|重制|补档",
     "[鬼畜区]", "鬼畜改词/恶搞"),

    # ===== 动画/番剧区 =====
    (r"MyGO(!!!!!)?|mygo(!!!!!)?|迷星叫|壱雫空|影色舞"
     r"|春日影|诗超绊|潜在表明|そよ"
     r"|長崎|素世|AveMujica|Ave Mujica|喵梦(亲)?"
     r"|高松灯|千早愛音|要乐奈|立希|若叶睦|三角初华|八幡海铃|祐天寺若麦"
     r"|(?<![a-zA-Z])486(?![a-zA-Z])|少女乐队|动漫乐队"
     r"|邦邦|BanG Dream|bang dream",
     "[动画/番剧区]", "MyGO!!!!!/Ave Mujica"),

    (r"新番|番剧|动画推荐|动漫推荐|追番|补番"
     r"|动画杂谈|动画吐槽|动漫杂谈"
     r"|二次元|番评|这年头.{0,10}谁还在看",
     "[动画/番剧区]", "新番/动画杂谈"),

    (r"MAD|AMV|静止画MAD|同人|手书|MMD|二创",
     "[动画/番剧区]", "动画二创/MAD"),

    # ===== 音乐区 =====
    (r"初音ミク|初音未来|初音(?=.*(?:ミク|曲|歌))?|重音テト|重音"
     r"|ミク(?![^a-zA-Z])|(?<![a-zA-Z])miku(?![a-zA-Z])|(?<![a-zA-Z])Miku(?![a-zA-Z])"
     r"|VOCALOID|vocaloid|术力口|术曲|ボカロ|v家"
     r"|DECO\*?27|ピノキオピー|PinocchioP|サツキ|Satsuki"
     r"|Orangestar|煮ル果実|niki|wotaku|SHIKI"
     r"|メズマライザー|Mesmerizer|ラビットホール|モニタリング"
     r"|Loveit|snooze|T氏の話"
     r"|妄想感傷代償連盟|少女A|椎名もた|ライアーダンサー|どこにもいかない",
     "[音乐区]", "VOCALOID/术力口"),

    (r"乐队Live|现场演出|演唱会|BGM|OST|主题曲"
     r"|吉他手|贝斯手|鼓手|主唱|键盘手"
     r"|摇滚|金属|朋克|合奏|排练|路演",
     "[音乐区]", "乐队/Live现场"),

    (r"吉他教学|吉他谱|吉他solo|吉他独奏|吉他伴奏"
     r"|弹唱|指弹|扫弦|和弦|钢琴教学|二胡|古筝"
     r"|练琴|乐理|识谱|翻弹|翻奏",
     "[音乐区]", "吉他/乐器教学"),

    (r"翻唱|(?<![a-zA-Z])cover(?![a-zA-Z])|(?<![a-zA-Z])Cover(?![a-zA-Z])|唱见|歌ってみた"
     r"|男声翻|女声翻|合唱|和声",
     "[音乐区]", "翻唱/翻弹"),

    (r"编曲|作曲|作词|混音|母带|(?<![a-zA-Z])FL Studio(?![a-zA-Z])"
     r"|Cubase|Ableton|音源|合成器|采样|音乐制作|P主",
     "[音乐区]", "音乐制作"),

    (r"Official Music Video|Official Video|官方投稿|原创歌曲|原创音乐",
     "[音乐区]", "官方MV/音乐视频"),

    (r"TOP\s*\d+|排行榜|盘点|歌单|音乐推荐|乐评|音乐鉴赏",
     "[音乐区]", "音乐杂谈/盘点"),

    # ===== 游戏区 =====
    (r"(?<![a-zA-Z])CSGO(?![a-zA-Z])|(?<![a-zA-Z])CS2(?![a-zA-Z])|(?<![a-zA-Z])CS:GO(?![a-zA-Z])|反恐精英|StatTrak"
     r"|大狗叫音乐盒|(?<![a-zA-Z])Valorant(?![a-zA-Z])|瓦罗兰特"
     r"|(?<![a-zA-Z])PUBG(?![a-zA-Z])|绝地求生|(?<![a-zA-Z])APEX(?![a-zA-Z])|Apex英雄"
     r"|使命召唤|战地|守望先锋|(?<![a-zA-Z])Overwatch(?![a-zA-Z])"
     r"|彩虹六号|帧数优化|压枪|跟枪|爆头",
     "[游戏区]", "FPS射击游戏"),

    (r"原神|星穹铁道|崩坏|米哈游|(?<![a-zA-Z])mhy(?![a-zA-Z])"
     r"|绝区零|(?<![a-zA-Z])ZZZ(?![a-zA-Z])|旷野之息|王泪"
     r"|开放世界(?![^的])|(?<![a-zA-Z])RPG(?![a-zA-Z])|角色扮演",
     "[游戏区]", "开放世界/RPG"),

    (r"英雄联盟|(?<![a-zA-Z])LOL(?![a-zA-Z])|(?<![a-zA-Z])DOTA(?![a-zA-Z])"
     r"|王者荣耀|(?<![a-zA-Z])KPL(?![a-zA-Z])"
     r"|上单|中单|打野|(?<![a-zA-Z])ADC(?![a-zA-Z])|团战|(?<![a-zA-Z])GANK(?![a-zA-Z])"
     r"|排位|段位|上分",
     "[游戏区]", "MOBA/竞技"),

    (r"Godot|godot|Unity引擎|Unreal|虚幻引擎"
     r"|游戏开发|DEV LOG|开发日志"
     r"|瓦片系统|Tilemap|像素游戏"
     r"|打击停顿|(?<![a-zA-Z])hitstop(?![a-zA-Z])|关卡设计",
     "[游戏区]", "游戏开发/引擎"),

    (r"游戏推荐|游戏杂谈|游戏文化|游戏设计|游戏史"
     r"|独立游戏|(?<![a-zA-Z])Indie(?![a-zA-Z])|游戏画面|游戏性",
     "[游戏区]", "游戏杂谈/评测"),

    (r"手游|手机游戏|抽卡|卡池|保底|氪金",
     "[游戏区]", "手机游戏"),

    # ===== 美食区 =====
    (r"家常菜做法|快手菜|烘焙|烤箱菜|空气炸锅"
     r"|料理教程|食材(?:处理|科普|介绍)|调料(?:搭配|推荐)"
     r"|红烧|清蒸|爆炒|炖汤|煲汤"
     r"|和面|揉面|发酵|醒面|(?:包|饺)子"
     r"|做饭|做菜|煮饭|炒菜|厨艺",
     "[美食区]", "做菜/烹饪教程"),

    (r"探店|打卡美食|试吃|美食街|网红店|老店"
     r"|苍蝇馆子|路边摊|性价比高|踩雷|避雷"
     r"|隐藏菜单|口味(?:测评|评测|推荐)",
     "[美食区]", "探店评测"),

    (r"吃播|咀嚼音|大胃王|吃垮自助餐"
     r"|暴食|狂吃|干饭(?![^的])",
     "[美食区]", "吃播"),

    (r"美食文化|饮食文化|食品工业|传统工艺"
     r"|非遗美食|街头美食|地方美食|特产|小吃"
     r"|食品安全|配料表",
     "[美食区]", "美食科普/文化"),

    # ===== 科技/数码区 =====
    (r"(?<![a-zA-Z])AI(?![a-zA-Z])|人工智能|(?<![a-zA-Z])AGI(?![a-zA-Z])"
     r"|(?<![a-zA-Z])ChatGPT(?![a-zA-Z])|(?<![a-zA-Z])GPT(?![a-zA-Z0-9])|(?<![a-zA-Z])OpenAI(?![a-zA-Z])"
     r"|(?<![a-zA-Z])Claude(?![a-zA-Z])|Anthropic|(?<![a-zA-Z])Gemini(?![a-zA-Z])"
     r"|(?<![a-zA-Z])ComfyUI(?![a-zA-Z])|Stable Diffusion|(?<![a-zA-Z])Midjourney(?![a-zA-Z])"
     r"|AI绘画|AI生图|AI视频|(?<![a-zA-Z])Sora(?![a-zA-Z])"
     r"|大模型|(?<![a-zA-Z])LLM(?![a-zA-Z])|(?<![a-zA-Z])vLLM(?![a-zA-Z])|(?<![a-zA-Z])RAG(?![a-zA-Z])"
     r"|(?<![a-zA-Z])Prompt(?![a-zA-Z])|提示词"
     r"|AI编程|(?<![a-zA-Z])Copilot(?![a-zA-Z])|(?<![a-zA-Z])Cursor(?![a-zA-Z])|(?<![a-zA-Z])Codex(?![a-zA-Z])"
     r"|机器学习|深度学习|神经网络"
     r"|(?<![a-zA-Z])Agent(?![a-zA-Z])|智能体|AI辅助|AI生成|AI工具"
     r"|9router|免费API",
     "[科技/数码区]", "AI人工智能"),

    (r"(?<![a-zA-Z])CPU(?![a-zA-Z])|(?<![a-zA-Z])GPU(?![a-zA-Z])|显卡|内存|硬盘|(?<![a-zA-Z])SSD(?![a-zA-Z])"
     r"|装机|配置(?=.*(?:电脑|主机|显卡|CPU))|跑分|性能"
     r"|笔记本|台式机|(?<![a-zA-Z])NVIDIA(?![a-zA-Z])|(?<![a-zA-Z])AMD(?![a-zA-Z])|(?<![a-zA-Z])Intel(?![a-zA-Z])"
     r"|[543]0系|(?<![a-zA-Z])RTX(?![a-zA-Z])",
     "[科技/数码区]", "电脑硬件"),

    (r"软件推荐|效率工具|自动化|插件|扩展"
     r"|使用技巧|快捷键|开源项目",
     "[科技/数码区]", "软件应用"),

    (r"数码评测|手机评测|开箱(?=.*(?:手机|数码|耳机|平板))"
     r"|平板评测|耳机评测|(?<![a-zA-Z])iPhone(?![a-zA-Z])|安卓(?:手机|平板|系统)"
     r"|华为(?:手机|平板|数码)|小米(?:手机|数码)",
     "[科技/数码区]", "数码产品评测"),

    # ===== 生活/娱乐区 =====
    (r"人民日报|别让算法|婚育观"
     r"|年轻人(?=.*(?:结婚|婚育|下班))|按时下班"
     r"|(?:不再)?相信努力|理想.{0,10}被现实取代"
     r"|文科无用|鼓吹.{0,10}(?:文科|无用)"
     r"|不敢叫的大狗|loser"
     r"|匹夫之勇|百家讲坛"
     r"|任何不允许质疑|任何不让评价",
     "[生活/娱乐区]", "社会时评/热点"),

    (r"人生感悟|职场|社畜|打工人"
     r"|赚钱(?=.*(?:技术|卖))|普通人(?=.*赚钱)"
     r"|逻辑思维|表达(?:能力|沟通)",
     "[生活/娱乐区]", "人生感悟/职场"),

    (r"找女朋友|恋爱(?=.*(?:技巧|方法|指南))|表白|相亲|脱单",
     "[生活/娱乐区]", "情感/婚恋"),

    (r"(?<![a-zA-Z])ASMR(?![a-zA-Z])|(?<![a-zA-Z])asmr(?![a-zA-Z])|音声|(?<![a-zA-Z])trigger(?![a-zA-Z])|触发音"
     r"|(?<![a-zA-Z])VRChat(?![a-zA-Z])|(?<![a-zA-Z])vrchat(?![a-zA-Z])"
     r"|变声器|王小桃|苦呀西|给木给木",
     "[生活/娱乐区]", "ASMR/音声"),

    (r"(?<![a-zA-Z])Vlog(?![a-zA-Z])|(?<![a-zA-Z])vlog(?![a-zA-Z])|日常|生活记录|搞笑(?=视频)?|整活",
     "[生活/娱乐区]", "搞笑/日常/Vlog"),

    # ===== 知识区 =====
    (r"编程|代码|算法|数据结构"
     r"|(?<![a-zA-Z])Python(?![a-zA-Z])|(?<![a-zA-Z])Java(?![a-zA-Z])|(?<![a-zA-Z])C\+\+(?![a-zA-Z])|(?<![a-zA-Z])JavaScript(?![a-zA-Z])|(?<![a-zA-Z])Rust(?![a-zA-Z])"
     r"|前端|后端|全栈"
     r"|(?<![a-zA-Z])git(?![a-zA-Z])|(?<![a-zA-Z])Git(?![a-zA-Z])|(?<![a-zA-Z])GitHub(?![a-zA-Z])"
     r"|开源|(?<![a-zA-Z])API(?![a-zA-Z])|接口|框架"
     r"|调试|重构|测试|部署"
     r"|计算机组成原理|计组|操作系统|(?<![a-zA-Z])OS(?![a-zA-Z])"
     r"|数据库系统|数据库|(?<![a-zA-Z])SQL(?![a-zA-Z])"
     r"|计算机网络|(?<![a-zA-Z])MIT(?![a-zA-Z])|计算机教育",
     "[知识区]", "计算机科学/编程"),

    (r"大学物理|大物|高数|高等数学|线性代数|概率论|离散数学"
     r"|期末(?:考前|冲刺)?速成|不挂科|考点"
     r"|考研|复习|冲刺|备考"
     r"|梯度|散度|旋度|向量|微积分",
     "[知识区]", "大学课程/考试"),

    (r"雅思|托福|(?<![a-zA-Z])GRE(?![a-zA-Z])|四六级"
     r"|英语(?:口语|听力)|日语(?=.*(?:学习|教学|课程))"
     r"|播客学英语|听力训练",
     "[知识区]", "语言学习"),

    (r"逆向工程|反编译|渗透(?:测试)?|漏洞"
     r"|(?<![a-zA-Z])root(?![a-zA-Z])|越狱|提权"
     r"|网络安全|黑客|破解|反代",
     "[知识区]", "网络安全/逆向"),

    (r"历史|哲学|社会(?:议题|现象|评论)|经济|政治"
     r"|人文|社科|心理(?:学|测试|知识)"
     r"|读书|书单|百家讲坛|3万对40万|得意之笔",
     "[知识区]", "社科人文/历史"),

    # ===== 舞蹈区 =====
    (r"宅舞|踊ってみた|翻跳|编舞",
     "[舞蹈区]", "宅舞"),

    # ===== 时尚区 =====
    (r"美妆|化妆|穿搭|搭配(?=.*(?:衣服|穿搭))|护肤",
     "[时尚区]", "美妆/穿搭"),

    (r"年度报告|表情包|纪念装扮|头像挂件|樱酱(?![^的])|八周年|圣诞节快乐",
     "[时尚区]", "B站装扮/收藏"),

    # ===== 运动区 =====
    (r"健身|减脂|增肌|训练(?=.*(?:健身|力量))|跑步(?=.*(?:健身|训练))|游泳",
     "[运动区]", "健身/运动"),
]

COMPILED = [(re.compile(pat, I), z1, z2) for pat, z1, z2 in ZONE_RULES]

# ========== 梗关键词 ==========
MEME_KEYWORDS = {
    "哈基米 / 基米宇宙": [
        "哈基米", "基米", "HACHIMI", "基咪",
        "哈基米FM", "基米唱片", "十面基米", "星基穿越", "夜来哈",
        "牵私人戏", "Highscore", "哈基米重度依赖", "HACHIMI OVERDOSE",
        "热爱105℃的哈基米", "基米的随波逐流", "神人的随波逐流",
        "哈基米音乐", "哈基米PV", "哈基米山歌",
        "哈基米是数据线之奴隶", "曼波", "哈异",
    ],
    "MyGO!!!!! / Ave Mujica 乐队番": [
        "MyGO", "mygo", "迷星叫", "壱雫空", "影色舞",
        "春日影", "诗超绊", "素世", "そよ", "長崎",
        "AveMujica", "喵梦", "486", "少女乐队",
        "BanG Dream", "邦邦",
    ],
    "VOCALOID / 术力口 (初音+Teto)": [
        "初音ミク", "初音", "重音テト", "重音", "ミク", "miku", "Miku",
        "VOCALOID", "vocaloid", "术力口", "术曲",
        "DECO*27", "ピノキオピー", "PinocchioP", "サツキ", "Orangestar",
        "メズマライザー", "ラビットホール", "モニタリング",
        "Loveit", "snooze", "T氏の話",
        "妄想感傷代償連盟", "少女A", "椎名もた",
        "ライアーダンサー", "どこにもいかない",
    ],
    "AI 大模型浪潮": [
        "AI", "AGI", "ChatGPT", "GPT", "Claude", "Gemini",
        "ComfyUI", "Stable Diffusion", "AI绘画",
        "大模型", "LLM", "vLLM", "RAG",
        "AI编程", "Copilot", "Codex",
        "Agent", "智能体", "AI辅助", "AI生成",
        "9router", "免费API", "Prompt", "提示词",
    ],
    "考研/期末/速成 学习潮": [
        "速成", "期末", "不挂科", "考研", "冲刺",
        "数据结构", "数据库系统", "计组", "计算机组成原理",
        "大学物理", "高数", "高等数学", "微积分",
        "雅思", "英语学习",
    ],
    "CS2/CSGO FPS": [
        "CSGO", "CS2", "CS:GO", "StatTrak", "大狗叫",
        "帧数优化", "硬件性能",
    ],
    "Godot / 独立游戏开发": [
        "Godot", "godot", "游戏引擎", "游戏开发", "DEV LOG",
        "打击停顿", "瓦片系统", "雨天效果",
    ],
    "逆向工程 / 网络安全": [
        "逆向", "逆向工程", "root", "网络安全",
        "反代", "渗透", "黑客",
    ],
    "社会议题 (婚育/算法/努力)": [
        "人民日报", "算法", "年轻人结婚", "婚育",
        "努力", "现实", "文科无用", "按时下班",
    ],
    "ASMR / 变声器 / VRChat": [
        "ASMR", "asmr", "变声器", "音声", "trigger",
        "VRChat", "王小桃", "苦呀西", "给木给木",
    ],
    "B站年度报告 / 装扮收藏": [
        "年度报告", "装扮", "纪念装扮", "头像挂件",
        "表情包", "樱酱", "八周年",
    ],
    "Git / GitHub / 开源": [
        "git", "Git", "GitHub", "编程", "开源", "前端",
    ],
    "鬼畜 / 霍全甲 / 对口型": [
        "霍全甲", "对口型", "神人", "随波逐流",
    ],
}


def classify_detailed(text):
    for pat, z1, z2 in COMPILED:
        if pat.search(text):
            return (z1, z2)
    return (None, None)


def run_analysis(uid: str = None) -> str:
    """运行分析，返回报告文本"""
    global REPORT_LINES
    REPORT_LINES = []

    if not uid:
        uid = get_uid()

    data_dir = BILI_FAV_HOME / f"data_{uid}"
    dynamics_dir = BILI_FAV_HOME / f"dynamics_{uid}"

    # 读取收藏夹数据
    favorites = {}
    if data_dir.exists():
        for fname in os.listdir(data_dir):
            if fname.endswith(".json") and fname != ".progress.json":
                with open(data_dir / fname, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for item in data:
                    item["_favorite"] = fname.replace(".json", "")
                favorites[fname.replace(".json", "")] = data

    # 读取动态数据
    dynamics = []
    simple_path = dynamics_dir / f"uid_{uid}_simple.json"
    if simple_path.exists():
        with open(simple_path, "r", encoding="utf-8") as f:
            dynamics = json.load(f)

    all_videos = []
    for items in favorites.values():
        all_videos.extend(items)

    if not all_videos and not dynamics:
        p("没有找到数据，请先运行采集")
        return "\n".join(REPORT_LINES)

    username = next((d.get('author', '未知用户') for d in dynamics if d.get('author')), '未知用户')

    # 分析
    all_text_pool = [v['title'] + " " + v['author'] for v in all_videos]
    for d in dynamics:
        all_text_pool.append(
            (d.get('content') or '') + " " +
            (d.get('video_title') or '') + " " +
            (d.get('forward_content') or '')
        )

    meme_stats = []
    for meme_name, kws in MEME_KEYWORDS.items():
        total = 0
        detail = []
        for kw in kws:
            c = sum(len(re.findall(re.escape(kw), t, re.IGNORECASE)) for t in all_text_pool)
            if c > 0:
                total += c
                detail.append((kw, c))
        if total > 0:
            meme_stats.append((total, meme_name, detail))
    meme_stats.sort(key=lambda x: -x[0])

    video_detail = []
    for v in all_videos:
        text = v['title'] + " " + v['author']
        z1, z2 = classify_detailed(text)
        video_detail.append((v, z1, z2))

    zone_l1_counter = Counter()
    zone_l2_counter = Counter()
    for v, z1, z2 in video_detail:
        if z1:
            zone_l1_counter[z1] += 1
        if z1 and z2:
            zone_l2_counter[(z1, z2)] += 1

    fav_detail = defaultdict(lambda: defaultdict(list))
    for v, z1, z2 in video_detail:
        fav_detail[v['_favorite']][z1 or "[未分类]"].append(v)

    dynamic_zones = defaultdict(list)
    for d in dynamics:
        text = (d.get('content') or '') + " " + (d.get('video_title') or '') + " " + (d.get('forward_content') or '')
        z1, _ = classify_detailed(text)
        if not z1:
            mt = d.get('type', '')
            if mt == 'common':
                z1 = "[装扮/报告]"
            elif d.get('video_bvid'):
                z1 = "[视频转发]"
            else:
                z1 = "[生活/娱乐区]"
        dynamic_zones[z1].append(d)

    # 输出报告
    p("=" * 80)
    p("  B站用户数据综合分析报告")
    p("=" * 80)

    p(f"\n[数据规模]")
    p(f"  用户: {username}")
    p(f"  视频: {len(all_videos)}个 | 收藏夹: {len(favorites)}个 | 转发动态: {len(dynamics)}条")

    p(f"\n{'='*80}")
    p(f"  分区全景 (一级分区)")
    p(f"{'='*80}")
    for zone, cnt in zone_l1_counter.most_common():
        pct = cnt / len(all_videos) * 100 if all_videos else 0
        bar = "#" * max(1, int(pct / 2))
        p(f"  {zone:20s} {cnt:2d}个 ({pct:4.1f}%) {bar}")

    p(f"\n{'='*80}")
    p(f"  二级细分详情")
    p(f"{'='*80}")
    for (z1, z2), cnt in zone_l2_counter.most_common():
        p(f"  {z1[1:-1]} > {z2}: {cnt}个")

    if meme_stats:
        p(f"\n{'='*80}")
        p(f"  梗/Meme 识别报告")
        p(f"{'='*80}")
        p(f"\n{'梗名称':35s} {'热度':>8s}")
        p(f"{'-'*45}")
        for total, meme_name, detail in meme_stats:
            bar = "#" * min(total, 20)
            p(f"  {meme_name:33s} {bar:12s} {total:3d}次")

    if dynamics:
        p(f"\n{'='*80}")
        p(f"  转发动态分类 ({len(dynamics)}条)")
        p(f"{'='*80}")
        for zone, items in sorted(dynamic_zones.items(), key=lambda x: -len(x[1])):
            p(f"\n  {zone} ({len(items)}条)")
            for d in items:
                ts = d.get('time', '')[:10]
                vt = d.get('video_title', '') or ''
                c = (d.get('content', '') or '')[:35]
                label = vt[:45] or c[:45] or f'[{d.get("type","")}]'
                author_info = f" @{d.get('original_author','')}" if d.get('original_author') else ""
                p(f"    [{ts}] {label}{author_info}")

    p(f"\n{'='*80}")
    p(f"  报告完")
    p(f"{'='*80}")

    return "\n".join(REPORT_LINES)


def save_report(uid: str = None) -> Path:
    """运行分析并保存报告文件"""
    if not uid:
        uid = get_uid()

    report_text = run_analysis(uid)
    report_path = BILI_FAV_HOME / f"analysis_report_{uid}.txt"
    report_path.write_text(report_text, encoding="utf-8")
    return report_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="B站数据分析")
    parser.add_argument("--uid", type=str, help="用户UID")
    args = parser.parse_args()

    report_path = save_report(args.uid)
    print(f"\n已保存: {report_path}")
