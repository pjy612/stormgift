import asyncio
import websockets

from config import PRIZE_HANDLER_SERVE_ADDR, PRIZE_SOURCE_PUSH_ADDR
from config.log4 import server_logger as logging


class NoticeHandler(object):
    def __init__(self, host, port):
        self.__clients = set()
        self.host = host
        self.port = port

    async def handler(self, ws, path):
        self.__clients.add(ws)
        logging.info(
            f"New client connected: ({ws.host}, {ws.port}), "
            f"path: {path}, current conn: {len(self.__clients)}"
        )

        while not ws.closed:
            await asyncio.sleep(10)

        if ws in self.__clients:
            self.__clients.remove(ws)
            logging.info("Client leave: %s, current connections: %s" % (ws, len(self.__clients)))

    def start_server(self):
        return websockets.serve(self.handler, self.host, self.port)

    async def notice_all(self, msg):
        lived_clients = [c for c in self.__clients if not c.closed]
        logging.info(f"Notice to all, msg: [{msg}], Lived clients: {len(lived_clients)}")
        for c in lived_clients:
            try:
                await c.send(msg)
            except Exception as e:
                print(f"Exception at send notice: {e}")


class PrizeInfoReceiver:
    notice_handler = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, message, addr):
        logging.info(f"Message received from {addr}: [{message}]")
        if self.__class__.notice_handler:
            asyncio.gather(self.__class__.notice_handler(message))

    @classmethod
    async def start_server(cls, addr):
        listen = loop.create_datagram_endpoint(cls, local_addr=addr)
        await asyncio.ensure_future(listen)


async def main():
    h = NoticeHandler(*PRIZE_HANDLER_SERVE_ADDR)

    PrizeInfoReceiver.notice_handler = h.notice_all
    await PrizeInfoReceiver.start_server(PRIZE_SOURCE_PUSH_ADDR)
    await h.start_server()
    logging.info(f"Server started.")


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
loop.run_forever()