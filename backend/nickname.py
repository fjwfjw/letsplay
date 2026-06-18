"""根据用户 IP 确定性生成昵称与头像（SVG）。同一 IP 永远得到同一身份。

增强差异化：即使同一 IP 段（如 10.0.0.81 vs 10.0.0.82）也会产生明显不同的昵称和头像。
"""
import hashlib

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
    """生成确定性几何头像 SVG（5x5 对称色块，类似 identicon）。

    增强差异化：使用更多 seed 位来决定颜色和图案。
    """
    pair = PALETTE[(seed >> 24) % len(PALETTE)]
    fg, bg = pair[0], pair[1]

    # 5x5 对称矩阵：左 3 列决定整行
    cells = []
    bit = seed >> 32
    for row in range(5):
        for col in range(3):  # 只取左 3 列
            on = (bit >> (row * 3 + col)) & 1
            if on:
                cells.append((col, row))
                if col < 2:  # 镜像到右侧
                    cells.append((4 - col, row))
                else:
                    if (col, row) not in cells:
                        cells.append((4 - col, row))

    rects = ""
    for (cx, cy) in dict.fromkeys(cells):  # 去重保序
        rects += f'<rect x="{cx*8}" y="{cy*8}" width="8" height="8" fill="{fg}"/>'

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" '
        f'shape-rendering="crispEdges">'
        f'<rect width="40" height="40" fill="{bg}"/>'
        f"{rects}"
        f"</svg>"
    )
    return svg
