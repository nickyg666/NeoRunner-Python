
#!/usr/bin/env python3
import os, json, subprocess, shutil, hashlib, sys, platform, urllib.request, re, time

CONFIG="config.json"
CWD=os.getcwd()

def say(msg): print(f"[BOOT] {msg}")

def run(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

def have(cmd):
    return shutil.which(cmd) is not None

def install_pkg(pkg):
    if have("apt"):
        run(f"sudo apt update && sudo apt install -y {pkg}")
    elif have("dnf"):
        run(f"sudo dnf install -y {pkg}")
    elif have("pacman"):
        run(f"sudo pacman -Sy --noconfirm {pkg}")

def ensure_prereqs():
    say("Checking prerequisites...")
    for p in ["tmux","curl","wget"]:
        if not have(p):
            say(f"{p} missing, installing...")
            install_pkg(p)

def java_check():
    if not have("java"):
        say("Java not found. Installing OpenJDK 21...")
        install_pkg("openjdk-21-jre-headless")
    out=run("java -version").stderr
    m=re.search(r'version \"(\d+)',out)
    if m and int(m.group(1))<17:
        say("Java too old. Installing newer...")
        install_pkg("openjdk-21-jre-headless")

def parse_props():
    path=os.path.join(CWD,"server.properties")
    d={}
    if not os.path.exists(path): return None
    for line in open(path):
        if "=" in line and not line.startswith("#"):
            k,v=line.strip().split("=",1)
            d[k]=v
    return d

def ask(q,default=None):
    prompt=f"{q}"
    if default: prompt+=f" [{default}]"
    prompt+=": "
    r=input(prompt).strip()
    return r or default

def download(url,out):
    say(f"Downloading {url}")
    urllib.request.urlretrieve(url,out)

def sha256(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        while True:
            b=f.read(8192)
            if not b: break
            h.update(b)
    return h.hexdigest()

def latest_neoforge():
    return "https://maven.neoforged.net/releases/net/neoforged/neoforge/installer.jar"

def latest_forge():
    return "https://maven.minecraftforge.net/net/minecraftforge/forge/installer.jar"

def latest_fabric():
    return "https://meta.fabricmc.net/v2/versions/installer"

def setup_loader(choice,mcver):
    if choice=="neoforge":
        url=latest_neoforge()
        out="neoforge-installer.jar"
    elif choice=="forge":
        url=latest_forge()
        out="forge-installer.jar"
    else:
        data=json.loads(urllib.request.urlopen(latest_fabric()).read())
        url=data[0]["url"]
        out="fabric-installer.jar"
    download(url,out)
    say("Installer downloaded.")
    print(f"Run: java -jar {out}")

def create_config(props):
    say("Creating config...")
    cfg={}
    cfg["server_jar"]=ask("Server jar name","server.jar")
    cfg["rcon_pass"]=ask("RCON password","changeme")
    cfg["rcon_port"]=ask("RCON port",props.get("rcon.port","25575") if props else "25575")
    cfg["http_port"]=ask("HTTP mod port","8000")
    cfg["mods_dir"]=ask("Mods folder","mods")
    cfg["clientonly_dir"]=ask("Client-only folder","clientonly")
    cfg["autostart"]=ask("Autostart with system? yes/no","yes")
    cfg["loader"]=ask("Modloader (neoforge/forge/fabric)","neoforge")
    cfg["mc_version"]=ask("Minecraft version","latest")
    json.dump(cfg,open(CONFIG,"w"),indent=2)
    return cfg

def enable_rcon():
    p="server.properties"
    txt=open(p).read()
    txt=re.sub(r"enable-rcon=.*","enable-rcon=true",txt)
    if "enable-rcon" not in txt: txt+="\nenable-rcon=true\n"
    open(p,"w").write(txt)

def systemd(cfg):
    svc=f"""[Unit]
Description=Minecraft Server
After=network.target

[Service]
User={os.getenv("USER")}
WorkingDirectory={CWD}
ExecStart=/usr/bin/tmux new -d -s mc 'python3 {os.path.basename(__file__)} run'
Restart=always

[Install]
WantedBy=multi-user.target
"""
    open("mcserver.service","w").write(svc)
    say("Systemd file written: mcserver.service")
    print("Install with: sudo mv mcserver.service /etc/systemd/system/ && sudo systemctl enable mcserver")

def start_tmux(cfg):
    if "TMUX" in os.environ: return
    run(f"tmux new -d -s mc 'python3 {os.path.basename(__file__)} run'")
    say("Launched inside tmux session 'mc'")
    sys.exit(0)

def http_server(port,mods,client):
    os.chdir(mods)
    subprocess.Popen(f"python3 -m http.server {port}",shell=True)

def scan_mods(cfg):
    mods=cfg["mods_dir"]
    client=cfg["clientonly_dir"]
    os.makedirs(client,exist_ok=True)
    for f in os.listdir(mods):
        if not f.endswith(".jar"): continue
        if "client" in f.lower():
            shutil.move(os.path.join(mods,f),os.path.join(client,f))

def run_server(cfg):
    subprocess.Popen(f"java -jar {cfg['server_jar']} nogui",shell=True)

def client_instructions(cfg):
    base=f"http://YOURSERVER:{cfg['http_port']}"
    print("\n===== CLIENT SETUP =====")
    print("Install loader:",cfg["loader"])
    if cfg["loader"]=="neoforge":
        print("Run installer: java -jar neoforge-installer.jar")
    if cfg["loader"]=="forge":
        print("Run installer: java -jar forge-installer.jar")
    if cfg["loader"]=="fabric":
        print("Run installer: java -jar fabric-installer.jar")
    print("After launching game once, join server.")
    print("If mods missing, download from:",base)
    print("Put files in %appdata%/.minecraft/mods")
    print("========================\n")

def main():
    ensure_prereqs()
    java_check()
    props=parse_props()
    if not props:
        say("No server.properties found.")
        if ask("Setup server here? yes/no","yes")=="yes":
            loader=ask("Loader type","neoforge")
            mcver=ask("MC version","latest")
            setup_loader(loader,mcver)
        else:
            sys.exit(0)

    if not os.path.exists(CONFIG):
        cfg=create_config(props)
        if props and props.get("enable-rcon","false")!="true":
            if ask("Enable RCON automatically?","yes")=="yes":
                enable_rcon()
    else:
        cfg=json.load(open(CONFIG))

    if len(sys.argv)>1 and sys.argv[1]=="run":
        http_server(cfg["http_port"],cfg["mods_dir"],cfg["clientonly_dir"])
        scan_mods(cfg)
        run_server(cfg)
        while True: time.sleep(60)

    if cfg.get("autostart")=="yes":
        systemd(cfg)

    start_tmux(cfg)

    client_instructions(cfg)

if __name__=="__main__":
    main()
