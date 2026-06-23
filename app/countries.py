"""国家 / 地区数据，供 /api/countries 选择器使用。

每条记录提供 ISO-3166 alpha-2 代码、中文名、英文名、国际区号；
国旗 emoji 由代码的区域指示符自动合成，无需手工维护。
列表覆盖常见 eSIM/保号目的地，可按需继续补充。
"""

# (code, 中文名, English, calling code)
_RAW = [
    ("CN", "中国", "China", "86"),
    ("HK", "中国香港", "Hong Kong", "852"),
    ("MO", "中国澳门", "Macau", "853"),
    ("TW", "中国台湾", "Taiwan", "886"),
    ("JP", "日本", "Japan", "81"),
    ("KR", "韩国", "South Korea", "82"),
    ("KP", "朝鲜", "North Korea", "850"),
    ("MN", "蒙古", "Mongolia", "976"),
    ("SG", "新加坡", "Singapore", "65"),
    ("MY", "马来西亚", "Malaysia", "60"),
    ("TH", "泰国", "Thailand", "66"),
    ("VN", "越南", "Vietnam", "84"),
    ("PH", "菲律宾", "Philippines", "63"),
    ("ID", "印度尼西亚", "Indonesia", "62"),
    ("KH", "柬埔寨", "Cambodia", "855"),
    ("LA", "老挝", "Laos", "856"),
    ("MM", "缅甸", "Myanmar", "95"),
    ("BN", "文莱", "Brunei", "673"),
    ("IN", "印度", "India", "91"),
    ("PK", "巴基斯坦", "Pakistan", "92"),
    ("BD", "孟加拉国", "Bangladesh", "880"),
    ("LK", "斯里兰卡", "Sri Lanka", "94"),
    ("NP", "尼泊尔", "Nepal", "977"),
    ("MV", "马尔代夫", "Maldives", "960"),
    ("KZ", "哈萨克斯坦", "Kazakhstan", "7"),
    ("UZ", "乌兹别克斯坦", "Uzbekistan", "998"),
    ("AE", "阿联酋", "United Arab Emirates", "971"),
    ("SA", "沙特阿拉伯", "Saudi Arabia", "966"),
    ("QA", "卡塔尔", "Qatar", "974"),
    ("KW", "科威特", "Kuwait", "965"),
    ("BH", "巴林", "Bahrain", "973"),
    ("OM", "阿曼", "Oman", "968"),
    ("IL", "以色列", "Israel", "972"),
    ("TR", "土耳其", "Turkey", "90"),
    ("IR", "伊朗", "Iran", "98"),
    ("IQ", "伊拉克", "Iraq", "964"),
    ("JO", "约旦", "Jordan", "962"),
    ("LB", "黎巴嫩", "Lebanon", "961"),
    ("GE", "格鲁吉亚", "Georgia", "995"),
    ("AM", "亚美尼亚", "Armenia", "374"),
    ("AZ", "阿塞拜疆", "Azerbaijan", "994"),
    ("US", "美国", "United States", "1"),
    ("CA", "加拿大", "Canada", "1"),
    ("MX", "墨西哥", "Mexico", "52"),
    ("BR", "巴西", "Brazil", "55"),
    ("AR", "阿根廷", "Argentina", "54"),
    ("CL", "智利", "Chile", "56"),
    ("CO", "哥伦比亚", "Colombia", "57"),
    ("PE", "秘鲁", "Peru", "51"),
    ("VE", "委内瑞拉", "Venezuela", "58"),
    ("EC", "厄瓜多尔", "Ecuador", "593"),
    ("CR", "哥斯达黎加", "Costa Rica", "506"),
    ("PA", "巴拿马", "Panama", "507"),
    ("GB", "英国", "United Kingdom", "44"),
    ("IE", "爱尔兰", "Ireland", "353"),
    ("FR", "法国", "France", "33"),
    ("DE", "德国", "Germany", "49"),
    ("NL", "荷兰", "Netherlands", "31"),
    ("BE", "比利时", "Belgium", "32"),
    ("LU", "卢森堡", "Luxembourg", "352"),
    ("CH", "瑞士", "Switzerland", "41"),
    ("AT", "奥地利", "Austria", "43"),
    ("ES", "西班牙", "Spain", "34"),
    ("PT", "葡萄牙", "Portugal", "351"),
    ("IT", "意大利", "Italy", "39"),
    ("GR", "希腊", "Greece", "30"),
    ("SE", "瑞典", "Sweden", "46"),
    ("NO", "挪威", "Norway", "47"),
    ("DK", "丹麦", "Denmark", "45"),
    ("FI", "芬兰", "Finland", "358"),
    ("IS", "冰岛", "Iceland", "354"),
    ("PL", "波兰", "Poland", "48"),
    ("CZ", "捷克", "Czechia", "420"),
    ("SK", "斯洛伐克", "Slovakia", "421"),
    ("HU", "匈牙利", "Hungary", "36"),
    ("RO", "罗马尼亚", "Romania", "40"),
    ("BG", "保加利亚", "Bulgaria", "359"),
    ("HR", "克罗地亚", "Croatia", "385"),
    ("SI", "斯洛文尼亚", "Slovenia", "386"),
    ("RS", "塞尔维亚", "Serbia", "381"),
    ("UA", "乌克兰", "Ukraine", "380"),
    ("RU", "俄罗斯", "Russia", "7"),
    ("BY", "白俄罗斯", "Belarus", "375"),
    ("LT", "立陶宛", "Lithuania", "370"),
    ("LV", "拉脱维亚", "Latvia", "371"),
    ("EE", "爱沙尼亚", "Estonia", "372"),
    ("EG", "埃及", "Egypt", "20"),
    ("MA", "摩洛哥", "Morocco", "212"),
    ("TN", "突尼斯", "Tunisia", "216"),
    ("DZ", "阿尔及利亚", "Algeria", "213"),
    ("ZA", "南非", "South Africa", "27"),
    ("NG", "尼日利亚", "Nigeria", "234"),
    ("KE", "肯尼亚", "Kenya", "254"),
    ("ET", "埃塞俄比亚", "Ethiopia", "251"),
    ("GH", "加纳", "Ghana", "233"),
    ("TZ", "坦桑尼亚", "Tanzania", "255"),
    ("AU", "澳大利亚", "Australia", "61"),
    ("NZ", "新西兰", "New Zealand", "64"),
    ("FJ", "斐济", "Fiji", "679"),
    ("PG", "巴布亚新几内亚", "Papua New Guinea", "675"),
]


