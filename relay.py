import asyncio
import ssl


class IRCBot:
    def __init__(
        self,
        server,
        port,
        nickname,
        channel,
        network_identifier,
        relay_bot=None,
        tls=True,
    ):
        self.server = server
        self.port = port
        self.nickname = nickname
        self.channel = channel
        self.network_identifier = network_identifier
        self.relay_bot = relay_bot
        self.reader = None
        self.writer = None
        self.tls = tls

    async def connect(self):
        if self.tls:
            self.reader, self.writer = await asyncio.open_connection(
                self.server, self.port, ssl=ssl.create_default_context()
            )
        else:
            self.reader, self.writer = await asyncio.open_connection(
                self.server, self.port
            )
        self.writer.write(f"NICK {self.nickname}\r\n".encode())
        self.writer.write(f"USER {self.nickname} 0 * :{self.nickname}\r\n".encode())
        await self.writer.drain()

    async def join_channel(self):
        self.writer.write(f"JOIN {self.channel}\r\n".encode())
        await self.writer.drain()

    async def send_message(self, message, relay=True):
        self.writer.write(f"PRIVMSG {self.channel} :{message}\r\n".encode())
        await self.writer.drain()

        if self.relay_bot and relay:
            # Only add network identifier if message is not a relayed message
            if not message.startswith('['):
                message = f"[{self.network_identifier}] {message}"
            await self.relay_bot.send_message(message, relay=False)

    async def listen(self):
        while True:
            line = await self.reader.readline()
            line = line.decode().strip()

            if line.startswith("PING"):
                response = "PONG :" + line.split(":")[1] + "\r\n"
                self.writer.write(response.encode())
                await self.writer.drain()
            else:
                parts = line.split()
                if len(parts) > 1 and parts[1].isdigit():
                    numeric_reply = parts[1]
                    if numeric_reply == '001':
                        await self.join_channel()
                elif (
                    len(parts) > 2
                    and parts[1] == "PRIVMSG"
                    and parts[2] == self.channel
                ):
                    nick = parts[0].split("!")[0].lstrip(":")
                    valid_colors = [
                        "02",
                        "03",
                        "04",
                        "05",
                        "06",
                        "07",
                        "08",
                        "09",
                        "10",
                        "11",
                        "12",
                        "13",
                        "14",
                        "15",
                    ]
                    which_color = lambda nick: valid_colors[
                        sum(ord(c) for c in nick) % len(valid_colors)
                    ]
                    color_nick = lambda nick: f"\u0003{which_color(nick)}{nick}\u0003"
                    colored_nick = color_nick(nick)
                    message = " ".join(parts[3:]).lstrip(":")
                    if message.startswith("\x01ACTION"):
                        message = message[8:-1]
                        relay_message = (
                            f"[{self.network_identifier}] * {colored_nick} {message}"
                        )
                    else:
                        relay_message = (
                            f"[{self.network_identifier}] <{colored_nick}> {message}"
                        )
                    if self.relay_bot:
                        await self.relay_bot.send_message(relay_message)

async def main():
    bot1 = IRCBot('irc.rizon.net', 6697, 'ii', '#computertech', 'R')
    bot2 = IRCBot('irc.technet.chat', 6697, 'ii', '#computertech', 'T')
    bot3 = IRCBot('irc.swiftirc.net', 6697, 'ii', '#computertech', 'S')

    bot1.relay_bot = bot2
    bot2.relay_bot = bot3
    bot3.relay_bot = bot1

    await asyncio.gather(
        bot1.connect(),
        bot2.connect(),
        bot3.connect()
    )

    await asyncio.gather(
        bot1.listen(),
        bot2.listen(),
        bot3.listen()
    )

if __name__ == "__main__":
    asyncio.run(main())
