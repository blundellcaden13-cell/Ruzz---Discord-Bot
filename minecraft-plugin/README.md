# RuzzStats (Paper plugin)

Tracks players online, uptime, unique members ever joined, and error
count, and serves them as JSON over a tiny built-in HTTP server so
the Ruzz Discord bot / website can show real Minecraft server stats.

Targets **Paper 1.21.1** (Java 21). If you're running a different
1.21.x build, bump the `paper-api` version in `pom.xml` to match —
check [papermc.io/downloads](https://papermc.io/downloads) for the
exact `-R0.1-SNAPSHOT` string for your version.

## Build

You'll need Maven and a JDK 21 installed on the machine you build on
(doesn't have to be the server itself).

```bash
cd minecraft-plugin
mvn clean package
```

This produces `target/RuzzStats-1.0.0.jar`.

## Install

1. Drop `RuzzStats-1.0.0.jar` into your Paper server's `plugins/` folder.
2. Start (or restart) the server once — this generates
   `plugins/RuzzStats/config.yml`.
3. Edit that config:
   ```yaml
   port: 8095
   bind-address: "0.0.0.0"
   token: "pick-something-random-here"
   ```
   If the Discord bot runs on a **different machine** than the
   Minecraft server, `bind-address: 0.0.0.0` and make sure `port` is
   reachable from the bot's machine (port-forward / firewall rule as
   needed). If they're on the **same machine**, you can set
   `bind-address: 127.0.0.1` instead and skip opening the port up at
   all.
4. Restart the server again to apply the config.

## Point the bot at it

In Discord, as an admin:

```
/mc-server address:play.yourserver.com:25565 stats_url:http://YOUR_SERVER_IP:8095/stats stats_token:pick-something-random-here
```

(Use the same `token` value you set in `config.yml`.)

Then announce a status:

```
/mc-status status:online
```

The bot pings both the real server address (via mcstatus) and this
plugin's `/stats` endpoint every 60 seconds and writes the combined
result to the database, which `home.py`'s landing page reads to
render the Minecraft status card.

## Test it directly

Once the server's running:

```bash
curl -H "X-Ruzz-Token: pick-something-random-here" http://localhost:8095/stats
```

Should return something like:

```json
{"online":true,"players_online":2,"max_players":20,"members":47,"uptime_seconds":184,"errors":0,"tps":"20.00","version":"..."}
```
