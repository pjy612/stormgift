import time
import json
import copy
import jinja2
import asyncio
import traceback
import datetime
from aiohttp import web
from config import CDN_URL
from utils.db_raw_query import AsyncMySQL
from utils.highlevel_api import ReqFreLimitApi
from config.log4 import website_logger as logging


gift_price_map = {
    "舰长": 1,
    "提督": 2,
    "总督": 3,
    "小电视飞船抽奖": 1245,
    "幻乐之声抽奖": 520,
    "任意门抽奖": 520,
    "摩天大楼抽奖": 450,
}


class Cache:
    e_tag = 0
    data = None

    raffle_e_tag = 0
    raffle_data = None


def request_frequency_control(time_interval=4):
    user_requests_records = []  # [(uniq, time), ... ]

    def deco(f):
        async def wrapped(request):
            host = request.headers.get("Host", "governors")
            ua = request.headers.get("User-Agent", "NON_UA")
            unique_identification = hash((host, ua))

            last_req_time = 0
            for _ in user_requests_records:
                if _[0] == unique_identification:
                    last_req_time = _[1]
                    break

            if time.time() - last_req_time < time_interval:
                return web.Response(text="拒绝服务：你的请求过于频繁。请3秒钟后再试。", content_type="text/html")

            result = await f(request)

            user_requests_records.insert(0, (unique_identification, time.time()))

            while len(user_requests_records) > 2000:
                user_requests_records.pop()

            return result
        return wrapped
    return deco


async def query_gifts(request):
    json_req = request.query.get("json")
    start_time = time.time()
    db_query_time = 0

    if time.time() < Cache.e_tag + 10:
        records = Cache.data
    else:
        try:
            db_start_time = time.time()
            raffle_records = await AsyncMySQL.execute(
                (
                    "select id, room_id, gift_name, sender_name, expire_time "
                    "from raffle where expire_time > %s order by id desc;"
                ), (datetime.datetime.now(), )
            )
            guard_records = await AsyncMySQL.execute(
                (
                    "select id, room_id, gift_name, sender_name, expire_time "
                    "from guard where expire_time > %s;"
                ), (datetime.datetime.now(),)
            )
            room_id_list = [row[1] for row in guard_records + raffle_records]
            room_info = await AsyncMySQL.execute(
                (
                    "select name, short_room_id, real_room_id "
                    "from biliuser where real_room_id in %s;"
                ), (room_id_list, )
            )
            room_dict = {}
            for row in room_info:
                name, short_room_id, real_room_id = row
                room_dict[real_room_id] = (name, short_room_id)

            def get_price(g):
                price_map = {
                    "小电视飞船": 1250,
                    "任意门": 600,
                    "幻乐之声": 520,
                    "摩天大楼": 450,
                    "总督": -1,
                    "提督": -2,
                    "舰长": -3
                }
                return price_map.get(g, 0)

            records = []
            for row in raffle_records + guard_records:
                raffle_id, room_id, gift_name, sender_name, expire_time = row
                master_name, short_room_id = room_dict.get(room_id, (None, None))
                if short_room_id == room_id:
                    short_room_id = "-"

                records.append({
                    "gift_name": gift_name.replace("抽奖", ""),
                    "short_room_id": short_room_id,
                    "real_room_id": room_id,
                    "master_name": master_name,
                    "sender_name": sender_name,
                    "raffle_id": raffle_id,
                    "expire_time": expire_time,
                })
            records.sort(key=lambda x: (get_price(x["gift_name"]), x["real_room_id"]), reverse=True)
            db_query_time = time.time() - db_start_time

        except Exception as e:
            msg = F"Error: {e} {traceback.format_exc()}"
            if json_req:
                text = json.dumps({"code": 500, "msg": msg})
                content_type = "application/json"
            else:
                text = msg
                content_type = "text/html"
            return web.Response(text=text, content_type=content_type)

        else:
            Cache.e_tag = time.time()
            Cache.data = records

    if json_req:
        json_result = [
            {
                k: str(v) if isinstance(v, datetime.datetime) else v
                for k, v in r.items()
                if k in ("gift_name", "real_room_id", "raffle_id", "expire_time")
            }
            for r in records
        ]
        return web.Response(
            text=json.dumps(
                {"code": 0, "e_tag": f"{hash(Cache.e_tag):0x}", "list": json_result},
                indent=2,
                ensure_ascii=False,
            ),
            content_type="application/json"
        )

    template_text = """
        <html>
        <style>
        table{
            width: 100%;
            max-width: 1100px;
            margin-bottom: 20px;
            border: 1px solid #7a7a7a;
            border-collapse: collapse;
            border-left: none;
            word-break: normal;
            line-height: 30px;
            text-align: center;
        }
        tr, th, td{
            border: 1px solid #7a7a7a;
        }
        </style>
        <body>
        <h2>礼物列表:（e_tag: {{ e_tag }}）<a href="/query_gifts?json=true" target="_blank">JSON格式</a></h2>
        <table>
        <tr>
        <th>raffle id</th>
        <th>短房间号</th>
        <th>原房间号</th>
        <th>主播</th>
        <th>礼物名称</th>
        <th>赠送者</th>
        <th>失效时间</th>
        <th>爪机传送门</th>
        </tr>
        {% for r in records %}
        <tr>
            <td>{{ r.raffle_id }}</td>
            <td>{% if r.short_room_id %}
                    {% if r.short_room_id == '-' %}-{% else %}
                <a href="https://live.bilibili.com/{{ r.short_room_id }}" target="_blank">{{ r.short_room_id }}</a>
                    {% endif %}
                {% endif %}
            </td>
            <td><a href="https://live.bilibili.com/{{ r.real_room_id }}" target="_blank">{{ r.real_room_id }}</a></td>
            <td>{{ r.master_name or "" }}</td>
            <td>{{ r.gift_name }}</td>
            <td>{{ r.sender_name }}</td>
            <td>{{ r.expire_time }}</td>
            <td><a href="bilibili://live/{{ r.real_room_id }}" target="_blank">打开破站</a></td>
        </tr>
        {% endfor %}
        </table>
        <h6>Process time: {{ proc_time }}(db query time: {{ db_query_time }})</h6></body></html>
    """
    template_text = " ".join(template_text.split())

    context = {
        "e_tag": f"{hash(Cache.e_tag):0x}",
        "records": records,
        "proc_time": f"{(time.time() - start_time):.3f}",
        "db_query_time": f"{db_query_time:.3f}",
    }

    text = jinja2.Template(template_text).render(context)
    return web.Response(text=text, content_type="text/html", charset="utf-8")


