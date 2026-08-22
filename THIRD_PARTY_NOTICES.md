# Third-Party Notices

NeoRunner builds on the work of several open-source projects and public APIs.
This project is not affiliated with, endorsed by, or sponsored by any of them.
All trademarks belong to their respective owners. Sincere thanks to every
maintainer and contributor.

## Mod Loaders

| Project | Used for | Home / source |
|---------|----------|---------------|
| **NeoForge** | Primary mod loader; downloaded from the NeoForge Maven (`maven.neoforged.net`) | https://neoforged.net |
| **Minecraft Forge** | Forge loader support (`maven.minecraftforge.net`) | https://minecraftforge.net |
| **Fabric** | Fabric loader support (`meta.fabricmc.net`) | https://fabricmc.net |

## Mod Distribution & Discovery

| Project | Used for | Home / source |
|---------|----------|---------------|
| **Modrinth** | Mod search / download API (`api.modrinth.com`) | https://modrinth.com |
| **CurseForge** | Mod search / modpack CDN (`api.curseforge.com`) | https://curseforge.com |

## Tooling

| Project | Used for | Home / source |
|---------|----------|---------------|
| **ferium** | Mod profile management and dependency resolution. The binary is fetched from the official GitHub releases (`gorilla-devs/ferium`). | https://github.com/gorilla-devs/ferium |
| **Chunker** | World conversion (Java ⇄ Bedrock, version up/down-grade). `chunker-cli.jar` is fetched from `HiveGamesOSS/Chunker` releases. | https://github.com/HiveGamesOSS/Chunker / https://chunker.app |
| **Cloudflared** | Cloudflare Tunnel for public access (installed from Cloudflare's apt repo). | https://github.com/cloudflare/cloudflared |
| **ddclient** | Dynamic DNS updates. | https://ddclient.net |
| **Caddy** | Automatic HTTPS reverse proxy (optional external access). | https://caddyserver.com |
| **Eclipse Temurin / Adoptium** | Java JRE installers bundled with the modpack download (`api.adoptium.net`). | https://adoptium.net |

## APIs & Metadata

| Service | Used for | Home |
|---------|----------|------|
| **Mojang** | Minecraft version manifest (`launchermeta.mojang.com`) | https://www.minecraft.net |

## Rebuilding the loader-jar patch

The clickable-link disconnect message patches the NeoForge/Forge jars by
rewriting class-file constant pools and injecting a small helper class. That
helper is embedded as pre-compiled base64 in
`neorunner_pkg/_clickable_message.py` so servers don't need a JDK at runtime.

To recompile it yourself (against the installed Minecraft server jar):

```bash
javac --release 21 \
  -cp "libraries/net/neoforged/minecraft-server-patched/<ver>/minecraft-server-patched-<ver>.jar:<server.jar>:libraries/com/mojang/brigadier/*/brigadier-*.jar" \
  -d /tmp/out ClickableMessage.java
```

Build dependencies for recompiling the helper: a JDK (Java 21 target), the
NeoForge `minecraft-server-patched` jar and the vanilla `server.jar`, and
`com.mojang:brigadier` (all already present under `libraries/` after a normal
`neorunner setup`).
