"""中小学生隐私过滤（确定性，写记忆之前必经，护栏之一，自进化不能改）。

不记：真实姓名、住址、学校 / 班级、电话、身份证号、邮箱、QQ / 微信号、生日。
做法：命中的片段整体替换成「〔已隐去〕」；去掉之后剩下的有效内容太少（< 4 个字），整条拒绝写入。
"""
import re

MASK = "〔已隐去〕"
_CN = r"[\u4e00-\u9fff]"
RULES = [
    ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)|(?<!\d)0\d{2,3}-?\d{7,8}(?!\d)")),
    ("id", re.compile(r"(?<![0-9A-Za-z])\d{17}[\dXx](?![0-9A-Za-z])")),
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("im", re.compile(r"(?:QQ|qq|微信|vx|VX|wx|WX)\s*(?:号)?\s*[:：是]?\s*[A-Za-z0-9_-]{5,}")),
    ("name", re.compile(r"(?:我叫|我的名字(?:是|叫)|名字叫|本名|真名(?:是|叫)?|姓名[:：]?)\s*" + _CN + r"{1,4}")),
    ("name2", re.compile(r"我(?:姓)" + _CN + r"(?:，|,|\s)*(?:叫" + _CN + r"{1,3})?")),
    ("school", re.compile(_CN + r"{1,12}?(?:小学|中学|初中|高中|学校|一中|二中|三中|实验学校|外国语学校|附中|附小)")),
    ("class", re.compile(r"[一二三四五六七八九十\d]{1,2}\s*(?:年级)?\s*[（(]?\s*[一二三四五六七八九十\d]{1,2}\s*[）)]?\s*班")),
    ("addr", re.compile(_CN + r"{2,10}(?:路|街|巷|大道|弄|小区|花园|新村|公寓)\s*\d+\s*(?:号|弄|栋|幢)?(?:\s*\d+\s*(?:室|号))?|"
                        + _CN + r"{2,4}(?:省|自治区)" + _CN + r"{2,4}市|" + _CN + r"{2,4}市" + _CN + r"{2,4}(?:区|县)|\d+\s*(?:栋|单元|号楼)")),
    ("addr2", re.compile(r"(?:住在|家在|我家住|住址[:：]?)\s*\S{1,20}")),
    ("birthday", re.compile(r"(?:生日|出生)(?:是|在|于)?\s*\d{1,4}\s*[年/-]?\s*\d{1,2}\s*[月/-]\s*\d{1,2}\s*日?")),
]
MIN_LEFT = 4


def scrub(text):
    """返回 (清洗后的文本, 命中的规则名列表)。"""
    t = str(text or "")
    hits = []
    for name, rx in RULES:
        if rx.search(t):
            hits.append(name)
            t = rx.sub(MASK, t)
    t = re.sub(r"(?:" + re.escape(MASK) + r"\s*)+", MASK, t).strip()
    return t, hits


def filter_for_memory(text):
    """写记忆前调用：返回清洗后的文本；清洗后有效内容太少则返回 None（不写）。"""
    t, hits = scrub(text)
    left = re.sub(re.escape(MASK) + r"|[\s，。,.!！?？:：;；、]", "", t)
    if len(left) < MIN_LEFT:
        return None
    return t


def has_identity(text):
    return bool(scrub(text)[1])
