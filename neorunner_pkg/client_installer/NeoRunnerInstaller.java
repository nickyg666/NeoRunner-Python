/*
 * NeoRunner Client Installer
 *
 * Self-contained installer with a Swing GUI. Installs the mod loader +
 * mods/config for a NeoRunner server onto the client's Minecraft directory.
 *
 * Flow:
 *   1. Detect the default .minecraft dir and show it in a text field
 *      (Browse... allows a custom path).
 *   2. Download the loader client installer from the server and run it
 *      quietly (NeoForge/Forge: --install-client, Fabric: client -dir).
 *   3. Extract the embedded pack.zip (mods + config + defaultconfigs) into
 *      the minecraft dir. No second download needed.
 *   4. Show a completion dialog with the server address.
 *
 * If no GUI is available (headless), it falls back to a minimal console
 * flow. Output from the loader installer is redirected to a temp log so
 * the client only sees high-level progress.
 *
 * Compiled with javac -source 8 -target 8 so it runs on any Java 8+ JVM.
 */

import java.awt.BorderLayout;
import java.awt.FlowLayout;
import java.awt.GraphicsEnvironment;
import java.awt.GridLayout;
import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;
import java.util.Properties;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

import javax.swing.BorderFactory;
import javax.swing.JButton;
import javax.swing.JFileChooser;
import javax.swing.JFrame;
import javax.swing.JLabel;
import javax.swing.JOptionPane;
import javax.swing.JPanel;
import javax.swing.JProgressBar;
import javax.swing.JTextField;
import javax.swing.SwingUtilities;
import javax.swing.SwingWorker;
import javax.swing.UIManager;

public class NeoRunnerInstaller {

    private static final String CONFIG = "/installer.properties";
    private static final String PACK = "/pack.zip";

    private String baseUrl;
    private String serverAddress;
    private String loader;
    private String mcVersion;
    private String loaderVersion;

    private JFrame frame;
    private JTextField dirField;
    private JProgressBar progress;
    private JLabel status;
    private JButton installBtn;

    public static void main(String[] args) throws Exception {
        NeoRunnerInstaller inst = new NeoRunnerInstaller();
        if (GraphicsEnvironment.isHeadless()) {
            inst.runConsole();
        } else {
            inst.showGui();
        }
    }

    private NeoRunnerInstaller() throws Exception {
        Properties props = new Properties();
        try (InputStream in = NeoRunnerInstaller.class.getResourceAsStream(CONFIG)) {
            if (in == null) {
                throw new IllegalStateException("installer.properties missing from jar");
            }
            props.load(in);
        }
        baseUrl = props.getProperty("baseUrl", "http://127.0.0.1:8000");
        serverAddress = props.getProperty("serverAddress", "127.0.0.1:25565");
        loader = props.getProperty("loader", "neoforge");
        mcVersion = props.getProperty("mcVersion", "1.21.11");
        loaderVersion = props.getProperty("loaderVersion", "");
    }

    /* ---------------- GUI ---------------- */

