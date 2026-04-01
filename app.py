from datetime import datetime
from urllib.parse import quote
from flask import Flask, render_template, request

app = Flask(__name__)

# 表示件数の上限（将来的にここを変更するだけで調整可能）
MAX_DISPLAY = 10

# 対象エリア名（将来の多地域展開時にここを変更 or リスト化する）
AREA_NAME = "溝の口"

# ソートキー: 営業中 > 待ちレベル(green/yellow/red) > 徒歩分数
WAIT_LEVEL_ORDER = {"green": 0, "yellow": 1, "red": 2}

def sort_key(shop):
    is_closed = 0 if shop["is_open"] else 1
    wait_order = WAIT_LEVEL_ORDER.get(shop["wait_level"], 9)
    return (is_closed, wait_order, shop["walk_minutes"])


# ============================================================
# おすすめスコア計算
# ============================================================
# 「今行くならここ」選定用。待ち時間を最重要とし、
# 距離・更新の新しさ・報告傾向を補助的に加点減点する。
#
# 加点の目安:
#   wait_level green  : +100
#   wait_level yellow : +40
#   wait_level red    : -50
#   距離（徒歩）      : 最大 +15（walk_minutes が少ないほど有利）
#   更新の新しさ      : 最大 +10（20分以内の更新を優遇）
#   報告傾向          : 空いてた +10 / 混んでた or やや混み -10
# ============================================================

SCORE_BY_WAIT = {"green": 300, "yellow": 30, "red": -100}

def compute_recommend_score(shop):
    score = SCORE_BY_WAIT.get(shop["wait_level"], 0)

    # 距離：徒歩分数が少ないほど加点（最大 +15）
    score += max(0, 15 - shop["walk_minutes"])

    # 更新の新しさ：20分以内を加点（最大 +10）
    score += max(0, (20 - shop["updated_minutes_ago"]) * 0.5)

    # 報告傾向
    summary = shop.get("report_summary") or ""
    if "空いてた" in summary:
        score += 10
    elif "混んでた" in summary or "やや混み" in summary:
        score -= 10

    return score


# ============================================================
# 混雑スコア計算
# ============================================================
# スコアの考え方:
#   ≤ 0 → green（すぐ入れる）
#     1 → yellow（少し待つ）
#   ≥ 2 → red（待つかも）
#
# 入力項目:
#   base_crowd_score    : 店舗固有のベーススコア（0〜2）
#   popular_level       : 人気度（1=普通 / 2=人気 / 3=超人気）
#   fast_turnover       : 回転が早い店か（True/False）
#   lunch_peak_strong   : 昼ピークの影響が特に強い店か
#   dinner_peak_strong  : 夜ピークの影響が特に強い店か
# ============================================================

def compute_wait_level(shop, now=None):
    """
    現在時刻・曜日・店舗属性から混雑スコアを計算し、
    wait_level（green/yellow/red）と reason（根拠文）を返す。
    """
    if now is None:
        now = datetime.now()

    score = shop["base_crowd_score"]
    weekday = now.weekday()   # 0=月 〜 6=日
    t = now.hour + now.minute / 60  # 小数時刻（例: 12:30 → 12.5）
    is_weekend = weekday >= 5
    is_peak = False

    # ---- 時間帯ルール ----
    if not is_weekend:
        if 11.5 <= t < 13.5:
            score += 1
            is_peak = True
            if shop.get("lunch_peak_strong"):
                score += 1
        elif 18.0 <= t < 20.0:
            score += 1
            is_peak = True
            if shop.get("dinner_peak_strong"):
                score += 1
        elif 14.0 <= t < 17.0:
            score -= 1
    else:
        if 12.0 <= t < 14.0:
            score += 1
            is_peak = True
            if shop.get("lunch_peak_strong"):
                score += 1
        elif 18.0 <= t < 21.0:
            score += 1
            is_peak = True
            if shop.get("dinner_peak_strong"):
                score += 1

    # ---- 人気度補正 ----
    pop = shop.get("popular_level", 1)
    if pop >= 3:
        score += 1   # 超人気店は常にスコアを押し上げる

    # ---- 回転速度補正（混んでいるときに緩和） ----
    fast = shop.get("fast_turnover", False)
    if fast and score >= 2:
        score -= 1

    # ---- wait_level 決定 ----
    if score <= 0:
        level = "green"
    elif score == 1:
        level = "yellow"
    else:
        level = "red"

    # ---- reason ラベル生成（短文・判断補助） ----
    if level == "green":
        if fast and is_peak:
            reason = "回転が早く、比較的すぐ座れる"
        elif not is_weekend and 14.0 <= t < 17.0:
            reason = "今の時間は空いていることが多い"
        elif is_weekend and not is_peak:
            reason = "土日でもこの時間は並ばず入れることが多い"
        else:
            reason = "今なら並ばず入れる可能性が高い"
    elif level == "yellow":
        if fast:
            reason = "少し待つが、席は比較的早く空きやすい"
        elif is_weekend and is_peak:
            reason = "週末ピーク中のため、5〜10分待つかも"
        elif is_peak:
            reason = "ピーク中のため、5〜10分待ちになることが多い"
        elif pop >= 2:
            reason = "人気店のため、少し並ぶ可能性がある"
        else:
            reason = "5〜10分待つことが多い"
    else:  # red
        if pop >= 3 and is_peak:
            reason = "超人気店のピーク帯、行列は避けにくい"
        elif pop >= 3:
            reason = "常に行列が出やすい人気店"
        elif is_weekend and is_peak:
            reason = "週末ピーク帯、相当の待ちが予想される"
        elif is_peak:
            reason = "今の時間帯は10分以上の待ちになりやすい"
        else:
            reason = "ピーク外でも混みやすく、長め待ちになることが多い"

    return level, reason


