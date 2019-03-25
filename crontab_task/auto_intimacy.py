import sys
import logging
import asyncio
SEND_CONFIG = {
    39748080: "电磁泡",
    20932326: "电磁泡",
}


log_format = logging.Formatter("%(asctime)s [%(levelname)s]: %(message)s")
console = logging.StreamHandler(sys.stdout)
console.setFormatter(log_format)
logger = logging.getLogger("auto_intimacy")
logger.setLevel(logging.DEBUG)
logger.addHandler(console)

if "linux" in sys.platform:
    file_handler = logging.FileHandler("/home/wwwroot/log/auto_intimacy.log")
    file_handler.setFormatter(log_format)
    logger.addHandler(file_handler)

logging = logger


async def send_gift(cookie):
    from utils.biliapi import BiliApi

    r = await BiliApi.get_medal_info_list(cookie)
    if not r:
        return
    uid = r[0]["uid"]
    target_model = [_ for _ in r if _["medal_name"] == SEND_CONFIG[uid]]
    if not target_model:
        return
    target_model = target_model[0]
    logging.info(f"{uid} -> {target_model['medal_name']}")

    live_room_id = target_model["roomid"]
    ruid = target_model["anchorInfo"]["uid"]

    today_feed = target_model["todayFeed"]
    day_limit = target_model["dayLimit"]
    left_intimacy = day_limit - today_feed
    logging.info(f"left_intimacy: {left_intimacy}")

    bag_list = await BiliApi.get_bag_list(cookie)
    gift_today = []
    gift_lt = []
    gift_bkl = []
    for gift in bag_list:
        if gift["corner_mark"] == "今天":
            gift_today.append(gift)
        elif gift["gift_name"] == "辣条":
            gift_lt.append(gift)
        elif gift["gift_name"] == "B坷垃":
            gift_bkl.append(gift)
    gift_lt.sort(key=lambda x: x["expire_at"])
    gift_bkl.sort(key=lambda x: x["expire_at"])
    can_send_bag = gift_today + gift_bkl + gift_lt

    send_list = []
    for gift in can_send_bag:
        if gift["gift_name"] == "辣条":
            intimacy_single = 1
        elif gift["gift_name"] == "B坷垃":
            intimacy_single = 99
        else:
            continue

        need_send_gift_num = min(left_intimacy // intimacy_single, gift["gift_num"])
        if need_send_gift_num > 0:
            send_list.append({
                "coin_type": None,
                "gift_num": need_send_gift_num,
                "bag_id": gift["bag_id"],
                "gift_id": gift["gift_id"],
            })
            left_intimacy -= intimacy_single*need_send_gift_num

        if left_intimacy <= 0:
            break

    if left_intimacy > 0:
        wallet_info = await BiliApi.get_wallet(cookie)
        silver = wallet_info.get("silver", 0)
        supplement_lt_num = min(silver // 100, left_intimacy)
        if supplement_lt_num > 0:
            send_list.append({
                "coin_type": "silver",
                "gift_num": supplement_lt_num,
                "bag_id": 0,
                "gift_id": 1,
            })

    logging.info(f"send_list: {send_list}")
    for gift in send_list:
        flag, data = await BiliApi.send_gift(
            gift["gift_id"], gift["gift_num"], gift["coin_type"], gift["bag_id"], ruid, live_room_id, cookie
        )
        if not flag:
            logging.info(f"Send failed, msg: {data.get('message', 'unknown')}")
    logging.info(f"Final left intimacy: {left_intimacy}")


async def main():
    sys.path.append('../')

    from data import COOKIE_LP, COOKIE_DD
    for c in (COOKIE_LP, COOKIE_DD):
        await send_gift(c)

loop = asyncio.get_event_loop()
loop.run_until_complete(main())
