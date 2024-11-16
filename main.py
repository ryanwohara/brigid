import asyncio
import logging
import ssl
import time
import yaml

logging.basicConfig(level=logging.INFO)


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
        self.autojoined = False

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
        logging.info(f"Connected to {self.server}:{self.port} as {self.nickname}")
        logging.info(f"Relaying to: {self.relay_bot.server}")

    async def join_channel(self):
        self.writer.write(f"JOIN {self.channel}\r\n".encode())
        await self.writer.drain()
        logging.info(f"Joined channel {self.channel}")

    async def send_message(self, message, relay=True):
        self.writer.write(f"PRIVMSG {self.channel} :{message}\r\n".encode())
        await self.writer.drain()
        logging.info(f"Sent message: {message}")

    def parse_message(self, message):
        parts = message.split()
        if not parts:
            return None, None, []
        source = parts[0][1:] if parts[0].startswith(":") else None
        command = parts[1] if source else parts[0]
        args_start = 2 if source else 1
        args = []
        trailing_arg_start = None
        for i, part in enumerate(parts[args_start:], args_start):
            if part.startswith(":"):
                trailing_arg_start = i
                break
            else:
                args.append(part)
        if trailing_arg_start is not None:
            args.append(" ".join(parts[trailing_arg_start:])[1:])
        return source, command, args

    async def listen(self):
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

        while True:
            line = await self.reader.readline()
            line = line.decode().strip()
            logging.info(f"Received message: {line}")
            if not len(line):
                break

            source, command, args = self.parse_message(line)

            if command == "PING":
                response = "PONG :" + args[0] + "\r\n"
                self.writer.write(response.encode())
                await self.writer.drain()
                logging.info(f"Sent PONG response")

                # Join the channel after connection is established
                if not self.autojoined:
                    await self.join_channel()
                    self.autojoined = True
            elif command == "PRIVMSG" and args[0] == self.channel:
                nick = source.split("!")[0]
                colored_nick = color_nick(nick)
                message = args[1]
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
            elif command == "INVITE" and args[0] == self.nickname:
                self.channel = args[1]
                await self.join_channel()


async def main():
    # Load the configuration file
    with open(".env", "r") as f:
        config = yaml.safe_load(f)

    # Create the bots
    bots = [IRCBot(**bot_config) for bot_config in config["bots"]]

    # Set up the relay bots
    for i in range(len(bots)):
        bots[i].relay_bot = bots[(i + 1) % len(bots)]

    # Connect and listen
    await asyncio.gather(*(bot.connect() for bot in bots))
    await asyncio.gather(*(bot.listen() for bot in bots))


if __name__ == "__main__":
    asyncio.run(main())
