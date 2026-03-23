from flask import Flask, render_template, request

app = Flask(__name__)

# 表示件数の上限（将来的にここを変更するだけで調整可能）
MAX_DISPLAY = 10

# 仮データ（池袋駅徒歩圏）
ramen_shops = [
    {
        "name": "五行 池袋西口店",
        "wait_level": "green",
        "comment": "ガラガラです、すぐ座れます",
        "address": "東京都豊島区西池袋1-10-3",
        "map_url": "https://maps.google.com/?q=五行+池袋西口",
        "is_open": True,
        "walk_time": "池袋駅から徒歩2分",
        "walk_minutes": 2,
        "tag": "焦がし味噌"
    },
    {
        "name": "つけ麺 道 池袋東口",
        "wait_level": "yellow",
        "comment": "少し待つけど食べる価値あり",
        "address": "東京都豊島区東池袋1-6-3",
        "map_url": "https://maps.google.com/?q=つけ麺+道+池袋東口",
        "is_open": True,
        "walk_time": "池袋駅から徒歩2分",
        "walk_minutes": 2,
        "tag": "つけ麺"
    },
    {
        "name": "博多風龍 池袋店",
        "wait_level": "green",
        "comment": "空席あり、今が狙い目",
        "address": "東京都豊島区西池袋1-15-2",
        "map_url": "https://maps.google.com/?q=博多風龍+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩3分",
        "walk_minutes": 3,
        "tag": "博多豚骨"
    },
    {
        "name": "無敵家",
        "wait_level": "yellow",
        "comment": "5分くらいでいけそう",
        "address": "東京都豊島区南池袋1-17-1",
        "map_url": "https://maps.google.com/?q=無敵家+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩3分",
        "walk_minutes": 3,
        "tag": "濃厚豚骨"
    },
    {
        "name": "麺屋 武蔵 池袋店",
        "wait_level": "red",
        "comment": "行列あり、20分待ちくらい",
        "address": "東京都豊島区南池袋1-16-10",
        "map_url": "https://maps.google.com/?q=麺屋+武蔵+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩3分",
        "walk_minutes": 3,
        "tag": "濃厚煮干し"
    },
    {
        "name": "ラーメン二郎 池袋東口店",
        "wait_level": "green",
        "comment": "今ならスッと入れる",
        "address": "東京都豊島区東池袋1-13-12",
        "map_url": "https://maps.google.com/?q=ラーメン二郎+池袋東口店",
        "is_open": True,
        "walk_time": "池袋駅から徒歩4分",
        "walk_minutes": 4,
        "tag": "ガッツリ系"
    },
    {
        "name": "頑者 池袋店",
        "wait_level": "yellow",
        "comment": "数人並んでる、10分くらい",
        "address": "東京都豊島区東池袋1-12-6",
        "map_url": "https://maps.google.com/?q=頑者+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩4分",
        "walk_minutes": 4,
        "tag": "家系"
    },
    {
        "name": "らーめん壱角家 池袋西口店",
        "wait_level": "yellow",
        "comment": "カウンター埋まり気味",
        "address": "東京都豊島区西池袋2-28-7",
        "map_url": "https://maps.google.com/?q=壱角家+池袋西口",
        "is_open": True,
        "walk_time": "池袋駅から徒歩4分",
        "walk_minutes": 4,
        "tag": "家系"
    },
    {
        "name": "鷹の目 池袋",
        "wait_level": "green",
        "comment": "今すぐ入れます",
        "address": "東京都豊島区西池袋2-18-4",
        "map_url": "https://maps.google.com/?q=鷹の目+池袋",
        "is_open": False,
        "walk_time": "池袋駅から徒歩5分",
        "walk_minutes": 5,
        "tag": "塩ラーメン"
    },
    {
        "name": "らあめん花月嵐 池袋店",
        "wait_level": "green",
        "comment": "混んでないです",
        "address": "東京都豊島区東池袋1-28-5",
        "map_url": "https://maps.google.com/?q=花月嵐+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩5分",
        "walk_minutes": 5,
        "tag": "チェーン・味噌"
    },
    {
        "name": "麺創房 無敵家 別館",
        "wait_level": "red",
        "comment": "今はちょい混み",
        "address": "東京都豊島区南池袋1-21-5",
        "map_url": "https://maps.google.com/?q=麺創房+無敵家+別館+池袋",
        "is_open": False,
        "walk_time": "池袋駅から徒歩5分",
        "walk_minutes": 5,
        "tag": "あっさり醤油"
    },
    {
        "name": "鶏白湯ラーメン 鳥の庄",
        "wait_level": "green",
        "comment": "空いてます、すぐ入れます",
        "address": "東京都豊島区西池袋3-26-5",
        "map_url": "https://maps.google.com/?q=鶏白湯ラーメン+鳥の庄+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩6分",
        "walk_minutes": 6,
        "tag": "鶏白湯"
    },
    {
        "name": "東京豚骨拉麺 ばんから 池袋店",
        "wait_level": "yellow",
        "comment": "少し待ちあり、回転は普通",
        "address": "東京都豊島区東池袋1-23-14",
        "map_url": "https://maps.google.com/?q=ばんから+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩6分",
        "walk_minutes": 6,
        "tag": "豚骨醤油"
    },
    {
        "name": "麺屋 こころ 池袋",
        "wait_level": "green",
        "comment": "すんなり入れました",
        "address": "東京都豊島区東池袋2-3-7",
        "map_url": "https://maps.google.com/?q=麺屋+こころ+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩6分",
        "walk_minutes": 6,
        "tag": "醤油ラーメン"
    },
    {
        "name": "池袋大勝軒",
        "wait_level": "yellow",
        "comment": "少し並んでるけど回転早め",
        "address": "東京都豊島区南池袋2-42-7",
        "map_url": "https://maps.google.com/?q=池袋大勝軒",
        "is_open": True,
        "walk_time": "池袋駅から徒歩7分",
        "walk_minutes": 7,
        "tag": "もりそば・つけ麺"
    },
    {
        "name": "麺屋 一燈 池袋",
        "wait_level": "red",
        "comment": "大人気、列がのびてます",
        "address": "東京都豊島区南池袋2-26-7",
        "map_url": "https://maps.google.com/?q=麺屋+一燈+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩8分",
        "walk_minutes": 8,
        "tag": "煮干し醤油"
    },
    {
        "name": "凪 煮干しそば 池袋",
        "wait_level": "red",
        "comment": "外まで並んでます",
        "address": "東京都豊島区南池袋2-7-11",
        "map_url": "https://maps.google.com/?q=凪+煮干しそば+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩8分",
        "walk_minutes": 8,
        "tag": "煮干し"
    },
    {
        "name": "ソラノイロ 池袋",
        "wait_level": "green",
        "comment": "穴場です、すぐ座れます",
        "address": "東京都豊島区南池袋2-18-5",
        "map_url": "https://maps.google.com/?q=ソラノイロ+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩8分",
        "walk_minutes": 8,
        "tag": "ベジ・塩"
    },
    {
        "name": "麺処 花田 池袋店",
        "wait_level": "green",
        "comment": "待ちなし、静かです",
        "address": "東京都豊島区東池袋2-14-3",
        "map_url": "https://maps.google.com/?q=麺処+花田+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩9分",
        "walk_minutes": 9,
        "tag": "味噌ラーメン"
    },
    {
        "name": "麺や 七彩 池袋",
        "wait_level": "yellow",
        "comment": "少し待ちあり",
        "address": "東京都豊島区東池袋2-56-3",
        "map_url": "https://maps.google.com/?q=麺や+七彩+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩9分",
        "walk_minutes": 9,
        "tag": "手打ち中華そば"
    },
    {
        "name": "中華そば 青葉 池袋",
        "wait_level": "yellow",
        "comment": "ほどよく混んでる感じ",
        "address": "東京都豊島区南池袋3-12-8",
        "map_url": "https://maps.google.com/?q=中華そば+青葉+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩10分",
        "walk_minutes": 10,
        "tag": "中華そば"
    },
    {
        "name": "担々麺 吉虎 池袋",
        "wait_level": "green",
        "comment": "空いてます",
        "address": "東京都豊島区西池袋4-5-9",
        "map_url": "https://maps.google.com/?q=担々麺+吉虎+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩11分",
        "walk_minutes": 11,
        "tag": "担々麺"
    },
    {
        "name": "とんこつラーメン 天神 池袋",
        "wait_level": "green",
        "comment": "ゆったり食べられます",
        "address": "東京都豊島区東池袋3-8-12",
        "map_url": "https://maps.google.com/?q=とんこつラーメン+天神+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩12分",
        "walk_minutes": 12,
        "tag": "博多豚骨"
    },
    {
        "name": "麺屋 龍之介 池袋",
        "wait_level": "yellow",
        "comment": "行列が少し出てます",
        "address": "東京都豊島区南池袋3-24-5",
        "map_url": "https://maps.google.com/?q=麺屋+龍之介+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩12分",
        "walk_minutes": 12,
        "tag": "鶏清湯"
    },
    {
        "name": "らーめん 天下一品 池袋東口店",
        "wait_level": "green",
        "comment": "スムーズに入れます",
        "address": "東京都豊島区東池袋1-42-16",
        "map_url": "https://maps.google.com/?q=天下一品+池袋東口",
        "is_open": True,
        "walk_time": "池袋駅から徒歩6分",
        "walk_minutes": 6,
        "tag": "こってり"
    },
    {
        "name": "北海道らーめん 札幌や 池袋",
        "wait_level": "green",
        "comment": "今なら待たずに入れます",
        "address": "東京都豊島区西池袋3-30-9",
        "map_url": "https://maps.google.com/?q=札幌や+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩7分",
        "walk_minutes": 7,
        "tag": "北海道味噌"
    },
    {
        "name": "黒帯 池袋店",
        "wait_level": "red",
        "comment": "人気店、並んでます",
        "address": "東京都豊島区南池袋1-8-4",
        "map_url": "https://maps.google.com/?q=黒帯+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩5分",
        "walk_minutes": 5,
        "tag": "濃厚醤油"
    },
    {
        "name": "塩そば 彩 池袋",
        "wait_level": "green",
        "comment": "静かでゆっくり食べられます",
        "address": "東京都豊島区東池袋2-8-11",
        "map_url": "https://maps.google.com/?q=塩そば+彩+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩9分",
        "walk_minutes": 9,
        "tag": "あっさり塩"
    },
    {
        "name": "麺家 うえだ 池袋",
        "wait_level": "yellow",
        "comment": "週末は混むけど今は普通",
        "address": "東京都豊島区西池袋2-42-3",
        "map_url": "https://maps.google.com/?q=麺家+うえだ+池袋",
        "is_open": True,
        "walk_time": "池袋駅から徒歩10分",
        "walk_minutes": 10,
        "tag": "煮干し醤油"
    },
    {
        "name": "東池袋大勝軒 本店",
        "wait_level": "red",
        "comment": "さすがの本店、行列あり",
        "address": "東京都豊島区東池袋4-28-3",
        "map_url": "https://maps.google.com/?q=東池袋大勝軒+本店",
        "is_open": True,
        "walk_time": "池袋駅から徒歩13分",
        "walk_minutes": 13,
        "tag": "元祖つけ麺"
    }
]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/result")
def result():
    max_walk_str = request.args.get("max_walk")

    if max_walk_str and max_walk_str.isdigit():
        max_walk = int(max_walk_str)
        filtered = [s for s in ramen_shops if s["walk_minutes"] <= max_walk]
        filter_label = f"池袋駅から徒歩{max_walk}分以内"
    else:
        max_walk = None
        filtered = ramen_shops
        filter_label = "池袋駅周辺の全店舗"

    total_count = len(filtered)

    # 表示件数を上限に制限（MAX_DISPLAY を変更するだけで調整可能）
    displayed = filtered[:MAX_DISPLAY]

    return render_template(
        "result.html",
        shops=displayed,
        filter_label=filter_label,
        max_walk=max_walk,
        total_count=total_count,
        max_display=MAX_DISPLAY
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
