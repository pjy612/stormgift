import time
import asyncio
import datetime
from utils.biliapi import BiliApi, CookieFetcher
from config.log4 import bili_api_logger as logging
from utils.db_raw_query import AsyncMySQL
from utils.reconstruction_model import LTUserCookie
from utils.email import send_cookie_invalid_notice, send_cookie_relogin_notice
from utils.dao import LtUserLoginPeriodOfValidity


class ReqFreLimitApi(object):
    __req_time = {}

    @classmethod
    async def _wait(cls, f, wait_time):
        last_req_time = cls.__req_time.get(f)
        if last_req_time is None:
            cls.__req_time[f] = time.time()
        else:
            interval = time.time() - last_req_time
            if interval < wait_time:
                sleep_time = wait_time - interval
                logging.warn(f"High level api request frequency control: f: {f}, sleep_time: {sleep_time:.3f}")
                await asyncio.sleep(sleep_time)
            cls.__req_time[f] = time.time()

    @classmethod
    async def _update_time(cls, f):
        cls.__req_time[f] = time.time()

    @classmethod
    async def get_uid_by_name(cls, user_name, wait_time=2):
        await cls._wait("get_uid_by_name", wait_time=wait_time)

        flag, uid = await BiliApi.get_user_id_by_search_way(user_name)
        if flag and isinstance(uid, (int, float)) and uid > 0:
            return uid

        obj = await DBCookieOperator.get_by_uid("*")
        if not obj:
            return None

        cookie = obj.cookie
        uid = None
        for retry_time in range(3):
            await BiliApi.add_admin(user_name, cookie)

            flag, admin_list = await BiliApi.get_admin_list(cookie)
            if not flag:
                continue

            for admin in admin_list:
                if admin.get("uname") == user_name:
                    uid = admin.get("uid")
                    break

        if isinstance(uid, (int, float)) and uid > 0:
            await BiliApi.remove_admin(uid, cookie)

        await cls._update_time("get_uid_by_name")
        return uid

    @classmethod
    async def get_raffle_record(cls, uid):
        raffles = await AsyncMySQL.execute(
            "select r.winner_name, r.room_id, r.prize_gift_name, r.expire_time "
            "from raffle r, biliuser u "
            "where r.winner_obj_id = u.id and u.uid = %s and r.expire_time >= %s "
            "order by r.expire_time desc;",
            (uid, datetime.datetime.now() - datetime.timedelta(days=7))
        )

        results = []
        for r in raffles:
            name, room_id, gift_name, created_time = r
            results.append([name, room_id, gift_name, created_time])

        if not results:
            return results

        room_id_map = await AsyncMySQL.execute(
            "select real_room_id, short_room_id from biliuser where real_room_id in %s;",
            ([row[1] for row in results], )
        )
        room_id_map = {r[0]: r[1] for r in room_id_map}
        for r in results:
            r[1] = room_id_map.get(r[1], r[1])
        return results

    @classmethod
    async def get_raffle_count(cls, day_range=0):
        now = datetime.datetime.today()
        start_datetime = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if day_range > 0:
            start_datetime -= datetime.timedelta(days=day_range)
        end_date_time = start_datetime + datetime.timedelta(days=1)

        result = await AsyncMySQL.execute(
            "select max(id), min(id) "
            "from raffle where created_time >= %s and created_time < %s;",
            (start_datetime, end_date_time)
        )
        max_raffle_id, min_raffle_id = result[0]

        result = await AsyncMySQL.execute(
            "select id, winner_obj_id, gift_type from raffle where id >= %s and id <= %s order by id desc;",
            (min_raffle_id, max_raffle_id)
        )
        miss_raffle_count = 0
        total_gift_count = 0
        miss_gift_record = max_raffle_id - min_raffle_id - len(result) + 1
        gift_list = {}
        for raffle_id, winner_obj_id, gift_type in result:
            if gift_type == "GIFT_20003":
                gift_name = "大楼"
            elif gift_type == "GIFT_30035":
                gift_name = "任意门"
            elif gift_type == "GIFT_30207":
                gift_name = "幻月之声"
            elif gift_type == "small_tv":
                gift_name = "小电视"
            else:
                gift_name = "其他高能"

            if gift_name not in gift_list:
                gift_list[gift_name] = 1
            else:
                gift_list[gift_name] += 1

            total_gift_count += 1
            if winner_obj_id is None:
                miss_raffle_count += 1

        return_data = {
            "miss": miss_gift_record,
            "miss_raffle": miss_raffle_count,
            "total": total_gift_count,
            "gift_list": gift_list
        }
        return return_data

    @classmethod
    async def get_guard_count(cls):
        max_id_yesterday = (await AsyncMySQL.execute(
            "select id from guard where created_time < %s order by id desc limit 1;",
            (datetime.date.today(),)
        ))[0][0]
        print("max_id_yesterday: %s" % max_id_yesterday)

        result = await AsyncMySQL.execute(
            "select id from guard where id > %s and created_time >= %s order by id desc;",
            (max_id_yesterday, datetime.date.today(), )
        )
        total_id_list = [r[0] for r in result]

        target_count = total_id_list[0] - max_id_yesterday
        miss = target_count - len(total_id_list)

        result = await AsyncMySQL.execute(
            "select gift_name, count(id) from guard where id > %s group by 1;", (max_id_yesterday, )
        )

        gift_list = {}
        total_gift_count = 0
        for row in result:
            gift_list[row[0]] = row[1]
            total_gift_count += row[1]

        return_data = {
            "miss": miss,
            "total": total_gift_count,
            "gift_list": gift_list
        }
        return return_data


