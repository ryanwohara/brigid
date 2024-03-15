import asyncio
import ssl
import logging

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
        ignored_users=None,
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
        self.ignored_users = ignored_users if ignored_users else []

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

        # Join the channel after connection is established
        await self.join_channel()

    async def join_channel(self):
        self.writer.write(f"JOIN {self.channel}\r\n".encode())
        await self.writer.drain()
        logging.info(f"Joined channel {self.channel}")

    async def send_message(self, message, relay=True):
        self.writer.write(f"PRIVMSG {self.channel} :{message}\r\n".encode())
        await self.writer.drain()
        logging.info(f"Sent message: {message}")

        if self.relay_bot and relay:
            # Only add network identifier if message is not a relayed message
            if not message.startswith('['):
                message = f"[{self.network_identifier}] {message}"
            await self.relay_bot.send_message(message, relay=False)

    def parse_message(self, message):
        parts = message.split()
        if not parts:
            return None, None, []
        source = parts[0][1:] if parts[0].startswith(':') else None
        command = parts[1] if source else parts[0]
        args_start = 2 if source else 1
        args = []
        trailing_arg_start = None
        for i, part in enumerate(parts[args_start:], args_start):
            if part.startswith(':'):
                trailing_arg_start = i
                break
            else:
                args.append(part)
        if trailing_arg_start is not None:
            args.append(' '.join(parts[trailing_arg_start:])[1:])
        return source, command, args

    async def listen(self):
        valid_colors = ["02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12", "13", "14", "15"]
        which_color = lambda nick: valid_colors[sum(ord(c) for c in nick) % len(valid_colors)]
        color_nick = lambda nick: f"\u0003{which_color(nick)}{nick}\u0003"

        while True:
            line = await self.reader.readline()
            line = line.decode().strip()
            logging.info(f"Received message: {line}")

            source, command, args = self.parse_message(line)

            if command == "PING":
                response = "PONG :" + args[0] + "\r\n"
                self.writer.write(response.encode())
                await self.writer.drain()
                logging.info(f"Sent PONG response")
            elif command == 'PRIVMSG' and args[0] == self.channel:
                nick = source.split('!')[0]
                if nick not in self.ignored_users:  # Check if the sender is ignored
                    colored_nick = color_nick(nick)
                    message = args[1]
                    if message.startswith('\x01ACTION'):
                        message = message[8:-1]
                        relay_message = f"[{self.network_identifier}] * {colored_nick} {message}"
                    else:
                        relay_message = f"[{self.network_identifier}] <{colored_nick}> {message}"
                    if self.relay_bot:
                        await self.relay_bot.send_message(relay_message)
            elif command == 'INVITE' and args[0] == self.nickname:
                channel = args[1]
                if channel == self.channel:
                    await self.join_channel()

async def main():
    bot1 = IRCBot('irc.rizon.net', 6697, 'ii', '#computertech', 'R', ignored_users=['user1', 'user2'])
    bot2 = IRCBot('irc.technet.chat', 6697, 'ii', '#computertech', 'T', ignored_users=['user1', 'user2'])
    bot3 = IRCBot('irc.swiftirc.net', 6697, 'ii', '#computertech', 'S', ignored_users=['user1', 'user2'])

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