async def query_raffles(request):
    json_req = request.query.get("json")

    if time.time() < Cache.raffle_e_tag + 300:
        raffle_data = Cache.raffle_data
    else:
        start_date = datetime.datetime.now() - datetime.timedelta(hours=48)
        records = await AsyncMySQL.execute(
            (
                "select id, room_id, gift_name, gift_type, sender_obj_id, winner_obj_id, "
                "   prize_gift_name, expire_time, sender_name, winner_name "
                "from raffle "
                "where expire_time >= %s "
                "order by id desc ;"
            ), (start_date, )
        )
        user_obj_id_list = []
        room_id_list = []
        for row in records:
            (
                id, room_id, gift_name, gift_type, sender_obj_id, winner_obj_id,
                prize_gift_name, expire_time, sender_name, winner_name
            ) = row

            room_id_list.append(room_id)
            user_obj_id_list.append(sender_obj_id)
            user_obj_id_list.append(winner_obj_id)

        users = await AsyncMySQL.execute(
            (
                "select id, uid, name, short_room_id, real_room_id "
                "from biliuser "
                "where id in %s or real_room_id in %s "
                "order by id desc ;"
            ), (user_obj_id_list, room_id_list)
        )
        room_id_map = {}
        user_obj_id_map = {}
        for row in users:
            id, uid, name, short_room_id, real_room_id = row
            if short_room_id and real_room_id:
                room_id_map[real_room_id] = (short_room_id, name)
            user_obj_id_map[id] = (uid, name)

        raffle_data = []
        for row in records:
            (
                id, real_room_id, gift_name, gift_type, sender_obj_id, winner_obj_id,
                prize_gift_name, expire_time, sender_name, winner_name
            ) = row

            short_room_id, master_uname = room_id_map.get(real_room_id, (None, ""))
            if short_room_id is None:
                short_room_id = ""
            elif short_room_id == real_room_id:
                short_room_id = "-"

            user_id, user_name = user_obj_id_map.get(winner_obj_id, ("", winner_name))
            sender_uid, sender_name = user_obj_id_map.get(sender_obj_id, ("", sender_name))

            info = {
                "short_room_id": short_room_id,
                "real_room_id": real_room_id,
                "raffle_id": id,
                "gift_name": (gift_name.replace("抽奖", "") + "-" + gift_type) or "",
                "prize_gift_name": prize_gift_name or "",
                "created_time": expire_time,
                "user_id": user_id or "",
                "user_name": user_name or "",
                "master_uname": master_uname or "",
                "sender_uid": sender_uid or "",
                "sender_name": sender_name or "",
            }
            raffle_data.append(info)

        Cache.raffle_data = raffle_data
        Cache.raffle_e_tag = time.time()

    if json_req:
        json_result = copy.deepcopy(raffle_data)
        for info in json_result:
            for k, v in info.items():
                if isinstance(v, datetime.datetime):
                    info[k] = str(v)
                elif v == "":
                    info[k] = None

        return web.Response(
            text=json.dumps(
                {"code": 0, "e_tag": f"{hash(Cache.raffle_e_tag):0x}", "list": json_result},
                indent=2,
                ensure_ascii=False,
            ),
            content_type="application/json"
        )

    template_text = """
            <html>
            <style>
            table{
                width: 100%;
                margin-bottom: 20px;
                border: 1px solid #7a7a7a;
                border-collapse: collapse;
                border-left: none;
                word-break: normal;
                line-height: 30px;
                text-align: center;
            }
            tr, th, td{
                border: 1px solid #7a7a7a;
            }
            input{
                text-align: center;
            }
            button{
                border: none;
                background: #ccc;
                padding: 6px 12px;
                margin-top: 15px;
                outline: none;
                transition: all 0.3s ease-out;
                cursor: pointer;
            }button:hover{
                background: #777;
                color: #fff;
            }
            </style>
            <body>
            <h2>中奖记录:（e_tag: {{ e_tag }}）<a href="/query_raffles?json=true" target="_blank">JSON格式</a></h2>
            <p>仅展示48小时内的获奖记录，共计{{ raffle_count }}条。
                <div>
                    精确查询用户中奖记录：
                    <label>uid或用户名<input class="redinput" type="text" name="uid"></label>
                    <label><input class="redinput" type="number" name="day_range" value="7">天内</label>
                    <button class="button center" id="submit-query">查询</button>                    
                </div>
            </p>
            <table>
            <tr>
            <th>raffle id</th>
            <th>短房间号</th>
            <th>原房间号</th>
            <th>主播</th>
            <th>高能</th>
            <th>提供者uid</th>
            <th>提供者</th>
            <th>奖品</th>
            <th>获奖uid</th>
            <th>获奖者</th>
            <th>中奖时间</th>
            </tr>
            {% for r in raffle_data %}
            <tr>
                <td>{{ r.raffle_id }}</td>
                <td>{{ r.short_room_id }}</td>
                <td>{{ r.real_room_id }}</td>
                <td>{{ r.master_uname }}</td>
                <td>{{ r.gift_name }}</td>
                <td>{{ r.sender_uid }}</td>
                <td>{{ r.sender_name }}</td>
                <td>{{ r.prize_gift_name }}</td>
                <td>{{ r.user_id }}</td>
                <td>{{ r.user_name }}</td>
                <td>{{ r.created_time }}</td>
            </tr>
            {% endfor %}
            </table>
            <script type="text/javascript" src="{{ CDN_URL }}/static/js/jquery.min.js"></script>
            <script>
                $("#submit-query").click(function(){
                    let uid = $("input[name=uid]").val();
                    let dayRange = parseInt($("input[name=day_range]").val());
                    window.open("/query_raffles_by_user?day_range=" + dayRange + "&uid=" + uid);
                });
            </script>
            </body></html>
        """
    template_text = " ".join(template_text.split())

    context = {
        "e_tag": f"{hash(Cache.raffle_e_tag):0x}",
        "raffle_data": raffle_data,
        "raffle_count": len(raffle_data),
        "CDN_URL": CDN_URL,
    }

    text = jinja2.Template(template_text).render(context)
    return web.Response(text=text, content_type="text/html")