class DBCookieOperator:

    _objects = None

    IMPORTANT_UID_LIST = (
        20932326,  # DD
        39748080,  # LP
        312186483,  # TZ
    )

    @classmethod
    async def execute(cls, *args, **kwargs):
        if cls._objects is None:
            from utils.reconstruction_model import objects
            await objects.connect()
            cls._objects = objects
        if args or kwargs:
            return await cls._objects.execute(*args, **kwargs)
        else:
            return None

    @classmethod
    async def add_uid_or_account_to_white_list(cls, uid=None, account=None):
        await cls.execute()

        if uid is not None:
            obj, is_new = await cls._objects.get_or_create(LTUserCookie, DedeUserID=uid)
        else:
            obj, is_new = await cls._objects.get_or_create(LTUserCookie, account=account)

        return obj

    @classmethod
    async def del_uid_or_account_from_white_list(cls, uid=None, account=None):
        count = 0
        if uid:
            objs = await cls._objects.execute(LTUserCookie.select().where(LTUserCookie.DedeUserID == uid))
            for obj in objs:
                count += 1
                await cls._objects.delete(obj)

        if account:
            objs = await cls._objects.execute(LTUserCookie.select().where(LTUserCookie.account == account))
            for obj in objs:
                count += 1
                await cls._objects.delete(obj)

        return count

    @classmethod
    async def add_cookie_by_account(cls, account, password, notice_email=None):
        objs = await cls.execute(LTUserCookie.select().where(LTUserCookie.account == account))
        if not objs:
            return False, "你不在白名单里。提前联系站长经过允许才可以使用哦。"

        lt_user = objs[0]
        if lt_user.available and (lt_user.cookie_expire_time - datetime.datetime.now()).total_seconds() > 3600*24*10:
            return True, lt_user

        flag, cookie = await CookieFetcher.get_cookie(account, password)
        if not flag:
            return False, cookie

        lt_user.password = password
        lt_user.cookie_expire_time = datetime.datetime.now() + datetime.timedelta(days=30)
        lt_user.available = True
        attrs = ["password", "cookie_expire_time", "available"]

        cookie_kv = [_.strip() for _ in cookie.split(";")]
        for k, v in [_.split("=", 1) for _ in cookie_kv if "=" in _]:
            setattr(lt_user, k, v)
            attrs.append(k)

        flag, data, uname = await BiliApi.get_if_user_is_live_vip(cookie, user_id=lt_user.DedeUserID, return_uname=True)
        if not flag:
            return False, "无法获取你的个人信息，请稍后再试。"

        lt_user.is_vip = data
        lt_user.name = uname
        attrs.extend(["is_vip", "name"])

        if notice_email is not None:
            lt_user.notice_email = notice_email
            attrs.append("notice_email")

        for obj in await cls._objects.execute(LTUserCookie.select().where(
            (LTUserCookie.DedeUserID == lt_user.DedeUserID) & (LTUserCookie.id != lt_user.id)
        )):
            await cls._objects.delete(obj)

        await cls._objects.update(lt_user, only=attrs)

        return True, lt_user

    @classmethod
    async def add_cookie_by_cookie(cls, DedeUserID, SESSDATA, bili_jct, notice_email=None):
        objs = await cls.execute(LTUserCookie.select().where(LTUserCookie.DedeUserID == DedeUserID))
        if not objs:
            return False, "Not in white list."

        lt_user = objs[0]
        if lt_user.available and (lt_user.cookie_expire_time - datetime.datetime.now()).total_seconds() > 3600*24*10:
            return True, lt_user

        cookie = f"bili_jct={bili_jct}; DedeUserID={DedeUserID}; SESSDATA={SESSDATA};"
        flag, data, uname = await BiliApi.get_if_user_is_live_vip(cookie, user_id=lt_user.DedeUserID, return_uname=True)
        if not flag:
            return False, data

        lt_user.bili_jct = bili_jct
        lt_user.DedeUserID = DedeUserID
        lt_user.SESSDATA = SESSDATA
        lt_user.cookie_expire_time = datetime.datetime.now() + datetime.timedelta(days=30)
        lt_user.available = True
        lt_user.is_vip = data
        lt_user.name = uname
        attrs = ["bili_jct", "DedeUserID", "SESSDATA", "cookie_expire_time", "available", "is_vip", "name"]

        if notice_email is not None:
            lt_user.notice_email = notice_email
            attrs.append("notice_email")

        await cls._objects.update(lt_user, only=attrs)

        return True, lt_user

    @classmethod
    async def set_invalid(cls, obj_or_user_id):
        if isinstance(obj_or_user_id, LTUserCookie):
            cookie_obj = obj_or_user_id
        else:
            objs = await cls.execute(LTUserCookie.select().where(LTUserCookie.DedeUserID == obj_or_user_id))
            if not objs:
                return False, "Cannot get LTUserCookie obj."
            cookie_obj = objs[0]

        cookie_obj.available = False
        await cls._objects.update(cookie_obj, only=("available",))

        user_in_period = await LtUserLoginPeriodOfValidity.in_period(user_id=cookie_obj.DedeUserID)
        user_in_iptt_list = cookie_obj.DedeUserID in cls.IMPORTANT_UID_LIST

        if (user_in_iptt_list or user_in_period) and cookie_obj.account and cookie_obj.password:
            for try_times in range(3):
                flag, data = await cls.add_cookie_by_account(
                    account=cookie_obj.account,
                    password=cookie_obj.password
                )
                if flag:
                    send_cookie_relogin_notice(cookie_obj)
                    return True, ""
                else:
                    logging.error(
                        f"Failed to login user: {cookie_obj.name}(uid: {cookie_obj.user_id}), "
                        f"try times: {try_times}, error msg: {data}"
                    )
                    await asyncio.sleep(1)

        send_cookie_invalid_notice(cookie_obj)
        return True, ""

    @classmethod
    async def set_vip(cls, obj_or_user_id, is_vip):
        if isinstance(obj_or_user_id, LTUserCookie):
            cookie_obj = obj_or_user_id
        else:
            objs = await cls.execute(LTUserCookie.select().where(LTUserCookie.DedeUserID == obj_or_user_id))
            if not objs:
                return False, "Cannot get LTUserCookie obj."
            cookie_obj = objs[0]

        cookie_obj.is_vip = bool(is_vip)
        await cls._objects.update(cookie_obj, only=("is_vip",))

        return True, cookie_obj

    @classmethod
    async def set_blocked(cls, obj_or_user_id):
        if isinstance(obj_or_user_id, LTUserCookie):
            cookie_obj = obj_or_user_id
        else:
            objs = await cls.execute(LTUserCookie.select().where(LTUserCookie.DedeUserID == obj_or_user_id))
            if not objs:
                return False, "Cannot get LTUserCookie obj."
            cookie_obj = objs[0]

        cookie_obj.blocked_time = datetime.datetime.now()
        await cls._objects.update(cookie_obj, only=("blocked_time",))
        return True, cookie_obj

    @classmethod
    async def get_by_uid(cls, user_id, available=None):
        if user_id == "*":
            objs = await cls.execute(LTUserCookie.select().where(LTUserCookie.available == True))
            return objs[0]

        if user_id == "DD":
            user_id = 20932326
        elif user_id == "LP":
            user_id = 39748080

        if available is None:
            query = LTUserCookie.select().where(LTUserCookie.DedeUserID == user_id)
        else:
            query = LTUserCookie.select().where(
                (LTUserCookie.DedeUserID == user_id) & (LTUserCookie.available == available)
            )
        objs = await cls.execute(query)
        if objs:
            return objs[0]
        return None

    @classmethod
    async def get_objs(
            cls,
            available: bool = None,
            is_vip: bool = None,
            non_blocked: bool = None,
            separate: bool = False
    ):
        query = LTUserCookie.select()
        if available is not None:
            query = query.where(LTUserCookie.available == available)
        if is_vip is not None:
            query = query.where(LTUserCookie.is_vip == is_vip)

        if non_blocked is not None:
            eight_hour_ago = datetime.datetime.now() - datetime.timedelta(hours=8)
            query = query.where(LTUserCookie.blocked_time < eight_hour_ago)

        important_objs = []
        objs = []
        for o in await cls.execute(query):
            if o.DedeUserID in cls.IMPORTANT_UID_LIST:
                important_objs.append(o)
            else:
                objs.append(o)

        if separate:
            return important_objs, objs
        else:
            return important_objs + objs

    @classmethod
    async def get_lt_status(cls, uid):
        cookie_obj = await cls.get_by_uid(uid)
        if cookie_obj is None:
            return False, f"用户（uid: {uid}）尚未配置。"

        if not cookie_obj.available:
            return False, f"用户{cookie_obj.name}（uid: {uid}）的登录已过期，请重新登录。"

        most_recently = await AsyncMySQL.execute(
            "select created_time from userrafflerecord where user_id = %s order by created_time desc limit 1;",
            (uid,)
        )
        if most_recently:
            most_recently = most_recently[0][0]
            interval = (datetime.datetime.now() - most_recently).total_seconds()
            if interval > 3600:
                most_recently = f"约{int(interval // 3600)}小时前"
            elif interval > 60:
                most_recently = f"约{int(interval // 60)}分钟前"
            else:
                most_recently = f"{int(interval)}秒前"
        else:
            most_recently = "未查询到记录"

        rows = await AsyncMySQL.execute(
            (
                "select gift_name, count(raffle_id) "
                "from userrafflerecord "
                "where user_id = %s and created_time >= %s "
                "group by gift_name;"
            ), (uid, datetime.datetime.now() - datetime.timedelta(hours=24))
        )
        raffle_result = []
        total_intimacy = 0
        for gift_name, count in rows:
            intimacy_map = {
                "总督": 20,
                "提督": 5,
                "舰长": 1,
                "小电视飞船抽奖": 5,
                "任意门抽奖": 5,
            }
            total_intimacy += intimacy_map.get(gift_name, 1) * count
            raffle_result.append({
                "gift_name": gift_name,
                "count": count
            })
        if (datetime.datetime.now() - cookie_obj.blocked_time).total_seconds() < 3600 * 6:
            blocked_datetime = cookie_obj.blocked_time
        else:
            blocked_datetime = None

        if blocked_datetime:
            title = (
                f"系统在{str(blocked_datetime)[:19]}发现你被关进了小黑屋，目前挂辣条暂停中。\n\n"
                f"最后一次抽奖时间：{str(most_recently)}\n"
                f"24小时内累计获得亲密度：{total_intimacy}\n"
            )
        else:
            title = (
                f"你现在正常领取辣条中\n\n"
                f"最后一次抽奖时间：{str(most_recently)}\n"
                f"24小时内累计获得亲密度：{total_intimacy}\n"
            )
        postfix = []
        for r in raffle_result:
            postfix.append("-"*20 + "\n")
            postfix.append(f"{r['gift_name']}: {r['count']}\n")
        postfix.append("-" * 20)
        return True, title + "".join(postfix)