import json
import os

# 已有的中文名作为本地化覆盖来源（country_map.json 只带英文名）。
_ZH = {code: name for code, name, _english, _calling in _RAW}

# 补全其余 ISO 地区的中文名，让选择器全部显示中文。
_ZH_EXTRA = {
    "AC": "阿森松岛", "AD": "安道尔", "AF": "阿富汗", "AG": "安提瓜和巴布达", "AI": "安圭拉",
    "AL": "阿尔巴尼亚", "AO": "安哥拉", "AQ": "南极洲", "AS": "美属萨摩亚", "AW": "阿鲁巴",
    "AX": "奥兰群岛", "BA": "波斯尼亚和黑塞哥维那", "BB": "巴巴多斯", "BF": "布基纳法索",
    "BI": "布隆迪", "BJ": "贝宁", "BL": "圣巴泰勒米", "BM": "百慕大", "BO": "玻利维亚",
    "BQ": "荷兰加勒比区", "BS": "巴哈马", "BT": "不丹", "BV": "布韦岛", "BW": "博茨瓦纳",
    "BZ": "伯利兹", "CC": "科科斯（基林）群岛", "CD": "刚果（金）", "CF": "中非共和国",
    "CG": "刚果（布）", "CI": "科特迪瓦", "CK": "库克群岛", "CM": "喀麦隆", "CP": "克利珀顿岛",
    "CU": "古巴", "CV": "佛得角", "CW": "库拉索", "CX": "圣诞岛", "CY": "塞浦路斯",
    "DG": "迪戈加西亚岛", "DJ": "吉布提", "DM": "多米尼克", "DO": "多米尼加共和国",
    "EA": "休达和梅利利亚", "EH": "西撒哈拉", "ER": "厄立特里亚", "FK": "福克兰群岛",
    "FM": "密克罗尼西亚", "FO": "法罗群岛", "GA": "加蓬", "GD": "格林纳达", "GF": "法属圭亚那",
    "GG": "根西", "GI": "直布罗陀", "GL": "格陵兰", "GM": "冈比亚", "GN": "几内亚",
    "GP": "瓜德罗普", "GQ": "赤道几内亚", "GT": "危地马拉", "GU": "关岛", "GW": "几内亚比绍",
    "GY": "圭亚那", "HM": "赫德岛和麦克唐纳群岛", "HN": "洪都拉斯", "HT": "海地",
    "IC": "加那利群岛", "IM": "马恩岛", "IO": "英属印度洋领地", "JE": "泽西", "JM": "牙买加",
    "KG": "吉尔吉斯斯坦", "KI": "基里巴斯", "KM": "科摩罗", "KN": "圣基茨和尼维斯",
    "KY": "开曼群岛", "LC": "圣卢西亚", "LI": "列支敦士登", "LR": "利比里亚", "LS": "莱索托",
    "LY": "利比亚", "MC": "摩纳哥", "MD": "摩尔多瓦", "ME": "黑山", "MF": "法属圣马丁",
    "MG": "马达加斯加", "MH": "马绍尔群岛", "MK": "北马其顿", "ML": "马里", "MP": "北马里亚纳群岛",
    "MQ": "马提尼克", "MR": "毛里塔尼亚", "MS": "蒙特塞拉特", "MT": "马耳他", "MU": "毛里求斯",
    "MW": "马拉维", "MZ": "莫桑比克", "NA": "纳米比亚", "NC": "新喀里多尼亚", "NE": "尼日尔",
    "NF": "诺福克岛", "NI": "尼加拉瓜", "NR": "瑙鲁", "NU": "纽埃", "PF": "法属波利尼西亚",
    "PM": "圣皮埃尔和密克隆", "PR": "波多黎各", "PS": "巴勒斯坦", "PW": "帕劳", "PY": "巴拉圭",
    "RE": "留尼汪", "RW": "卢旺达", "SB": "所罗门群岛", "SC": "塞舌尔", "SD": "苏丹",
    "SH": "圣赫勒拿", "SJ": "斯瓦尔巴和扬马延", "SL": "塞拉利昂", "SM": "圣马力诺",
    "SN": "塞内加尔", "SO": "索马里", "SR": "苏里南", "SS": "南苏丹", "ST": "圣多美和普林西比",
    "SV": "萨尔瓦多", "SX": "荷属圣马丁", "SY": "叙利亚", "SZ": "斯威士兰",
    "TC": "特克斯和凯科斯群岛", "TD": "乍得", "TF": "法属南方和南极洲领地", "TG": "多哥",
    "TJ": "塔吉克斯坦", "TK": "托克劳", "TL": "东帝汶", "TM": "土库曼斯坦", "TO": "汤加",
    "TT": "特立尼达和多巴哥", "TV": "图瓦卢", "UG": "乌干达", "UY": "乌拉圭", "VA": "梵蒂冈",
    "VC": "圣文森特和格林纳丁斯", "VG": "英属维尔京群岛", "VI": "美属维尔京群岛", "VU": "瓦努阿图",
    "WF": "瓦利斯和富图纳", "WS": "萨摩亚", "XK": "科索沃", "YE": "也门", "YT": "马约特",
    "ZM": "赞比亚", "ZW": "津巴布韦",
}