# ============================================================
# 店舗データ（池袋駅徒歩圏）
# wait_level は実行時に compute_wait_level() で動的に決定する
# updated_minutes_ago : 最終更新からの経過分数（仮データ）
# report_summary      : ユーザー報告のサマリー（仮データ、None = 報告なし）
# ============================================================
ramen_shops = [
    {
        "name": "「溝の口」鶏白湯麺石田屋",
        "comment": "鶏白湯専門店。ウエストキャニオビル2F",
        "address": "神奈川県川崎市高津区溝口1-12-10",
        "website_url": "https://www.instagram.com/toripaitanishidaya/",
        "map_url": "https://maps.app.goo.gl/8fsBBVA2RUwpCpDf6",
        "route_url": "https://maps.app.goo.gl/8fsBBVA2RUwpCpDf6",
        "is_open": True,
        "walk_time": "溝の口駅から徒歩3分",  # 要確認
        "walk_minutes": 3,                   # 要確認
        "tag": "鶏白湯",
        "latitude": 35.6014,
        "longitude": 139.6070,
        "base_crowd_score": 1,
        "popular_level": 1,
        "fast_turnover": False,
        "lunch_peak_strong": True,
        "dinner_peak_strong": False,
        "updated_minutes_ago": 0,
        "report_summary": None,
    },
    {
        "name": "横浜家系ラーメン 武骨家 溝口店",
        "comment": "横浜家系。濃厚豚骨醤油スープ",
        "address": "神奈川県川崎市高津区溝口1-15-3",
        "website_url": None,
        "map_url": "https://maps.app.goo.gl/cEtgV1JuLJ1RWo8j7",
        "route_url": "https://maps.app.goo.gl/cEtgV1JuLJ1RWo8j7",
        "is_open": True,
        "walk_time": "溝の口駅から徒歩3分",  # 要確認
        "walk_minutes": 3,                   # 要確認
        "tag": "家系",
        "latitude": 35.6012,
        "longitude": 139.6075,
        "base_crowd_score": 1,
        "popular_level": 1,
        "fast_turnover": True,
        "lunch_peak_strong": True,
        "dinner_peak_strong": False,
        "updated_minutes_ago": 0,
        "report_summary": None,
    },
    {
        "name": "麺屋ななほし",
        "comment": "溝の口エリアの中華そば店",
        "address": "神奈川県川崎市高津区坂戸1-1-6",
        "website_url": None,
        "map_url": "https://maps.app.goo.gl/PhbJkakupgPFtsEh7",
        "route_url": "https://maps.app.goo.gl/PhbJkakupgPFtsEh7",
        "is_open": True,
        "walk_time": "溝の口駅から徒歩10分",
        "walk_minutes": 10,
        "tag": "中華そば",
        "latitude": 35.5998,
        "longitude": 139.6095,
        "base_crowd_score": 1,
        "popular_level": 1,
        "fast_turnover": False,
        "lunch_peak_strong": True,
        "dinner_peak_strong": False,
        "updated_minutes_ago": 0,
        "report_summary": None,
    },
    {
        "name": "まっち棒",
        "comment": "和歌山ラーメンの専門店。サウスウィング1F",
        "address": "神奈川県川崎市高津区溝口2-3-7",
        "website_url": "https://match-bou.jp/",
        "map_url": "https://maps.app.goo.gl/Cv4nnUfbT6mqhejc7",
        "route_url": "https://maps.app.goo.gl/Cv4nnUfbT6mqhejc7",
        "is_open": True,
        "walk_time": "溝の口駅から徒歩5分",  # 要確認
        "walk_minutes": 5,                   # 要確認
        "tag": "和歌山ラーメン",
        "latitude": 35.6008,
        "longitude": 139.6082,
        "base_crowd_score": 1,
        "popular_level": 1,
        "fast_turnover": False,
        "lunch_peak_strong": True,
        "dinner_peak_strong": False,
        "updated_minutes_ago": 0,
        "report_summary": None,
    },
    {
        "name": "つけめんTETSU 溝の口店",
        "comment": "つけ麺の人気チェーン。溝の口店",
        "address": "神奈川県川崎市高津区溝口2-8-12",
        "website_url": "https://www.tetsu102.com/en/",
        "map_url": "https://maps.app.goo.gl/JwfvpSFEkiAwgGCx8",
        "route_url": "https://maps.app.goo.gl/JwfvpSFEkiAwgGCx8",
        "is_open": True,
        "walk_time": "溝の口駅から徒歩5分",  # 要確認
        "walk_minutes": 5,                   # 要確認
        "tag": "つけ麺",
        "latitude": 35.6003,
        "longitude": 139.6090,
        "base_crowd_score": 1,
        "popular_level": 1,
        "fast_turnover": False,
        "lunch_peak_strong": True,
        "dinner_peak_strong": False,
        "updated_minutes_ago": 0,
        "report_summary": None,
    },
    {
        "name": "らーめん和蔵",
        "comment": "豚骨ラーメン。SKIPSビルB1F",
        "address": "神奈川県川崎市高津区久本1-2-2",
        "website_url": "https://www.instagram.com/ramenkazukura/",
        "map_url": "https://maps.app.goo.gl/RjYFA4ruExUAqXcD9",
        "route_url": "https://maps.app.goo.gl/RjYFA4ruExUAqXcD9",
        "is_open": True,
        "walk_time": "溝の口駅から徒歩5分",  # 要確認
        "walk_minutes": 5,                   # 要確認
        "tag": "豚骨",
        "latitude": 35.6005,
        "longitude": 139.6088,
        "base_crowd_score": 1,
        "popular_level": 1,
        "fast_turnover": False,
        "lunch_peak_strong": True,
        "dinner_peak_strong": False,
        "updated_minutes_ago": 0,
        "report_summary": None,
    },
]

