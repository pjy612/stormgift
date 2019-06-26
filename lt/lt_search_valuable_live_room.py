import asyncio
import datetime
from utils.biliapi import BiliApi
from utils.model import LiveRoomInfo, objects

BiliApi.USE_ASYNC_REQUEST_METHOD = True


async def search_short_number():
    print("search_short_number...")

    for room_id in range(1, 999):
        live_room_info = {}

        req_url = F"https://api.live.bilibili.com/AppRoom/index?room_id={room_id}&platform=android"
        flag, data = await BiliApi.get(req_url, timeout=10, check_error_code=True)
        if flag and data["code"] in (0, "0"):
            short_room_id = data["data"]["show_room_id"]
            real_room_id = data["data"]["room_id"]
            user_id = data["data"]["mid"]

            live_room_info["short_room_id"] = short_room_id
            live_room_info["real_room_id"] = real_room_id
            live_room_info["title"] = ""  # data["data"]["title"].encode("utf-8")
            live_room_info["user_id"] = user_id
            live_room_info["create_at"] = data["data"]["create_at"]
            live_room_info["attention"] = data["data"]["attention"]

            req_url = f"https://api.live.bilibili.com/guard/topList?roomid={real_room_id}&page=1&ruid={user_id}"
            flag, data = await BiliApi.get(req_url, timeout=10, check_error_code=True)
            if not flag:
                print(f"Error! e: {data}")
                continue

            live_room_info["guard_count"] = data["data"]["info"]["num"]
            print(f"{live_room_info}")

            flag, r = await LiveRoomInfo.update_live_room(**live_room_info)
            print(
                f"Update {'success' if flag else 'Failed'}! room_id: "
                f"{live_room_info['short_room_id']}->{live_room_info['real_room_id']}, r: {r}"
            )
        await asyncio.sleep(10)


async def search_normal():
    pass


async def main():
    await objects.connect()

    while True:
        now_hour = datetime.datetime.now().hour
        if 2 < now_hour < 13:
            await search_short_number()
            await search_normal()

        await asyncio.sleep(60)

loop = asyncio.get_event_loop()
loop.run_until_complete(main())
