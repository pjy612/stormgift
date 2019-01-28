import time
import os
import sys
import logging
import json
import aioredis
import datetime
import asyncio

import peewee
from peewee_async import Manager, PooledMySQLDatabase


if sys.platform == "linux":
    CONFIG_FILE = "/home/wwwroot/stormgift/config/proj_config.json"
    LOG_PATH = "/home/wwwroot/log"
else:
    CONFIG_FILE = "../config/proj_config.json"
    LOG_PATH = "../log"
fh = logging.FileHandler(os.path.join(LOG_PATH, "sync_database.log"), encoding="utf-8")
fh.setFormatter(logging.Formatter('%(asctime)s: %(message)s'))
logger = logging.getLogger("sync_database")
logger.setLevel(logging.DEBUG)
logger.addHandler(fh)
logger.addHandler(logging.StreamHandler(sys.stdout))
logging = logger


with open(CONFIG_FILE, "rb") as f:
    config = json.loads(f.read().decode("utf-8"))
    mysql_config = config.get("mysql")
    redis_config = config.get("redis")
mysql_db = PooledMySQLDatabase(**mysql_config)


class User(peewee.Model):
    name = peewee.CharField()
    uid = peewee.IntegerField(unique=True, null=True, )
    face = peewee.CharField()
    info = peewee.CharField()

    class Meta:
        database = mysql_db


class GiftRec(peewee.Model):
    key = peewee.CharField(unique=True)
    room_id = peewee.IntegerField()
    gift_id = peewee.IntegerField()
    gift_name = peewee.CharField()
    gift_type = peewee.CharField()
    sender = peewee.ForeignKeyField(User, related_name="gift_rec", on_delete="SET NULL", null=True)
    sender_type = peewee.IntegerField(null=True)
    created_time = peewee.DateTimeField(default=datetime.datetime.now)
    status = peewee.IntegerField()

    class Meta:
        database = mysql_db


loop = asyncio.get_event_loop()
objects = Manager(mysql_db, loop=loop)


class SyncTool(object):
    @classmethod
    async def get_or_update_user_obj(cls, uid, name, face):
        if uid is None:
            users = await objects.execute(User.select().where(User.name == name))
            if users:
                return users[0]
            else:
                return await objects.create(User, name=name, uid=uid, face=face)

        users = await objects.execute(User.select().where(User.uid == uid))
        if users:
            user_obj = users[0]
            if user_obj.name != name:
                logging.info("User obj name update: %s -> %s" % (user_obj.name, name))
                user_obj.name = name
                await objects.update(user_obj)
            return user_obj
        else:
            users = await objects.execute(User.select().where(User.name == name))
            if users:
                user_obj = users[0]
                user_obj.uid = uid
                logging.info("User obj(%s) uid update: %s -> %s" % (name, user_obj.uid, uid))
                await objects.update(user_obj)
                return user_obj
            else:
                return await objects.create(User, name=name, uid=uid, face=face)

    @classmethod
    async def proc_single_info(cls, k, data):
        try:
            r = json.loads(data.decode("utf-8"))
        except Exception as e:
            logging.error("Error in sync_tv_single_rec: %s" % e)
            return

        if k.startswith("_T"):
            user_info = r["from_user"]
            user_obj = await cls.get_or_update_user_obj(uid=None, name=user_info["uname"], face=user_info["face"])
            return {
                "key": k,
                "room_id": int(k[2:].split("$")[0]),
                "gift_id": r["raffleId"],
                "gift_name": r["title"],
                "gift_type": r["type"],
                "sender": user_obj,
                "sender_type": r["sender_type"],
                "created_time": datetime.datetime.fromtimestamp(r["_saved_time"] / 1000),
                "status": r["status"],
            }
        elif k.startswith("NG"):
            user_info = r["sender"]
            user_obj = await cls.get_or_update_user_obj(user_info["uid"], user_info["uname"], user_info["face"])
            return {
                "key": k,
                "room_id": int(k[2:].split("$")[0]),
                "gift_id": int(k[2:].split("$")[-1]),
                "gift_name": "guard",
                "gift_type": "G" + str(r["privilege_type"]),
                "sender": user_obj,
                "sender_type": None,
                "created_time": datetime.datetime.fromtimestamp(r["_saved_time"] / 1000),
                "status": r["status"],
            }
        else:
            return

    @classmethod
    async def sync_rec(cls, redis):
        ng_keys = await redis.execute("keys", "NG*")
        _t_keys = await redis.execute("keys", "_T*")
        keys = set(ng_keys + _t_keys)
        old_key = []
        for key in keys:
            r = await redis.execute("get", key)
            r = json.loads(r.decode("utf-8"))
            if r and r.get("_saved_time"):
                old_key.append(key)

        print(old_key)
        return
        db_keys = {_.key for _ in await objects.execute(GiftRec.select(GiftRec.key))}
        need_deleted_from_redis = keys - db_keys
        print(len(need_deleted_from_redis))

        return
        keys = []
        need_synced_keys = {_.decode("utf-8") for _ in keys} - {_.key for _ in existed_keys}
        logging.info("Need sync count: %s." % len(need_synced_keys))

        source_info = {}
        pipe = redis.pipeline()
        count = 0
        for k in need_synced_keys:
            count += 1
            source_info[k] = pipe.get(k)
            if count >= 100:
                await pipe.execute()
                pipe = redis.pipeline()
                count = 0
        if count > 0:
            await pipe.execute()

        need_create_gift_rec = []
        for k, info in source_info.items():
            param = await cls.proc_single_info(k, info.result())
            if param is not None:
                need_create_gift_rec.append(param)

            if len(need_create_gift_rec) >= 100:
                r = await objects.execute(GiftRec.insert_many(need_create_gift_rec))
                logging.info("Bulk create succeed! r: %s" % r)
                need_create_gift_rec = []

        if need_create_gift_rec:
            r = await objects.execute(GiftRec.insert_many(need_create_gift_rec))
            logging.info("Bulk create succeed! r: %s" % r)

    @classmethod
    async def run(cls):
        start_time = time.time()
        await objects.connect()
        redis = await aioredis.create_connection(
            address='redis://%s:%s' % (redis_config["host"], redis_config["port"]),
            db=redis_config["db"],
            password=redis_config["auth_pass"],
            loop=loop
        )
        await cls.sync_rec(redis)

        redis.close()
        await redis.wait_closed()
        await objects.close()
        logging.info("Execute finished, cost: %s.\n\n" % (time.time() - start_time))


loop.run_until_complete(SyncTool.run())