# 现有 _RAW 的中文名优先，其余用补全表。
_ZH_ALL = dict(_ZH_EXTRA)
_ZH_ALL.update(_ZH)


def flag_from_code(code):
    """2 字母 ISO 代码 → 国旗 emoji；无效则返回地球。"""
    code = (code or "").strip().upper()
    if len(code) != 2 or not code.isalpha():
        return "🌐"
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in code)


def code_from_flag(flag):
    """国旗 emoji → 2 字母 ISO 代码；无法识别则返回空串。"""
    scalars = [ord(ch) for ch in (flag or "")]
    letters = [chr(ord("A") + s - 0x1F1E6) for s in scalars if 0x1F1E6 <= s <= 0x1F1FF]
    return "".join(letters) if len(letters) == 2 else ""


def _load_map():
    path = os.path.join(os.path.dirname(__file__), "country_map.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("countries", [])
    except (OSError, ValueError):
        return []


_MAP = _load_map()

COUNTRIES = []
for entry in _MAP:
    code = entry.get("countryCode", "")
    english = entry.get("englishName", "") or ""
    calling = (entry.get("callingCodes") or [""])[0].lstrip("+")
    COUNTRIES.append(
        {
            "code": code,
            "name": _ZH_ALL.get(code) or english or code,
            "english": english,
            "flag": entry.get("flag") or flag_from_code(code),
            "calling": calling,
            "bgAsset": entry.get("cardBackgroundAssetName", "") or "",
            "bgFile": entry.get("cardBackgroundFile", "") or "",
        }
    )

# 兜底：若 country_map.json 缺失，退回手写列表。
if not COUNTRIES:
    COUNTRIES = [
        {"code": c, "name": n, "english": e, "flag": flag_from_code(c), "calling": cc, "bgAsset": "", "bgFile": ""}
        for c, n, e, cc in _RAW
    ]

NAME_BY_CODE = {c["code"]: c["name"] for c in COUNTRIES}
CODE_TO_ASSET = {c["code"]: c["bgAsset"] for c in COUNTRIES if c["bgAsset"]}
ASSET_TO_FILE = {c["bgAsset"]: c["bgFile"] for c in COUNTRIES if c["bgAsset"] and c["bgFile"]}
