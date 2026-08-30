package com.ruzz.stats;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;
import org.bukkit.Bukkit;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.player.PlayerJoinEvent;
import org.bukkit.plugin.java.JavaPlugin;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;
import java.util.logging.Handler;
import java.util.logging.Level;
import java.util.logging.LogRecord;
import java.util.logging.Logger;

/**
 * RuzzStats — exposes live server stats over a tiny built-in HTTP
 * server so the Ruzz Discord bot (cogs/mc_status.py) can show real
 * player counts, uptime, error counts, and unique-member totals on
 * the website, on top of the plain reachability ping mcstatus does.
 *
 * Endpoint: GET /stats  ->  JSON:
 *   {
 *     "online": true,
 *     "players_online": 5,
 *     "max_players": 20,
 *     "members": 134,           // unique players who have EVER joined
 *     "uptime_seconds": 3725,   // since this plugin was enabled
 *     "errors": 2,              // SEVERE log records seen since enable
 *     "tps": "19.98",
 *     "version": "..."
 *   }
 *
 * See config.yml for the port / bind address / auth token.
 */
public class RuzzStatsPlugin extends JavaPlugin implements Listener {

    private long enabledAtMillis;
    private final AtomicLong errorCount = new AtomicLong(0);
    private final Set<UUID> knownMembers = ConcurrentHashMap.newKeySet();
    private java.io.File membersFile;
    private HttpServer httpServer;
    private Handler errorCountingHandler;

    @Override
    public void onEnable() {
        saveDefaultConfig();
        enabledAtMillis = System.currentTimeMillis();

        membersFile = new java.io.File(getDataFolder(), "members.txt");
        loadMembers();

        Bukkit.getPluginManager().registerEvents(this, this);
        attachErrorCounter();
        startHttpServer();

        int port = getConfig().getInt("port", 8095);
        getLogger().info("RuzzStats enabled — stats server listening on port " + port
                + " (" + knownMembers.size() + " known members loaded)");
    }

    @Override
    public void onDisable() {
        if (httpServer != null) {
            httpServer.stop(0);
        }
        if (errorCountingHandler != null) {
            try {
                Logger.getLogger("").removeHandler(errorCountingHandler);
            } catch (SecurityException ignored) {
            }
        }
        saveMembers();
    }

    // ─────────────────────────────────────
    // Unique member tracking
    // ─────────────────────────────────────

    @EventHandler
    public void onJoin(PlayerJoinEvent event) {
        UUID id = event.getPlayer().getUniqueId();
        if (knownMembers.add(id)) {
            Bukkit.getScheduler().runTaskAsynchronously(this, this::saveMembers);
        }
    }

    private void loadMembers() {
        if (!membersFile.exists()) return;
        try {
            for (String line : Files.readAllLines(membersFile.toPath(), StandardCharsets.UTF_8)) {
                line = line.trim();
                if (line.isEmpty()) continue;
                try {
                    knownMembers.add(UUID.fromString(line));
                } catch (IllegalArgumentException ignored) {
                    // skip malformed lines rather than fail the whole load
                }
            }
        } catch (IOException e) {
            getLogger().warning("Could not load members.txt: " + e.getMessage());
        }
    }

    private synchronized void saveMembers() {
        try {
            getDataFolder().mkdirs();
            List<String> lines = new ArrayList<>();
            for (UUID id : knownMembers) lines.add(id.toString());
            Files.write(membersFile.toPath(), lines, StandardCharsets.UTF_8,
                    StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
        } catch (IOException e) {
            getLogger().warning("Could not save members.txt: " + e.getMessage());
        }
    }

    // ─────────────────────────────────────
    // Error counting
    // ─────────────────────────────────────
    // Best-effort: hooks the java.util.logging root logger so SEVERE
    // records from anywhere on the server get counted, not just this
    // plugin's own code. If your setup routes console output through
    // a different logging bridge this may stay at 0 — every other
    // field in /stats still works regardless.

    private void attachErrorCounter() {
        errorCountingHandler = new Handler() {
            @Override
            public void publish(LogRecord record) {
                if (record.getLevel().intValue() >= Level.SEVERE.intValue()) {
                    errorCount.incrementAndGet();
                }
            }

            @Override
            public void flush() {
            }

            @Override
            public void close() throws SecurityException {
            }
        };
        try {
            Logger.getLogger("").addHandler(errorCountingHandler);
        } catch (SecurityException e) {
            getLogger().warning("Could not attach error counter: " + e.getMessage());
        }
    }

    // ─────────────────────────────────────
    // HTTP stats server
    // ─────────────────────────────────────

    private void startHttpServer() {
        int port = getConfig().getInt("port", 8095);
        String bind = getConfig().getString("bind-address", "0.0.0.0");
        String token = getConfig().getString("token", "");

        try {
            httpServer = HttpServer.create(new InetSocketAddress(bind, port), 0);
            httpServer.createContext("/stats", new StatsHandler(token));
            httpServer.setExecutor(null);
            httpServer.start();
        } catch (IOException e) {
            getLogger().severe("RuzzStats could not start its HTTP server on "
                    + bind + ":" + port + " — " + e.getMessage());
        }
    }

    private class StatsHandler implements HttpHandler {
        private final String token;

        StatsHandler(String token) {
            this.token = token;
        }

        @Override
        public void handle(HttpExchange exchange) throws IOException {
            try {
                if (token != null && !token.isBlank()) {
                    String provided = exchange.getRequestHeaders().getFirst("X-Ruzz-Token");
                    if (provided == null || !provided.equals(token)) {
                        sendJson(exchange, 401, "{\"error\":\"unauthorized\"}");
                        return;
                    }
                }

                long uptimeSeconds = (System.currentTimeMillis() - enabledAtMillis) / 1000;
                int online = Bukkit.getOnlinePlayers().size();
                int max = Bukkit.getMaxPlayers();

                String json = "{"
                        + "\"online\":true,"
                        + "\"players_online\":" + online + ","
                        + "\"max_players\":" + max + ","
                        + "\"members\":" + knownMembers.size() + ","
                        + "\"uptime_seconds\":" + uptimeSeconds + ","
                        + "\"errors\":" + errorCount.get() + ","
                        + "\"tps\":" + formatTps() + ","
                        + "\"version\":\"" + escape(Bukkit.getVersion()) + "\""
                        + "}";
                sendJson(exchange, 200, json);
            } catch (Exception e) {
                getLogger().warning("RuzzStats /stats handler error: " + e.getMessage());
                sendJson(exchange, 500, "{\"error\":\"internal error\"}");
            }
        }

        private void sendJson(HttpExchange exchange, int status, String body) throws IOException {
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(status, bytes.length);
            try (OutputStream os = exchange.getResponseBody()) {
                os.write(bytes);
            }
        }

        private String escape(String s) {
            return s == null ? "" : s.replace("\\", "\\\\").replace("\"", "\\\"");
        }

        private String formatTps() {
            try {
                double[] tps = Bukkit.getTPS(); // Paper-only API
                return String.format("%.2f", tps[0]);
            } catch (Throwable t) {
                return "null";
            }
        }
    }
}