@request_frequency_control(time_interval=4)
async def query_raffles_by_user(request):
    uid = request.query.get("uid")
    day_range = request.query.get("day_range")
    now = datetime.datetime.now()
    raffle_start_record_time = now.replace(year=2019, month=7, day=2, hour=0, minute=0, second=0, microsecond=0)

    try:
        day_range = int(day_range)
        assert day_range > 1
    except (ValueError, TypeError, AssertionError):
        return web.Response(text="day_range参数错误。", content_type="text/html")

    end_date = now - datetime.timedelta(days=day_range)
    if end_date < raffle_start_record_time:
        total_days = int((now - raffle_start_record_time).total_seconds() / 3600 / 24)
        return web.Response(
            text=f"day_range参数超出范围。最早可以查询2019年7月2日之后的记录，day_range范围 1 ~ {total_days}。",
            content_type="text/html"
        )

    if not uid or len(uid) > 50:
        return web.Response(text="请输入正确的用户。", content_type="text/html")

    try:
        uid = int(uid)
    except (TypeError, ValueError):
        uid = await ReqFreLimitApi.get_uid_by_name(user_name=uid)

    user_record = await AsyncMySQL.execute(
        "select id, uid, name from biliuser where uid = %s;", (uid, )
    )
    if not user_record:
        return web.Response(text="未收录该用户。", content_type="text/html")

    winner_obj_id, uid, user_name = user_record[0]
    records = await AsyncMySQL.execute(
        (
            "select room_id, prize_gift_name, expire_time, sender_name, id from raffle "
            "where winner_obj_id = %s and expire_time > %s "
            "order by expire_time desc ;"
        ), (winner_obj_id, datetime.datetime.now() - datetime.timedelta(days=day_range))
    )
    if not records:
        return web.Response(text=f"用户{uid} - {user_name} 在{day_range}天内没有中奖。", content_type="text/html")
    room_id_list = [row[0] for row in records]
    room_info = await AsyncMySQL.execute(
        (
            "select short_room_id, real_room_id, name "
            "from biliuser where real_room_id in %s;"
        ), (room_id_list, )
    )
    room_dict = {}
    for row in room_info:
        short_room_id, real_room_id, name = row
        room_dict[real_room_id] = (short_room_id, name)

    raffle_data = []
    for row in records:
        room_id, prize_gift_name, expire_time, sender_name, raffle_id = row
        short_room_id, master_name = room_dict.get(room_id, ("-", None))
        if short_room_id == room_id:
            short_room_id = "-"
        info = {
            "short_room_id": short_room_id,
            "real_room_id": room_id,
            "raffle_id": raffle_id,
            "prize_gift_name": prize_gift_name,
            "sender_name": sender_name,
            "expire_time": expire_time,
            "master_name": master_name,
        }
        raffle_data.insert(0, info)

    template_text = """
            <html>
            <style>
            table{
                width: 100%;
                max-width: 1100px;
                margin-bottom: 20px;
                border: 1px solid #7a7a7a;
                border-collapse: collapse;
                border-left: none;
                word-break: normal;
                line-height: 30px;
                text-align: center;
            }
            tr, th, td{
                border: 1px solid #7a7a7a;
            }
            input{
                text-align: center;
            }
            </style>
            <body>
            <h2>用户uid: {{ uid }} - {{ user_name }} 在{{ day_range }}天内获奖列表: </h2>
            <table>
            <tr>
            <th>raffle id</th>
            <th>短房间号</th>
            <th>原房间号</th>
            <th>主播</th>
            <th>奖品</th>
            <th>提供者</th>
            <th>中奖时间</th>
            </tr>
            {% for r in raffle_data %}
            <tr>
                <td>{{ r.raffle_id }}</td>
                <td>{{ r.short_room_id }}</td>
                <td>{{ r.real_room_id }}</td>
                <td>{{ r.master_name }}</td>
                <td>{{ r.prize_gift_name }}</td>
                <td>{{ r.sender_name }}</td>
                <td>{{ r.expire_time }}</td>
            </tr>
            {% endfor %}
            </table>
            </body></html>
        """
    template_text = " ".join(template_text.split())

    context = {
        "uid": uid,
        "user_name": user_name,
        "day_range": day_range,
        "raffle_data": raffle_data,
    }
    text = jinja2.Template(template_text).render(context)
    return web.Response(text=text, content_type="text/html")


async def default_middle_ware(app, handler):
    async def wrapper(request):
        host = request.headers.get("Host", "governors")
        ua = request.headers.get("User-Agent", "NON_UA")
        logging.info(f"{host}->{request.remote}->{request.method}:{request.url}->\n\t{ua}")

        try:
            response = await handler(request)
        except Exception as e:
            status_code = getattr(e, "status_code", 500)
            reason = getattr(e, "reason", "Internal Server Error")
            content = f"<center><h3>{status_code} {reason}!</h3></center>"

            if status_code == 500:
                error_message = str(e)
                tb = traceback.format_exc()
                content += f"<br><h4>{error_message}</h4><pre>{tb}</pre>"

            response = web.Response(text=content, status=status_code, reason=reason, content_type="text/html")

        response.headers.add("Server", "madliar")
        return response
    return wrapper


async def on_web_startup(app):
    pass


app = web.Application(middlewares=(default_middle_ware, ))
app.on_startup.extend([
    on_web_startup,
])
app.add_routes([
    web.get('/query_gifts', query_gifts),
    web.get('/query_raffles', query_raffles),
    web.get('/query_raffles_by_user', query_raffles_by_user),
])
web.run_app(app, port=2048)
