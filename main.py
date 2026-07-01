import asyncio
import base64
import logging
import ssl
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
        relay_bots=[],
        tls=True,
        nickserv_password=None,
    ):
        self.server = server
        self.port = port
        self.nickname = nickname
        self.channel = channel
        self.network_identifier = network_identifier
        self.relay_bots = relay_bots
        self.reader = None
        self.writer = None
        self.tls = tls
        self.nickserv_password = nickserv_password

    async def connect(self):
        if self.tls:
            self.reader, self.writer = await asyncio.open_connection(
                self.server, self.port, ssl=ssl.create_default_context()
            )
        else:
            self.reader, self.writer = await asyncio.open_connection(
                self.server, self.port
            )
        # Begin capability negotiation before registering so SASL can complete
        # (and identify us to services) before the welcome burst / auto-join.
        if self.nickserv_password:
            self.writer.write("CAP LS\r\n".encode())
        self.writer.write(f"NICK {self.nickname}\r\n".encode())
        self.writer.write(f"USER {self.nickname} 0 * :{self.nickname}\r\n".encode())
        await self.writer.drain()
        logging.info(f"Connected to {self.server}:{self.port} as {self.nickname}")

    async def join_channel(self):
        self.writer.write(f"JOIN {self.channel}\r\n".encode())
        await self.writer.drain()
        logging.info(f"Joined channel {self.channel}")

    async def register_as_bot(self):
        self.writer.write(f"MODE {self.nickname} +B\r\n".encode())
        await self.writer.drain()
        logging.info("Registered as a bot user")

    async def request_sasl(self):
        self.writer.write("CAP REQ :sasl\r\n".encode())
        await self.writer.drain()

    async def start_sasl(self):
        self.writer.write("AUTHENTICATE PLAIN\r\n".encode())
        await self.writer.drain()

    async def send_sasl_credentials(self):
        # SASL PLAIN: base64(authzid \0 authcid \0 password); authzid left empty.
        payload = f"\x00{self.nickname}\x00{self.nickserv_password}".encode()
        token = base64.b64encode(payload).decode()
        self.writer.write(f"AUTHENTICATE {token}\r\n".encode())
        await self.writer.drain()

    async def end_cap(self):
        self.writer.write("CAP END\r\n".encode())
        await self.writer.drain()

    async def send_message(self, message, relay=True):
        self.writer.write(f"PRIVMSG {self.channel} :{message}\r\n".encode())
        await self.writer.drain()
        logging.info(f"Sent message: {message}")

    def parse_message(self, message):
        parts = message.split(" ")
        if not parts or not len(parts):
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
            b = await self.reader.readline()
            try:
                line = b.decode('utf-8').strip()
                logging.info(f"Received message: {line}")
            except:
                logging.warn(f"Error decoding message")
                pass
            if not len(line):
                break

            source, command, args = self.parse_message(line)

            # SASL capability negotiation (only when a password is configured).
            if command == "CAP" and len(args) >= 2:
                subcommand = args[1]
                caps = args[-1].split()
                if subcommand == "LS":
                    if "sasl" in caps:
                        await self.request_sasl()
                    else:
                        logging.warning(
                            "SASL not offered by server; connecting without identifying"
                        )
                        await self.end_cap()
                elif subcommand == "ACK" and "sasl" in caps:
                    await self.start_sasl()
                elif subcommand == "NAK":
                    logging.warning(
                        "SASL capability refused; connecting without identifying"
                    )
                    await self.end_cap()
            elif command == "AUTHENTICATE" and args and args[0] == "+":
                await self.send_sasl_credentials()
            elif command == "903":  # RPL_SASLSUCCESS
                logging.info("SASL authentication successful")
                await self.end_cap()
            elif command in ("902", "904", "905", "906", "907"):  # SASL failed/aborted
                logging.error(
                    f"SASL authentication failed ({command}); "
                    "connecting without identifying"
                )
                await self.end_cap()
            # Register + join once fully connected. With SASL this arrives only
            # after authentication, so we are identified before joining.
            elif command == "001":
                await self.register_as_bot()
                await self.join_channel()
            elif command == "PING":
                response = "PONG :" + args[0] + "\r\n"
                self.writer.write(response.encode())
                await self.writer.drain()
                logging.info(f"Sent PONG response")

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
                for bot in self.relay_bots:
                    await bot.send_message(relay_message)
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
        bots[i].relay_bots = [
            bot for bot in bots if bot.network_identifier != bots[i].network_identifier
        ]

    # Connect and listen
    await asyncio.gather(*(bot.connect() for bot in bots))
    await asyncio.gather(*(bot.listen() for bot in bots))


if __name__ == "__main__":
    asyncio.run(main())
