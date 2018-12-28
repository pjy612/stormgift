let request = require("request");
let UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/70.0.3538.110 Safari/537.36";


class Acceptor {
    static setInvalidGift(index, room_id, gift_id, logger){
        let k = "" + index + "_" + room_id + "_" + gift_id;
        if(this.__INVALID_PRIZE_POOL.indexOf(k) < 0){
            let len = this.__INVALID_PRIZE_POOL.push(k);
            if(len > 2000){
                for(let i = 0; i < len - 100; i++){
                    this.__INVALID_PRIZE_POOL.shift();
                }
            }
            logger.debug(
                "\t\tDEBUG: gift id set, room_id: %s, gift id: %s, gidPool len: %s",
                room_id, gift_id, this.__INVALID_PRIZE_POOL.length
            );
        }
    }
    static giftIsAvailable(room_id, gift_id){
        let k = "" + room_id + "_" + gift_id;
        return this.__INVALID_PRIZE_POOL.indexOf(k) < 0;
    }
    constructor(cookieDictList, loggerDict, defaultLogger) {
        this.cookieDictList = cookieDictList || [];
        this.loggerDict = loggerDict || {};
        this.defaultLogger = defaultLogger;
    }
    acceptGuardSingle(room_id, index) {
        let logging = this.loggerDict[this.cookieDictList[index].csrf_token] || this.defaultLogger;
        let csrf_token = this.cookieDictList[index].csrf_token;
        let cookie = this.cookieDictList[index].cookie;
        let joinFn = (gift_id) => {
            request.post({
                url: "https://api.live.bilibili.com/lottery/v2/Lottery/join",
                headers: {"User-Agent": UA, "Cookie": cookie},
                timeout: 20000,
                form: {
                    roomid: room_id,
                    id: gift_id,
                    type: "guard",
                    csrf_token: csrf_token,
                    csrf: csrf_token,
                    visit_id: "",
                }
            }, function (err, res, body) {
                if (err) {
                    logging.error("Error happened (r: " + room_id + "): " + err.toString());
                } else {
                    let r = JSON.parse(body.toString());
                    if (r.code === 0) {
                        let msg = r.data.message;
                        logging.info("GUARD ACCEPTOR: SUCCEED! room_id: %s, gift_id: %s, msg: %s, from: %s",
                            room_id, gift_id, msg, r.data.from
                        );
                    }
                }
            });
        };
        request({
            url: "https://api.live.bilibili.com/lottery/v1/Lottery/check_guard?roomid=" + room_id,
            method: "get",
            headers: {"User-Agent": UA, "Cookie": cookie},
            timeout: 20000,
        },function (err, res, body) {
            if(err){
                logging.error("Accept single guard error: %s, room_id: %s", err.toString(), room_id);
            }else{
                let r = JSON.parse(body.toString());
                if(r.code === 0){
                    let data = r.data || [];
                    if (data.length === 0){
                        // logging.warn("INVALID_GUARD_NOTICE, CANNOT JOIN -> %s", room_id)
                    }else{
                        data.forEach(function(d){joinFn(parseInt(d.id))})
                    }
                }
            }
        })
    };
    acceptGuard(room_id){
        for (let i = 0; i < this.cookieDictList.length; i++){
            this.acceptGuardSingle(room_id, i);
        }
    };
    acceptTvSingle(room_id, index){
        let logging = this.loggerDict[this.cookieDictList[index].csrf_token] || this.defaultLogger;
        let csrf_token = this.cookieDictList[index].csrf_token;
        let cookie = this.cookieDictList[index].cookie;
        let joinFn = (gift_id, title, from) => {
            if(!Acceptor.giftIsAvailable(room_id, gift_id)){
                logging.warn("TV GIFT: had accepted, skip it. room_id: %s, gift_id: %s", room_id, gift_id);
                return;
            }
            request({
                url: "https://api.live.bilibili.com/gift/v3/smalltv/join",
                method: "post",
                headers: {"User-Agent": UA, "Cookie": cookie},
                form: {
                    roomid: room_id,
                    raffleId: gift_id,
                    type: "Gift",
                    csrf_token: csrf_token,
                    csrf: csrf_token,
                    visit_id: "",
                },
                timeout: 20000,
            }, function (err, res, body) {
                Acceptor.setInvalidGift(index, room_id, gift_id, logging);
                if (err) {
                    logging.error("Accept tv prize error: %s, room_id: %s", err.toString(), room_id);
                } else {
                    let r = {"-": "-"};
                    try{
                        r = JSON.parse(body.toString());
                    }catch (e) {
                        logging.error(
                            "Error response acceptTvSingle JoinFn: %s, body:\n-------\n%s\n\n",
                            e.toString(), body
                        );
                        return;
                    }
                    if(r.code === 0){
                        let data = r.data || {};
                        let giftid = data.raffleId,
                            gtype = data.type;
                        logging.info(
                            "TV ACCEPTOR: SUCCEED! room id: %s, gift id: %s, title: %s, from: %s",
                            room_id, giftid, title, from
                        );
                    }else{
                        logging.error("TV ACCEPTOR: Failed! r: %s", JSON.stringify(r));
                    }
                }
            });
        };
        let getTvGiftId = (room_id) => {
            request({
                url: "https://api.live.bilibili.com/gift/v3/smalltv/check?roomid=" + room_id,
                method: "get",
                headers: {"User-Agent": UA, "Cookie": cookie},
                timeout: 20000,
            },function (err, res, body) {
                if(err){
                    logging.error("Get tv gift id error: %s, room_id: %s", err.toString(), room_id);
                }else{
                    let r = {"-": "-"};
                    try{
                        r = JSON.parse(body.toString());
                    }catch (e) {
                        logging.error("Error response getTvGiftId: %s, body:\n-------\n%s\n\n", e.toString(), body);
                        return;
                    }
                    if(r.code === 0){
                        let data = r.data || {};
                        let gidlist = data.list || [];
                        if(gidlist.length === 0){
                            logging.warn("INVALID_TV_NOTICE, CANNOT JOIN -> %s", room_id);
                        }
                        for (let i = 0; i < gidlist.length; i++){
                            let gid = parseInt(gidlist[i].raffleId) || 0,
                                title = gidlist[i].title || "Unknown",
                                from = gidlist[i].from;
                            if (gid !== 0){
                                // 限制频率
                                if (index !== 0 && Math.random() > 0.4){
                                    Acceptor.setInvalidGift(index, room_id, gid, logging);
                                    return
                                }

                                let delayTime = parseInt((index === 0 ? 10 : 40)*1000*Math.random());
                                logging.info(
                                    "\t\t\t Delay %s secs to join TV prize, room_id: %s, gid: %s, title: %s, from: %s",
                                    delayTime/1000, room_id, gid, title, from
                                );
                                setTimeout(() => {joinFn(gid, title, from)}, delayTime);
                            }
                        }
                    }
                }
            })
        };
        let delayTime = parseInt((index === 0 ? 10 : 60)*Math.random()*1000);
        logging.info("\t\t Delay %s secs to get TV gift id, room_id: %s", delayTime/1000, room_id);
        setTimeout(() => {getTvGiftId(room_id)}, delayTime);
    }
    acceptTv(room_id){
        this.acceptTvSingle(room_id, 0);

        let datetime = new Date();
        let hours = datetime.getHours();
        let limitFreq = (hours >= 20 || hours < 1);
        for (let i = 1; i < this.cookieDictList.length; i++){
            if((limitFreq && Math.random() < 0.3) || (!limitFreq)){
                this.acceptTvSingle(room_id, i);
            }
        }
    }
}
Acceptor.__INVALID_PRIZE_POOL = [];
module.exports.Acceptor = Acceptor;
