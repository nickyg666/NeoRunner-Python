/*
 * NeoRunner Client Installer
 *
 * Installs the mod loader + mods/config for a NeoRunner server onto the
 * client's Minecraft directory.
 *
 * Flow:
 *   1. Detect the default .minecraft dir (Windows/Linux/macOS) and ask the
 *      user to confirm (or type a custom path).
 *   2. Download the loader client installer from the server and run it
 *      (NeoForge/Forge: --install-client, Fabric: client -dir).
 *   3. Download launcher.zip (mods + config + defaultconfigs) and extract
 *      into the minecraft dir.
 *   4. Print the server address to join.
 *
 * Compiled with javac -release 8 so it runs on any Java 8+ JVM.
 */

import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Enumeration;
import java.util.Properties;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

public class NeoRunnerInstaller {

    private static final String CONFIG = "/installer.properties";

    private static String baseUrl;
    private static String serverAddress;
    private static String loader;
    private static String mcVersion;
    private static String loaderVersion;

    public static void main(String[] args) throws Exception {
        Properties props = new Properties();
        try (InputStream in = NeoRunnerInstaller.class.getResourceAsStream(CONFIG)) {
            if (in == null) {
                System.err.println("ERROR: installer.properties missing from jar");
                System.exit(1);
            }
            props.load(in);
        }
        baseUrl = props.getProperty("baseUrl", "http://127.0.0.1:8000");
        serverAddress = props.getProperty("serverAddress", "127.0.0.1:25565");
        loader = props.getProperty("loader", "neoforge");
        mcVersion = props.getProperty("mcVersion", "1.21.11");
        loaderVersion = props.getProperty("loaderVersion", "");

        System.out.println();
        System.out.println("==============================================");
        System.out.println("  NeoRunner Client Installer");
        System.out.println("==============================================");
        System.out.println("  Loader : " + loader + (loaderVersion.isEmpty() ? "" : " " + loaderVersion));
        System.out.println("  MC     : " + mcVersion);
        System.out.println("  Server : " + serverAddress);
        System.out.println("  Source : " + baseUrl);
        System.out.println("==============================================");
        System.out.println();

        // 1. Find + confirm the minecraft directory
        Path mcDir = findDefaultMinecraftDir();
        System.out.println("Detected Minecraft directory:");
        System.out.println("  " + mcDir);
        System.out.println();
        System.out.print("Use this directory? [Y/n] or enter a custom path: ");
        String answer = readLine();
        if (answer != null && !answer.trim().isEmpty() && !answer.trim().equalsIgnoreCase("y")
                && !answer.trim().equalsIgnoreCase("yes")) {
            String custom = answer.trim().replace("\"", "");
            mcDir = Paths.get(custom);
        }
        Files.createDirectories(mcDir);
        System.out.println("Installing into: " + mcDir);
        System.out.println();

        // 2. Install the loader client
        Path loaderJar = download(baseUrl + "/download/loader-installer.jar", "loader-installer.jar");
        System.out.println();
        System.out.println("Installing " + loader + " client (this may take a while)...");
        int loaderRc = installLoaderClient(loaderJar, mcDir);
        if (loaderRc != 0) {
            System.err.println("WARNING: loader install exited with code " + loaderRc);
        }

        // 3. Extract mods + config
        System.out.println();
        System.out.println("Downloading mods + config...");
        Path packZip = download(baseUrl + "/download/launcher.zip", "neorunner-launcher.zip");
        extractZip(packZip, mcDir);

        // 4. Done
        System.out.println();
        System.out.println("==============================================");
        System.out.println("  INSTALLATION COMPLETE!");
        System.out.println("==============================================");
        System.out.println("  1. Open the " + loader + " profile for Minecraft " + mcVersion
                + " in your launcher");
        System.out.println("     (the loader install created it automatically)");
        System.out.println("  2. Wait for it to finish loading, then join:");
        System.out.println("     " + serverAddress);
        System.out.println();
        System.out.println("  Mods and config were placed in:");
        System.out.println("  " + mcDir);
        System.out.println("==============================================");
    }

