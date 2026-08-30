# RuzzStats (Paper plugin)

Tracks players online, uptime, unique members ever joined, and error
count, and serves them as JSON over a tiny built-in HTTP server so
the Ruzz Discord bot / website can show real Minecraft server stats.

**Target:** Paper **1.21.11** (Java 21)

If you run a different 1.21.x build, change the `paper-api` version in
`pom.xml` to match — see [Paper downloads](https://papermc.io/downloads)
for the exact API version string for your server.

## Build

You need **Maven** and **JDK 21** (build machine does not have to be the game server).

```bash
cd minecraft-plugin
mvn clean package
```

Produces: `target/RuzzStats-1.0.0.jar`

## Install

1. Drop `RuzzStats-1.0.0.jar` into your Paper server's `plugins/` folder.
2. Start (or restart) once — this creates `plugins/RuzzStats/config.yml`.
3. Edit that file:

```yaml
port: 8095
bind-address: "0.0.0.0"
token: "pick-something-random-here"
```

- Bot on a **different machine**: keep `0.0.0.0` and open/firewall the port so the bot can reach it.
- Bot on the **same machine**: you can use `127.0.0.1` and skip exposing the port publicly.

4. Restart the server again to apply the config.

## Point the bot at it

In Discord (admin):

```
/mc-server address:play.yourserver.com:25565 stats_url:http://YOUR_SERVER_IP:8095/stats stats_token:pick-something-random-here
```

Use the same `token` as in `config.yml`.

Then:

```
/mc-status status:online
```

The bot pings the real server (mcstatus) and this plugin's `/stats` endpoint on a schedule and stores the result for the Discord commands and `home.py` landing page.

## Test the endpoint

```bash
curl -H "X-Ruzz-Token: pick-something-random-here" http://localhost:8095/stats
```

Example response:

```json
{
  "online": true,
  "players_online": 2,
  "max_players": 20,
  "members": 47,
  "uptime_seconds": 184,
  "errors": 0,
  "tps": "20.00",
  "version": "..."
}
```
