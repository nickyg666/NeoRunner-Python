package mom.w8.neorunner;

import com.google.inject.Inject;
import com.velocitypowered.api.event.Subscribe;
import com.velocitypowered.api.event.proxy.ProxyInitializeEvent;
import com.velocitypowered.api.event.player.PlayerChooseInitialServerEvent;
import com.velocitypowered.api.plugin.Plugin;
import com.velocitypowered.api.proxy.ProxyServer;
import com.velocitypowered.api.proxy.server.RegisteredServer;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Optional;
import java.util.Properties;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * NeoRouter: routes players to their initial Velocity server based on what
 * they typed into their client's server address field.
 *
 * Forge/NeoForge clients append a NUL-separated marker (\0FML\0, \0FML3\0,
 * \0FML4\0, ...) to the handshake address; Fabric/vanilla clients do not.
 * The raw address (marker included) is available through getRawVirtualHost().
 *
 *   marker present -> registered server named "modded"
 *   no marker      -> registered server named "lobby"
 *
 * Names are overridable via plugins/neorunner-router.properties:
 *   modded=modded
 *   lobby=lobby
 */
@Plugin(id = "neorunner-router",
        name = "NeoRunner Router",
        version = "1.0.0",
        description = "Send Forge/NeoForge clients to the modded server, everyone else to the lobby",
        authors = {"nickyg666"})
public final class NeorunnerRouter {

    private final ProxyServer proxy;
    private final Logger logger = LoggerFactory.getLogger(NeorunnerRouter.class);
    private volatile String moddedName = "modded";
    private volatile String lobbyName = "lobby";
    // Where UNMARKED clients go when their protocol does NOT match the lobby:
    // "modded" lets Fabric/Quilt packs accept plain-vanilla-capable clients
    // directly (the server kicks truly incompatible ones with its own message);
    // "lobby" is the Forge-family default where vanilla users belong.
    private volatile String unmarkedFallback = "lobby";

    @Inject
    public NeorunnerRouter(ProxyServer proxy) {
        this.proxy = proxy;
    }

    @Subscribe
    public void onProxyInitialize(ProxyInitializeEvent event) {
        try {
            Path cfgFile = Path.of("plugins", "neorunner-router.properties");
            if (Files.exists(cfgFile)) {
                Properties p = new Properties();
                try (var in = Files.newInputStream(cfgFile)) {
                    p.load(in);
                }
                moddedName = p.getProperty("modded", moddedName).trim();
                lobbyName = p.getProperty("lobby", lobbyName).trim();
                String ut = p.getProperty("unmarkedTarget", "").trim().toLowerCase();
                if (ut.equals("modded") || ut.equals("lobby")) {
                    unmarkedFallback = ut;
                }
            }
        } catch (Exception e) {
            logger.warn("[NeoRunner] could not read router properties: {}", e.toString());
        }
        logger.info(
                "[NeoRunner] router ready: FML-marker clients -> '{}', everyone else -> '{}' "
                + "(unmarked fallback: '{}')",
                moddedName, lobbyName, unmarkedFallback);
    }

    @Subscribe
    public void onChooseInitialServer(PlayerChooseInitialServerEvent event) {
        if (event.getInitialServer().isPresent()) {
            return; // another plugin already made the call
        }
        // The raw virtual host is exactly what the client put in the Server
        // Address box -- including any \0FML* suffix appended by Forge/NeoForge.
        String rawHost = event.getPlayer().getRawVirtualHost().orElse("");
        boolean modloader = rawHost.contains("\u0000FML");

        // No marker means vanilla / Fabric / Quilt are indistinguishable here.
        // unmarkedFallback="modded" sends them straight to the pack server
        // (right call for Fabric/Quilt packs; a truly-incompatible client gets
        // the backend's own kick message), while "lobby" keeps them in the
        // vanilla download lobby (Forge-family default).
        boolean toModded = modloader || "modded".equals(unmarkedFallback);
        String targetName = toModded ? moddedName : lobbyName;

        Optional<RegisteredServer> target = proxy.getServer(targetName);
        if (target.isEmpty()) {
            logger.warn(
                    "[NeoRunner] registered server '{}' not found; using Velocity default", targetName);
            return;
        }
        event.setInitialServer(target.get());
        logger.info(
                "[NeoRunner] {} -> '{}' ({})",
                event.getPlayer().getUsername(),
                targetName,
                modloader ? "modloader marker" : "no marker");
    }
}