    /* ---------------- directory detection ---------------- */

    private static Path findDefaultMinecraftDir() {
        String os = System.getProperty("os.name", "").toLowerCase();
        if (os.contains("win")) {
            String appData = System.getenv("APPDATA");
            if (appData != null && !appData.isEmpty()) {
                return Paths.get(appData, ".minecraft");
            }
            String userHome = System.getProperty("user.home", ".");
            return Paths.get(userHome, "AppData", "Roaming", ".minecraft");
        } else if (os.contains("mac")) {
            String userHome = System.getProperty("user.home", ".");
            return Paths.get(userHome, "Library", "Application Support", "minecraft");
        } else {
            String userHome = System.getProperty("user.home", ".");
            return Paths.get(userHome, ".minecraft");
        }
    }

    private static String readLine() {
        try {
            BufferedReader reader = new BufferedReader(new InputStreamReader(System.in));
            return reader.readLine();
        } catch (IOException e) {
            return "";
        }
    }

    /* ---------------- downloads ---------------- */

    private static Path download(String urlString, String fileName) throws IOException {
        System.out.println("  Downloading " + fileName + " ...");
        URL url = new URL(urlString);
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setConnectTimeout(15000);
        conn.setReadTimeout(60000);
        conn.setInstanceFollowRedirects(true);
        int status = conn.getResponseCode();
        if (status >= 400) {
            throw new IOException("HTTP " + status + " downloading " + urlString);
        }
        Path tmp = Files.createTempFile("neorunner-", ".download");
        try (InputStream in = conn.getInputStream();
             OutputStream out = new FileOutputStream(tmp.toFile())) {
            byte[] buf = new byte[65536];
            int n;
            long total = 0;
            while ((n = in.read(buf)) != -1) {
                out.write(buf, 0, n);
                total += n;
            }
            System.out.println("  Downloaded " + (total / (1024 * 1024)) + " MB");
        }
        return tmp;
    }

    /* ---------------- loader client install ---------------- */

    private static int installLoaderClient(Path installerJar, Path mcDir) throws Exception {
        String javaBin = System.getProperty("java.home") + File.separator + "bin" + File.separator + "java";
        ProcessBuilder pb;
        if ("fabric".equalsIgnoreCase(loader)) {
            pb = new ProcessBuilder(
                    javaBin, "-jar", installerJar.toAbsolutePath().toString(),
                    "client", "-dir", mcDir.toAbsolutePath().toString(),
                    "-mcversion", mcVersion,
                    loaderVersion.isEmpty() ? "" : "-loader", loaderVersion);
        } else {
            pb = new ProcessBuilder(
                    javaBin, "-jar", installerJar.toAbsolutePath().toString(),
                    "--install-client", mcDir.toAbsolutePath().toString());
        }
        pb.redirectErrorStream(true);
        Process proc = pb.start();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(proc.getInputStream()))) {
            String line;
            while ((line = reader.readLine()) != null) {
                System.out.println("    " + line);
            }
        }
        return proc.waitFor();
    }

    /* ---------------- zip extraction ---------------- */

    private static void extractZip(Path zipPath, Path destDir) throws IOException {
        try (ZipFile zip = new ZipFile(zipPath.toFile())) {
            Enumeration<? extends ZipEntry> entries = zip.entries();
            int count = 0;
            while (entries.hasMoreElements()) {
                ZipEntry entry = entries.nextElement();
                if (entry.isDirectory()) {
                    continue;
                }
                Path target = destDir.resolve(entry.getName()).normalize();
                if (!target.startsWith(destDir)) {
                    System.err.println("  SKIPPED unsafe path: " + entry.getName());
                    continue;
                }
                Files.createDirectories(target.getParent());
                try (InputStream in = zip.getInputStream(entry);
                     OutputStream out = new FileOutputStream(target.toFile())) {
                    byte[] buf = new byte[65536];
                    int n;
                    while ((n = in.read(buf)) != -1) {
                        out.write(buf, 0, n);
                    }
                }
                count++;
            }
            System.out.println("  Extracted " + count + " files into " + destDir);
        }
    }
}
