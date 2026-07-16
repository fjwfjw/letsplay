"""根据用户 IP 确定性生成昵称与头像（DiceBear bottts-neutral）。同一 IP 永远得到同一身份。

增强差异化：即使同一 IP 段（如 10.0.0.81 vs 10.0.0.82）也会产生明显不同的昵称和头像。
"""
import hashlib
import random as _random

# DiceBear bottts-neutral 风格头像 API
DICEBEAR_BASE = "https://api.dicebear.com/7.x/bottts-neutral/svg?seed="

# 形容词池：运动/竞技感
ADJECTIVES = [
    "冲刺的","跳跃的","翻滚的","旋转的","弹动的","摇摆的",
    "滑行的","蹬踏的","摆动的","抖动的","抛接的","闪避的",
    "加速的","腾空的","扭转的","漂移的","反弹的","跨步的",
    "俯冲的","起跑的","菜菜的","牛逼的","灵动的","暴走的",
    "飘逸的","稳健的","凶猛的","狡猾的","顽强的","冷静的",
    "英勇的"
]

# 动物池：以鸟类为主（呼应羽毛球）
ANIMALS = [
    "隼", "鹰", "鸭子", "菜鸟", "雕", "大鹅","猹",
    "猫咪", "狗子", "兔子", "熊", "麋鹿", "狐狸",
    "鲸", "企鹅", "松鼠", "刺猬", "熊猫", "考拉",
    "水獭", "仓鼠", "猎豹", "海豚", "鹦鹉", "火烈鸟",
    "鹦鹉"
]

# 头像配色方案：前景色 / 背景色
PALETTE = [
    ["#d4ff3a", "#0a0e1a"],  # lime / night
    ["#ff5e3a", "#0a0e1a"],  # coral / night
    ["#3ad4ff", "#0a0e1a"],  # cyan / night
    ["#ffd23a", "#0a0e1a"],  # gold / night
    ["#ff3a8c", "#0a0e1a"],  # magenta / night
    ["#3aff9e", "#0a0e1a"],  # mint / night
    ["#a23aff", "#0a0e1a"],  # violet / night
    ["#3affd2", "#0a0e1a"],  # aqua / night
    ["#ff8c3a", "#0a0e1a"],  # orange / night
    ["#3aff6e", "#0a0e1a"],  # green / night
    ["#ff3adc", "#0a0e1a"],  # pink / night
    ["#3adcff", "#0a0e1a"],  # sky / night
]


def _hash_ip(ip: str) -> int:
    """将 IP 哈希为稳定整数。使用双重哈希增强末位差异。"""
    # 第一轮：完整 IP 哈希
    h1 = hashlib.sha256(ip.encode("utf-8")).hexdigest()
    # 第二轮：将 IP 倒序再哈希，让末位变化产生更大差异
    h2 = hashlib.sha256(ip[::-1].encode("utf-8")).hexdigest()
    # 混合两个哈希，确保最后一位的变化也能大幅影响结果
    combined = hashlib.sha256((h1 + h2).encode("utf-8")).hexdigest()
    return int(combined, 16)


def generate_identity(ip: str) -> dict:
    """根据 IP 生成 {id, nickname, avatar_svg}。"""
    seed = _hash_ip(ip)
    adj = ADJECTIVES[seed % len(ADJECTIVES)]
    animal = ANIMALS[(seed >> 8) % len(ANIMALS)]
    number = (seed >> 16) % 900 + 100
    nickname = f"{adj}{animal}{number}"

    avatar = _build_avatar(seed)
    return {
        "id": f"u{seed % 0xFFFFFFFF:08x}",
        "nickname": nickname,
        "avatar": avatar,
    }


def _build_avatar(seed: int) -> str:
    """生成 DiceBear bottts-neutral 头像（img 标签，确定性）。"""
    seed_str = f"letsplay-{seed:x}"
    return f'<img src="{DICEBEAR_BASE}{seed_str}" alt="avatar" style="width:100%;height:100%;display:block;" />'


def generate_random_avatar() -> str:
    """生成随机 DiceBear 头像（用于注册时换头像）。"""
    seed_str = f"letsplay-{_random.randint(0, 2**63):x}"
    return f'<img src="{DICEBEAR_BASE}{seed_str}" alt="avatar" style="width:100%;height:100%;display:block;" />'