    private void showGui() {
        try {
            UIManager.setLookAndFeel(UIManager.getSystemLookAndFeelClassName());
        } catch (Exception ignored) {
        }
        dirField = new JTextField(34);
        progress = new JProgressBar();
        status = new JLabel("Ready");
        installBtn = new JButton("Install");
        frame = new JFrame("NeoRunner Client Installer");
        frame.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
        frame.setLayout(new BorderLayout(12, 12));

        JPanel info = new JPanel(new GridLayout(4, 1, 4, 2));
        info.setBorder(BorderFactory.createTitledBorder("Server"));
        info.add(new JLabel("Loader : " + loader + (loaderVersion.isEmpty() ? "" : " " + loaderVersion)));
        info.add(new JLabel("MC     : " + mcVersion));
        info.add(new JLabel("Server : " + serverAddress));
        info.add(new JLabel("Source : " + baseUrl));

        dirField.setText(findDefaultMinecraftDir().toString());
        JButton browse = new JButton("Browse...");
        browse.addActionListener(e -> chooseDirectory());

        JPanel dirRow = new JPanel(new FlowLayout(FlowLayout.LEFT, 8, 0));
        dirRow.add(dirField);
        dirRow.add(browse);

        JPanel dirPanel = new JPanel(new BorderLayout(0, 4));
        dirPanel.setBorder(BorderFactory.createTitledBorder("Minecraft directory"));
        dirPanel.add(dirRow, BorderLayout.NORTH);
        dirPanel.add(status, BorderLayout.CENTER);
        dirPanel.add(progress, BorderLayout.SOUTH);

        progress.setIndeterminate(false);
        progress.setStringPainted(false);

        installBtn.addActionListener(e -> install());
        JPanel buttons = new JPanel(new FlowLayout(FlowLayout.RIGHT));
        buttons.add(installBtn);

        JPanel center = new JPanel(new BorderLayout(0, 12));
        center.add(info, BorderLayout.NORTH);
        center.add(dirPanel, BorderLayout.CENTER);

        frame.add(center, BorderLayout.CENTER);
        frame.add(buttons, BorderLayout.SOUTH);

        frame.setSize(560, 300);
        frame.setLocationRelativeTo(null);
        frame.setResizable(false);
        frame.setVisible(true);
    }

    private void chooseDirectory() {
        JFileChooser chooser = new JFileChooser();
        chooser.setFileSelectionMode(JFileChooser.DIRECTORIES_ONLY);
        if (chooser.showOpenDialog(frame) == JFileChooser.APPROVE_OPTION) {
            dirField.setText(chooser.getSelectedFile().getAbsolutePath());
        }
    }

    private void setStatus(final String text) {
        SwingUtilities.invokeLater(() -> status.setText(text));
    }

    private void install() {
        final Path mcDir = Paths.get(dirField.getText().trim().replace("\"", ""));
        installBtn.setEnabled(false);
        progress.setIndeterminate(true);

        SwingWorker<Void, String> worker = new SwingWorker<Void, String>() {
            @Override
            protected Void doInBackground() throws Exception {
                try {
                    publish("Creating directory...");
                    Files.createDirectories(mcDir);

                    publish("Downloading " + loader + " installer...");
                    Path loaderJar = download(baseUrl + "/download/loader-installer.jar", "loader-installer.jar");
                    log("Downloaded loader installer (" + loaderJar.toFile().length() / 1024 + " KB)");

                    publish("Installing " + loader + " client (may take a minute)...");
                    int rc = installLoaderClient(loaderJar, mcDir);
                    if (rc != 0) {
                        log("Loader installer exited with code " + rc);
                    }

                    publish("Extracting mods and config...");
                    int count = extractPack(mcDir);

                    publish("Done!");
                    log("Extracted " + count + " files. Join at " + serverAddress);
                    SwingUtilities.invokeLater(() -> JOptionPane.showMessageDialog(
                            frame,
                            "Installation complete!\n\nJoin the server at:\n  " + serverAddress
                                    + "\n\nMods and config were placed in:\n  " + mcDir,
                            "NeoRunner Installer",
                            JOptionPane.INFORMATION_MESSAGE));
                } catch (Exception ex) {
                    log("ERROR: " + ex.getMessage());
                    SwingUtilities.invokeLater(() -> JOptionPane.showMessageDialog(
                            frame,
                            "Installation failed:\n" + ex.getMessage(),
                            "NeoRunner Installer",
                            JOptionPane.ERROR_MESSAGE));
                }
                return null;
            }

            @Override
            protected void process(List<String> chunks) {
                for (String chunk : chunks) {
                    status.setText(chunk);
                }
            }

            @Override
            protected void done() {
                installBtn.setEnabled(true);
                progress.setIndeterminate(false);
            }
        };
        worker.execute();
    }

    private void log(String line) {
        System.out.println("[installer] " + line);
    }

    /* ---------------- console fallback ---------------- */

