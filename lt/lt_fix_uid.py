import asyncio
from utils.db_raw_query import AsyncMySQL


async def fix_user_record_missed_uid():
    non_uid_users = await objects.execute(BiliUser.select().where(BiliUser.uid == None))
    logging.info(f"non_uid_users count: {len(non_uid_users)}")

    for non_uid_user_obj in non_uid_users:
        lastest_user_name = non_uid_user_obj.name
        fix_failed_key = f"FIX_MISSED_USER_{lastest_user_name}"
        if await redis_cache.get(fix_failed_key):
            logging.info(f"Found failed key: {fix_failed_key}, now skip.")
            continue

        uid = await ReqFreLimitApi.get_uid_by_name(lastest_user_name)
        if not uid:
            await redis_cache.set(fix_failed_key, "f", 3600 * 24 * random.randint(4, 7))
            logging.warning(f"Cannot get uid by name: `{non_uid_user_obj.name}`")
            continue

        has_uid_user_objs = await objects.execute(
            BiliUser.select().where(BiliUser.uid == uid)
        )
        if has_uid_user_objs:
            has_uid_user_obj = has_uid_user_objs[0]
            logging.info(f"User uid: {uid} -> name: {lastest_user_name} duplicated! ")

            # 有两个user_obj
            # 1.先把旧的existed_user_obj的name更新
            has_uid_user_obj.name = lastest_user_name
            await objects.update(has_uid_user_obj, only=("name",))

            # 2.迁移所有的raffle记录
            updated_count = 0
            for raffle_obj in await objects.execute(
                    Raffle.select().where(Raffle.sender_obj_id == non_uid_user_obj.id)
            ):
                updated_count += 1
                raffle_obj.sender_obj_id = has_uid_user_obj.id
                await objects.update(raffle_obj, only=("sender_obj_id",))

            for raffle_obj in await objects.execute(
                    Raffle.select().where(Raffle.winner_obj_id == non_uid_user_obj.id)
            ):
                updated_count += 1
                raffle_obj.winner_obj_id = has_uid_user_obj.id
                await objects.update(raffle_obj, only=("winner_obj_id",))

            # 3 迁移guard记录
            for guard_obj in await objects.execute(
                    Guard.select().where(Guard.sender_obj_id == non_uid_user_obj.id)
            ):
                updated_count += 1
                guard_obj.sender_obj_id = has_uid_user_obj.id
                await objects.update(guard_obj, only=("sender_obj_id",))

            # 4.删除空的user_obj
            await objects.delete(non_uid_user_obj)

            logging.info(f"User obj updated! raffle update count: {updated_count}")

        else:
            non_uid_user_obj.uid = uid
            await objects.update(non_uid_user_obj, only=("uid",))
            logging.info(f"User obj updated! {lastest_user_name} -> {uid}, obj id: {non_uid_user_obj.id}")


async def main():
    pass


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