# 池袋エリアバックアップ（後で戻す用）
ikbukuro_shops_backup = list(ramen_shops)


@app.route("/")
def index():
    return render_template("index.html", area_name=AREA_NAME)


@app.route("/result")
def result():
    max_walk_str = request.args.get("max_walk")
    mode = request.args.get("mode", "")

    # 現在時刻をもとに全店舗の wait_level と reason を動的に計算
    now = datetime.now()
    enriched = []
    for shop in ramen_shops:
        s = dict(shop)
        s["wait_level"], s["reason"] = compute_wait_level(s, now)
        s["area"] = s.get("area", AREA_NAME)
        if not s.get("route_url"):
            s["route_url"] = "https://www.google.com/maps/dir/?api=1&destination=" + quote(s["address"]) + "&travelmode=walking"
        enriched.append(s)

    # 徒歩圏フィルタ
    if max_walk_str and max_walk_str.isdigit():
        max_walk = int(max_walk_str)
        filtered = [s for s in enriched if s["walk_minutes"] <= max_walk]
        filter_label = f"溝の口駅から徒歩{max_walk}分以内の営業中店舗"
    else:
        max_walk = None
        filtered = enriched
        filter_label = "溝の口駅周辺の営業中店舗"

    # 営業中のみ表示（デフォルト動作）
    # 将来 "閉店中も含む" 表示が必要になった場合は、ここで条件を分岐させる
    filtered = [s for s in filtered if s["is_open"]]

    # 待ちレベル・徒歩分数の順でソート（JS未使用時のフォールバック）
    filtered.sort(key=sort_key)

    total_count = len(filtered)

    # 表示件数を上限に制限（MAX_DISPLAY を変更するだけで調整可能）
    displayed = filtered[:MAX_DISPLAY]

    # おすすめスコアで「今行くならここ」店舗を選定
    if displayed:
        featured_shop = max(displayed, key=compute_recommend_score)
        other_shops   = [s for s in displayed if s is not featured_shop]
    else:
        featured_shop = None
        other_shops   = []

    return render_template(
        "result.html",
        featured_shop=featured_shop,
        other_shops=other_shops,
        all_shops_json=filtered,   # JS の現在地ソートに使用（全件・フィルタ済み）
        filter_label=filter_label,
        max_walk=max_walk,
        mode=mode,
        total_count=total_count,
        max_display=MAX_DISPLAY,
        area_name=AREA_NAME,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