    private void runConsole() throws Exception {
        System.out.println("NeoRunner Client Installer (console mode)");
        Path mcDir = findDefaultMinecraftDir();
        System.out.print("Minecraft directory [" + mcDir + "]: ");
        String answer = readLine();
        if (answer != null && !answer.trim().isEmpty() && !answer.trim().equalsIgnoreCase("y")
                && !answer.trim().equalsIgnoreCase("yes")) {
            mcDir = Paths.get(answer.trim().replace("\"", ""));
        }
        Files.createDirectories(mcDir);
        log("Installing into " + mcDir);

        log("Downloading " + loader + " installer...");
        Path loaderJar = download(baseUrl + "/download/loader-installer.jar", "loader-installer.jar");
        log("Installing " + loader + " client...");
        int rc = installLoaderClient(loaderJar, mcDir);
        log("Loader installer exited with code " + rc);

        log("Extracting mods and config...");
        int count = extractPack(mcDir);
        log("Done! Extracted " + count + " files. Join at " + serverAddress);
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
            BufferedReader reader = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
            return reader.readLine();
        } catch (IOException e) {
            return "";
        }
    }

    /* ---------------- downloads ---------------- */

    private static Path download(String urlString, String fileName) throws IOException {
        URL url = new URL(urlString);
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setConnectTimeout(15000);
        conn.setReadTimeout(60000);
        conn.setInstanceFollowRedirects(true);
        // Cloudflare bot protection returns 403 for the default Java/<version>
        // User-Agent, so present a browser UA for all downloads.
        conn.setRequestProperty("User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36");
        conn.setRequestProperty("Accept", "*/*");
        int status = conn.getResponseCode();
        if (status >= 400) {
            throw new IOException("HTTP " + status + " downloading " + urlString);
        }
        Path tmp = Files.createTempFile("neorunner-", ".download");
        try (InputStream in = conn.getInputStream();
             OutputStream out = new FileOutputStream(tmp.toFile())) {
            byte[] buf = new byte[65536];
            int n;
            while ((n = in.read(buf)) != -1) {
                out.write(buf, 0, n);
            }
        }
        return tmp;
    }

    /* ---------------- loader client install (quiet) ---------------- */

    private int installLoaderClient(Path installerJar, Path mcDir) throws Exception {
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
        // Redirect all loader-installer output to a temp log so the client
        // doesn't see hundreds of lines of progress spam.
        Path logFile = Files.createTempFile("neorunner-loader-", ".log");
        pb.redirectOutput(logFile.toFile());
        pb.redirectErrorStream(true);
        Process proc = pb.start();
        int rc = proc.waitFor();
        if (rc != 0) {
            printLogTail(logFile, 25);
        }
        Files.deleteIfExists(logFile);
        return rc;
    }

    private static void printLogTail(Path logFile, int lines) throws IOException {
        try (BufferedReader reader = Files.newBufferedReader(logFile, StandardCharsets.UTF_8)) {
            String line;
            while ((line = reader.readLine()) != null) {
                System.out.println("  " + line);
            }
        }
    }

    /* ---------------- zip extraction (embedded pack) ---------------- */

    private static int extractPack(Path destDir) throws IOException {
        InputStream in = NeoRunnerInstaller.class.getResourceAsStream(PACK);
        if (in == null) {
            throw new IOException("pack.zip missing from jar");
        }
        int count = 0;
        try (ZipInputStream zip = new ZipInputStream(in)) {
            ZipEntry entry;
            while ((entry = zip.getNextEntry()) != null) {
                if (entry.isDirectory()) {
                    continue;
                }
                Path target = destDir.resolve(entry.getName()).normalize();
                if (!target.startsWith(destDir)) {
                    System.out.println("  SKIPPED unsafe path: " + entry.getName());
                    continue;
                }
                Files.createDirectories(target.getParent());
                try (OutputStream out = new FileOutputStream(target.toFile())) {
                    byte[] buf = new byte[65536];
                    int n;
                    while ((n = zip.read(buf)) != -1) {
                        out.write(buf, 0, n);
                    }
                }
                count++;
            }
        }
        return count;
    }
}
