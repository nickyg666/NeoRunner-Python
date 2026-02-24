"""NeoForge modloader implementation"""
import os
import re
from loaders.base import LoaderBase


class NeoForgeLoader(LoaderBase):
    """NeoForge-specific server launcher and management"""
    
    def prepare_environment(self):
        """Setup NeoForge server environment"""
        self.log_message("LOADER_NEOFORGE", f"Preparing {self.get_loader_display_name()} environment ({self.mc_version})")
        
        # NeoForge uses @args files
        self._setup_jvm_args()
        self._setup_server_properties()
        self._setup_eula()
        
        self.log_message("LOADER_NEOFORGE", "Environment ready (using @args files)")
    
    def _setup_jvm_args(self):
        """Create user_jvm_args.txt with memory settings"""
        jvm_file = os.path.join(self.cwd, "user_jvm_args.txt")
        
        # Get memory settings from config
        xmx = self.cfg.get("xmx", "6G")
        xms = self.cfg.get("xms", "4G")
        
        # Always regenerate to pick up config changes
        jvm_args = f"""-Xmx{xmx}
-Xms{xms}
-XX:+UseG1GC
-XX:MaxGCPauseMillis=200
-XX:+ParallelRefProcEnabled
-XX:+UnlockExperimentalVMOptions
-XX:G1NewCollectionPercentage=30
-XX:G1MaxNewCollectionLength=16777216
-XX:+PerfDisableSharedMem
-XX:+AlwaysPreTouch
"""
        with open(jvm_file, 'w') as f:
            f.write(jvm_args)
    
    def _setup_server_properties(self):
        """Setup server.properties with RCON and basic settings"""
        props_file = os.path.join(self.cwd, "server.properties")
        
        properties = {
            "enable-rcon": "true",
            "rcon.password": self.cfg.get("rcon_pass", "changeme"),
            "rcon.port": str(self.cfg.get("rcon_port", 25575)),
            "server-port": str(self.cfg.get("server_port", 1234)),
            "motd": "NeoRunner - NeoForge Server",
            "level-name": "world",
            "gamemode": "survival",
            "difficulty": "normal",
            "max-players": "20",
            "online-mode": "false",
            "pvp": "true",
            "allow-flight": "true"
        }
        
        # Read existing if present
        existing = {}
        if os.path.exists(props_file):
            try:
                with open(props_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            if '=' in line:
                                k, v = line.split('=', 1)
                                existing[k] = v
            except:
                pass
            properties.update(existing)
        
        # Only override RCON settings if not set
        if not existing.get("enable-rcon"):
            properties["enable-rcon"] = "true"
            properties["rcon.password"] = self.cfg.get("rcon_pass", "changeme")
            properties["rcon.port"] = str(self.cfg.get("rcon_port", 25575))
        
        # Write back
        with open(props_file, 'w') as f:
            for k, v in sorted(properties.items()):
                f.write(f"{k}={v}\n")
    
    def _setup_eula(self):
        """Create eula.txt"""
        eula_file = os.path.join(self.cwd, "eula.txt")
        if not os.path.exists(eula_file):
            with open(eula_file, 'w') as f:
                f.write("eula=true\n")
    
    def build_java_command(self):
        """Build NeoForge launch command"""
        # NeoForge uses @args files
        java_cmd = [
            "java",
            "@user_jvm_args.txt",
            f"@libraries/net/neoforged/neoforge/{self._get_neoforge_version()}/unix_args.txt",
            "nogui"
        ]
        return java_cmd
    
    def _get_neoforge_version(self):
        """Extract NeoForge version from libraries"""
        lib_path = os.path.join(self.cwd, "libraries/net/neoforged/neoforge")
        if os.path.exists(lib_path):
            versions = [d for d in os.listdir(lib_path) if os.path.isdir(os.path.join(lib_path, d))]
            if versions:
                return sorted(versions)[-1]  # Latest version
        return "21.11.38-beta"  # Fallback
    
    def detect_crash_reason(self, log_output):
        """Parse NeoForge crash logs for common issues.
        
        Returns dict with:
            type: 'missing_dep', 'mod_error', 'mod_conflict', 'version_mismatch', 'unknown'
            dep: name of missing dependency (for missing_dep)
            culprit: mod ID that caused the crash (if identifiable)
            culprits: list of all involved mod IDs (for conflicts involving multiple mods)
            message: relevant portion of the crash log
        """
        log_text = log_output if isinstance(log_output, str) else ""
        log_lower = log_text.lower()
        
        # ---- EXTRACT CRASH REPORT SECTION if present ----
        # NeoForge crash reports have a structured section starting with
        # "---- Minecraft Crash Report ----" or "Crash report saved to"
        crash_section = log_text
        crash_marker = log_text.find("---- Minecraft Crash Report ----")
        if crash_marker >= 0:
            crash_section = log_text[crash_marker:]
        
        # Also look for FML-specific error blocks
        fml_error = ""
        for marker in ["net.neoforged.fml.ModLoadingException", 
                        "LoadingExceptionModCrash",
                        "FML detected errors during loading"]:
            idx = log_lower.find(marker.lower())
            if idx >= 0:
                fml_error = log_text[max(0, idx - 200):idx + 1000]
                break
        
        # Use the most relevant section for the message
        relevant_log = fml_error or crash_section[:2000] or log_text[-2000:]
        
        MOD_ID = r'[\w.\-]+'
        
        # ---- 0. INVALID/CORRUPT JAR FILE ----
        # "File mods/farming-for-blockheads-7463289.jar is not a jar file"
        bad_jar_match = re.search(r'file\s+mods/(\S+\.jar)\s+is\s+not\s+a\s+jar\s+file', log_lower)
        if bad_jar_match:
            bad_file = bad_jar_match.group(1)
            # Extract a slug-like token from the filename
            slug = re.sub(r'[-_]?\d.*$', '', bad_file.replace('.jar', '')).lower()
            return {
                "type": "mod_error",
                "culprit": slug or bad_file,
                "culprits": [slug or bad_file],
                "message": f"File mods/{bad_file} is not a valid JAR (likely a corrupt download or HTML error page)",
                "bad_file": bad_file
            }
        
        # ---- 0.3. MIXIN ERROR WITH CLIENT CLASS ----
        # "MixinTransformerError" with "Error loading class" for client-side classes
        # Also catches "Attach error for X from mod Y" patterns
        mixin_client_match = re.search(r"mixintransformererror|MixinPreProcessorException.*from\s+mod\s+(" + MOD_ID + r")", log_text, re.IGNORECASE)
        if mixin_client_match or (re.search(r"error\s+loading\s+class:.*client", log_lower) and re.search(r"from\s+mod\s+(" + MOD_ID + r")", log_text)):
            # Extract mod ID from "from mod X" pattern
            from_mod_match = re.search(r"from\s+mod\s+(" + MOD_ID + r")", log_text)
            culprit_mod = from_mod_match.group(1).lower() if from_mod_match else None
            culprit_file = None
            if culprit_mod:
                # Find the JAR file
                jar_pattern = rf"mods/([^\s/]*{re.escape(culprit_mod)}[^\s/]*\.jar)"
                jar_match = re.search(jar_pattern, log_lower)
                if jar_match:
                    culprit_file = jar_match.group(1)
            return {
                "type": "mod_error",
                "subtype": "client_only",
                "culprit": culprit_mod,
                "culprits": [culprit_mod] if culprit_mod else [],
                "message": f"Client-only mod mixin crash: {culprit_mod or 'unknown'}",
                "bad_file": culprit_file
            }
        
        # ---- 0.5. CLIENT-ONLY MOD CRASH ----
        # Detect mods that reference client-side classes (Screen, MouseHandler, etc.)
        # on a dedicated server.  These are NOT mixin conflicts — the mod simply
        # cannot run without a client.  Must be checked BEFORE mixin conflict
        # detection to prevent false positive quarantines.
        client_class_patterns = [
            r"noclassdeffounderror:\s+net/minecraft/client/",
            r"classnotfoundexception:\s+net\.minecraft\.client\.",
            r"noclassdeffounderror:\s+com/mojang/blaze3d/",
            r"classnotfoundexception:\s+com\.mojang\.blaze3d\.",
            r"noclassdeffounderror:\s+net/minecraft/client/sounds/",
        ]
        
        all_client_crashes = []
        for cp in client_class_patterns:
            if re.search(cp, log_lower):
                # Find ALL mods that failed with client class errors
                # Pattern: "Failed to create mod instance. ModID: X"
                fail_patterns = [
                    r"failed\s+to\s+create\s+mod\s+instance\.\s*modid:\s*(" + MOD_ID + r")",
                    r"modid:\s*(" + MOD_ID + r")[^\n]*noclassdeffounderror",
                    r"\[(" + MOD_ID + r")\][^\n]*failed",
                ]
                for fp in fail_patterns:
                    for match in re.finditer(fp, log_lower):
                        mod_id = match.group(1)
                        if mod_id not in all_client_crashes:
                            all_client_crashes.append(mod_id)
                
                # Also try extracting from "Mod file: X.jar"
                for match in re.finditer(r"mod\s+file:\s+\S*mods/(\S+\.jar)", log_lower):
                    culprit_file = match.group(1)
                    culprit_mod = re.sub(r'[-_]?\d.*$', '', culprit_file.replace('.jar', '')).lower()
                    if culprit_mod and culprit_mod not in all_client_crashes:
                        all_client_crashes.append(culprit_mod)
                
                # Also try from mod X patterns
                for match in re.finditer(r"from\s+mod\s+(" + MOD_ID + r")", log_text):
                    mod_id = match.group(1).lower()
                    if mod_id not in all_client_crashes:
                        all_client_crashes.append(mod_id)
                
                break
        
        if all_client_crashes:
            # Get the jar files for all culprits
            bad_files = []
            for culprit_mod in all_client_crashes:
                jar_pattern = rf"mods/([^\s/]*{re.escape(culprit_mod)}[^\s/]*\.jar)"
                jar_match = re.search(jar_pattern, log_lower)
                if jar_match:
                    bad_files.append(jar_match.group(1))
            
            return {
                "type": "mod_error",
                "subtype": "client_only",
                "culprit": all_client_crashes[0] if all_client_crashes else None,
                "culprits": all_client_crashes,
                "message": f"Client-only mod crash: {', '.join(all_client_crashes)} reference client classes not available on server",
                "bad_file": bad_files[0] if bad_files else None,
                "bad_files": bad_files
            }
        
        # ---- 1. MISSING MOD DEPENDENCY ----
        missing_patterns = [
            # "mod X requires Y Z or above" — X is the culprit, Y is the missing dep
            (r"mod\s+(" + MOD_ID + r")\s+requires?\s+(" + MOD_ID + r")", 1, 2),
            # "Failure message: Mod X requires Y"
            (r"failure\s+message:\s+mod\s+(" + MOD_ID + r")\s+requires?\s+(" + MOD_ID + r")", 1, 2),
            # "missing or unsupported mandatory dependencies: X {Y}" 
            (r"missing\s+(?:or\s+unsupported\s+)?(?:mandatory\s+)?dependenc(?:y|ies)[:\s]+(" + MOD_ID + r")", None, 1),
            # "could not find required mod: X"
            (r"could\s+not\s+find\s+(?:required\s+mod[:\s]+)?(" + MOD_ID + r")", None, 1),
            # "missing dependency: X"
            (r"missing\s+dependency[:\s]+(" + MOD_ID + r")", None, 1),
            # NeoForge specific: "Mod File X needs Y"
            (r"mod\s+file\s+\S+\s+needs\s+(" + MOD_ID + r")", None, 1),
        ]
        
        for pattern, culprit_group, dep_group in missing_patterns:
            match = re.search(pattern, log_lower)
            if match:
                dep_name = match.group(dep_group)
                culprit = match.group(culprit_group) if culprit_group else None
                return {
                    "type": "missing_dep",
                    "dep": dep_name,
                    "culprit": culprit,
                    "culprits": [culprit] if culprit else [],
                    "message": relevant_log[:1000]
                }
        
        # ---- 2. MOD CONFLICTS (duplicate registries, incompatible mods) ----
        # These are common when two biome mods (BOP + BYG) or two tech mods clash
        
        # NOTE: Mixin "overwrite conflict" WARNINGS with "Skipping method" are NOT crashes!
        # The mixin framework handles these gracefully - one mod's mixin is skipped, server boots fine.
        # Only detect ACTUAL mixin ERRORS (MixinApplyError, MixinTransformerError, etc.)
        
        def _extract_mod_id_from_mixin_path(path_or_id):
            if not path_or_id:
                return None
            s = path_or_id.lower().strip()
            if '.' not in s:
                return s
            parts = s.split('.')
            skip_words = {'mixin', 'mixins', 'common', 'client', 'server', 'api', 'impl', 'core', 'internal', 'util', 'handler', 'access', 'wrapper', 'hook', 'patch', 'transform', 'chunk', 'world', 'entity', 'block', 'item', 'screen', 'container', 'packet', 'network', 'data', 'config'}
            mixin_idx = -1
            for i, part in enumerate(parts):
                if 'mixin' in part:
                    mixin_idx = i
                    break
            if mixin_idx > 0:
                for i in range(mixin_idx - 1, -1, -1):
                    part = parts[i]
                    if part in skip_words or part in ('dev', 'com', 'org', 'net', 'io', 'me', 'xyz'):
                        continue
                    if len(part) >= 3:
                        return part
            for part in reversed(parts):
                if part in skip_words:
                    continue
                if len(part) >= 3 and not part.startswith('class') and not part.startswith('mixin'):
                    return part
            return parts[-1] if parts else s
        
        benign_mixin_conflict = False
        mod1, mod2, method_name, mixin_class = None, None, None, None
        benign_mixin_match = re.search(
            r"overwrite\s+conflict\s+for\s+(\S+)\s+in\s+(\S+)\s+from\s+(?:mod\s+)?(" + MOD_ID + r")[\s,].*?"
            r"previously\s+(?:written|defined)\s+by\s+(.+?)\.?\s+Skipping\s+method\.?",
            log_text, re.IGNORECASE
        )
        if benign_mixin_match:
            method_name = benign_mixin_match.group(1)
            mixin_class = benign_mixin_match.group(2)
            mod1 = benign_mixin_match.group(3).lower()
            mod2_raw = benign_mixin_match.group(4)
            mod2 = _extract_mod_id_from_mixin_path(mod2_raw)
            benign_mixin_conflict = True
        
        conflict_patterns = [
            # "DuplicateModsFoundException" — two versions of same mod
            (r"duplicatemodsfoundexception.*?(\S+\.jar).*?(\S+\.jar)", "duplicate"),
            # Duplicate registry key: "Registry key already exists: modid:name"
            (r"duplicate\s+(?:registry\s+)?(?:key|entry|id)[:\s]+(" + MOD_ID + r"[:/]" + MOD_ID + r")", "registry"),
            # "is already registered" patterns
            (r"(" + MOD_ID + r"[:/]" + MOD_ID + r")\s+is\s+already\s+registered", "registry"),
            # "Mixin apply failed" — only match if mod ID is on same line (prevents false positives
            # from benign warnings like "Failed reading REFMAP JSON" which have "mixin" in the prefix)
            (r"mixin\s+apply\s+for\s+mod\s+(" + MOD_ID + r")\s+failed", "mixin_fail"),
            # MixinApplyError with specific mod
            (r"mixinapplyerror.*?mod[:\s]+(" + MOD_ID + r")", "mixin_fail"),
            # Mixin transformer error (actual crash, not just warning)
            (r"mixintransformererror.*?from\s+mod\s+(" + MOD_ID + r")", "mixin_error"),
            # Incompatible mod set 
            (r"incompatible\s+mod(?:s)?\s+(?:set|found|detected)", "incompatible"),
            # "conflicts with"
            (r"(" + MOD_ID + r")\s+conflicts?\s+with\s+(" + MOD_ID + r")", "conflict"),
        ]
        
        if benign_mixin_conflict:
            return {
                "type": "benign_mixin_warning",
                "conflict_type": "mixin_overwrite_handled",
                "culprit": None,
                "culprits": [mod1, mod2] if mod1 and mod2 else [],
                "message": f"Mixin overwrite warning (handled gracefully): {mod1} and {mod2} both target {method_name} in {mixin_class}. One mixin was skipped - this is NOT a crash."
            }
        
        for pattern, conflict_type in conflict_patterns:
            match = re.search(pattern, log_lower)
            if match:
                culprits = [g for g in match.groups() if g]
                # For registry conflicts, try to extract the mod namespace from "modid:name"
                if conflict_type == "registry" and culprits:
                    ns = culprits[0].split(":")[0] if ":" in culprits[0] else culprits[0].split("/")[0]
                    culprits = [ns]
                
                # For mixin conflicts, extract proper mod ID if it's a package path
                if conflict_type in ("mixin_fail", "mixin_error"):
                    culprits = [_extract_mod_id_from_mixin_path(c) for c in culprits]
                
                primary_culprit = culprits[-1] if culprits else None
                
                return {
                    "type": "mod_conflict",
                    "conflict_type": conflict_type,
                    "culprit": primary_culprit,
                    "culprits": culprits,
                    "message": relevant_log[:1000]
                }
        
        # ---- 3. SPECIFIC MOD ERRORS (crash traceable to a single mod) ----
        mod_error_patterns = [
            # "Error loading mod: mod_id"
            (r"error\s+loading\s+mod[:\s]+(" + MOD_ID + r")", 1),
            # "Mod mod_id has crashed"
            (r"mod\s+(" + MOD_ID + r")\s+has\s+crashed", 1),
            # "Exception caught during firing of event ... mod_id"
            (r"exception\s+.*?mod[:\s]+(" + MOD_ID + r")", 1),
            # "Caused by mod: mod_id"
            (r"caused\s+by\s+mod[:\s]+(" + MOD_ID + r")", 1),
            # "ModLoadingException: ... mod_id"
            (r"modloadingexception.*?(" + MOD_ID + r")", 1),
            # NeoForge: "Mod X (modid) encountered an error during ..."
            (r"mod\s+\S+\s+\((" + MOD_ID + r")\)\s+encountered\s+an?\s+error", 1),
        ]
        
        for pattern, group in mod_error_patterns:
            match = re.search(pattern, log_lower)
            if match:
                culprit = match.group(group)
                # Filter out generic/framework mod IDs that are never the real culprit
                if culprit not in ("minecraft", "neoforge", "fml", "forge", "java", "net"):
                    return {
                        "type": "mod_error",
                        "culprit": culprit,
                        "culprits": [culprit],
                        "message": relevant_log[:1000]
                    }
        
        # ---- 4. TRY TO EXTRACT CULPRIT FROM STACK TRACES ----
        # Look for mod namespaces in stack traces (e.g., "at com.biomesoplenty.init...")
        # Common namespace patterns for popular mods
        stack_ns_patterns = [
            (r"at\s+(?:com|net|dev|io|org)\.(\w+)\.(\w+)\.", None),  # at com.author.modname.Class
        ]
        
        # Only use stack trace analysis if we haven't found a culprit yet
        # and there's a real crash (not just warnings)
        if "exception" in log_lower or "error" in log_lower or "crash" in log_lower:
            # Look for the last non-minecraft, non-java package in stack trace
            stack_mods = re.findall(r"at\s+(?:com|net|dev|io|org)\.([\w]+)\.([\w]+)\.", log_lower)
            # Filter out framework packages
            framework_pkgs = {"mojang", "minecraft", "neoforged", "neoforge", "cpw", "fml",
                              "google", "gson", "apache", "netty", "oshi", "slf4j", "log4j",
                              "java", "sun", "jdk", "spongepowered", "mixin"}
            mod_pkgs = [(a, m) for a, m in stack_mods if a not in framework_pkgs and m not in framework_pkgs]
            
            if mod_pkgs:
                # Most likely culprit is the first mod-specific class in the stack
                author, modname = mod_pkgs[0]
                culprit_guess = modname
                return {
                    "type": "mod_error",
                    "culprit": culprit_guess,
                    "culprits": [culprit_guess],
                    "message": relevant_log[:1000]
                }
        
        # ---- 5. GENERIC MOD LOADING ERROR ----
        if any(kw in log_lower for kw in ["fml", "neoforge", "modloading"]) and "error" in log_lower:
            return {
                "type": "mod_error",
                "culprit": None,
                "culprits": [],
                "message": relevant_log[:1000]
            }
        
        # ---- 6. VERSION MISMATCH ----
        if "version" in log_lower and ("mismatch" in log_lower or "incompatible" in log_lower):
            return {
                "type": "version_mismatch",
                "culprit": None,
                "culprits": [],
                "message": relevant_log[:1000]
            }
        
        return {
            "type": "unknown",
            "culprit": None,
            "culprits": [],
            "message": relevant_log[:1000]
        }
