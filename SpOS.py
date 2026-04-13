# SpOS.py - v1.0 - Estilo Hacknet completo con mejoras para simular un SO real (historial de comandos, autocompletado básico, más comandos, manejo de ~)
# Solo Python estándar + subprocess para música y comandos + readline para historial (si disponible)
import sys
import os
# from smbprotocol.connection import Connection  # Importado de forma perezosa en hack()
import time
import random
import shutil
import subprocess
import platform
import getpass
import json
import socket
import threading
import queue

try:
    import readline  # Historial y autocompletado
except ImportError:
    readline = None  # No disponible en Windows por defecto, pero no es crítico
# ───────────── Colores ANSI estilo Hacknet ─────────────
GREEN = "\033[32m"
BRIGHT_GREEN = "\033[92m"
DARK_GREEN = "\033[2;32m"
CYAN = "\033[36m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = "\033[95m"
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
INVERSE = "\033[7m"
BLINK = "\033[5m"
SHADOW = "*******"
shadow = SHADOW
host = f"{SHADOW}-0{random.randint(1,9)}"

DEFAULT_CHAT_HOST = "127.0.0.1"
DEFAULT_CHAT_PORT = 5000


class ChatManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._inbox = queue.Queue()
        self._server_sock = None
        self._server_thread = None
        self._server_stop = threading.Event()
        self._clients = set()  # conexiones activas (server-side)

        self._client_sock = None  # client-side
        self._client_thread = None
        self._client_stop = threading.Event()
        self._connected_to = None

    def start_server(self, host="0.0.0.0", port=DEFAULT_CHAT_PORT):
        with self._lock:
            if self._server_thread and self._server_thread.is_alive():
                return True, f"Servidor ya activo en puerto {port}."

            self._server_stop.clear()
            try:
                self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self._server_sock.bind((host, port))
                self._server_sock.listen(10)
                self._server_sock.settimeout(0.5)  # para poder parar sin bloquear
            except Exception as e:
                try:
                    if self._server_sock:
                        self._server_sock.close()
                except Exception:
                    pass
                self._server_sock = None
                return False, f"No se pudo iniciar servidor: {e}"

            self._server_thread = threading.Thread(
                target=self._server_loop,
                args=(port,),
                daemon=True,
            )
            self._server_thread.start()
            return True, f"Servidor iniciado (escuchando en 0.0.0.0:{port})."

    def _server_loop(self, port):
        while not self._server_stop.is_set():
            try:
                conn, addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except Exception:
                break

            with self._lock:
                self._clients.add(conn)
            self._inbox.put(f"[server] Cliente conectado: {addr[0]}:{addr[1]}")
            t = threading.Thread(target=self._handle_client, args=(conn, addr), daemon=True)
            t.start()

        with self._lock:
            clients = list(self._clients)
            self._clients.clear()
            sock = self._server_sock
            self._server_sock = None
        for c in clients:
            try:
                c.close()
            except Exception:
                pass
        try:
            if sock:
                sock.close()
        except Exception:
            pass

    def _handle_client(self, conn, addr):
        try:
            conn.settimeout(0.5)
            while not self._server_stop.is_set():
                try:
                    data = conn.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    break
                msg = data.decode("utf-8", errors="ignore")
                self._inbox.put(f"[{addr[0]}:{addr[1]}] {msg}")
        except Exception as e:
            self._inbox.put(f"[server] Error con {addr[0]}:{addr[1]}: {e}")
        finally:
            with self._lock:
                try:
                    self._clients.discard(conn)
                except Exception:
                    pass
            try:
                conn.close()
            except Exception:
                pass
            self._inbox.put(f"[server] Cliente desconectado: {addr[0]}:{addr[1]}")

    def stop_server(self):
        with self._lock:
            if not (self._server_thread and self._server_thread.is_alive()):
                return True, "Servidor no estaba activo."
            self._server_stop.set()
        return True, "Deteniendo servidor..."

    def connect_client(self, host=DEFAULT_CHAT_HOST, port=DEFAULT_CHAT_PORT):
        with self._lock:
            if self._client_thread and self._client_thread.is_alive():
                return True, f"Ya conectado a {self._connected_to}."

            self._client_stop.clear()
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(3)
                s.connect((host, port))
                s.settimeout(0.5)
            except Exception as e:
                try:
                    s.close()
                except Exception:
                    pass
                return False, f"No se pudo conectar a {host}:{port}: {e}"

            self._client_sock = s
            self._connected_to = f"{host}:{port}"
            self._client_thread = threading.Thread(target=self._client_recv_loop, daemon=True)
            self._client_thread.start()
            return True, f"Conectado como cliente a {host}:{port}."

    def _client_recv_loop(self):
        while not self._client_stop.is_set():
            try:
                data = self._client_sock.recv(4096)
            except socket.timeout:
                continue
            except Exception:
                break
            if not data:
                break
            msg = data.decode("utf-8", errors="ignore")
            self._inbox.put(f"[server] {msg}")

        with self._lock:
            sock = self._client_sock
            self._client_sock = None
            self._connected_to = None
        try:
            if sock:
                sock.close()
        except Exception:
            pass
        self._inbox.put("[client] Desconectado del servidor.")

    def disconnect_client(self):
        with self._lock:
            if not (self._client_thread and self._client_thread.is_alive()):
                return True, "Cliente no estaba conectado."
            self._client_stop.set()
            sock = self._client_sock
            self._client_sock = None
            self._connected_to = None
        try:
            if sock:
                sock.close()
        except Exception:
            pass
        return True, "Desconectando cliente..."

    def send(self, message):
        if not message.strip():
            return False, "Mensaje vacío."

        sent_any = False
        with self._lock:
            client_sock = self._client_sock
            server_clients = list(self._clients)

        if client_sock:
            try:
                client_sock.send(message.encode("utf-8"))
                sent_any = True
            except Exception as e:
                self._inbox.put(f"[client] Error enviando: {e}")

        if server_clients:
            payload = message.encode("utf-8")
            dead = []
            for c in server_clients:
                try:
                    c.send(payload)
                    sent_any = True
                except Exception:
                    dead.append(c)
            if dead:
                with self._lock:
                    for c in dead:
                        self._clients.discard(c)
                        try:
                            c.close()
                        except Exception:
                            pass

        if not sent_any:
            return False, "No hay conexión activa (usa `chat join` o inicia servidor con `chat`)."
        self._inbox.put(f"(tú) {message}")
        return True, "Mensaje enviado."

    def drain_inbox(self, max_items=50):
        items = []
        for _ in range(max_items):
            try:
                items.append(self._inbox.get_nowait())
            except queue.Empty:
                break
        return items


chat_mgr = ChatManager()
def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')
def type_text(text, delay=0.015, extra_random=False, end="\n"):
    """Efecto de tipeo letra por letra como en Hacknet, con end opcional"""
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(delay + random.uniform(-0.008, 0.012) if extra_random else delay)
    sys.stdout.write(end)
    sys.stdout.flush()
def bit_message():
    type_text(f"""{YELLOW}
-14 DAY TIMER EXPIRED : INITIALIZING FAILSAFE-
______________________________________________ 
 
 
Hi.
. . .

This is strange... Stranger than I expected.
 
I guess I'm supposed to write this in past tense, though I hardly feel like admitting it's over.
 
My name is Bit, and if you're reading this, I'm already dead.

                {RESET}""", delay=0.01)    

# ============================= Usuarios ==============================
# Usuarios y contraseñas (hasheadas simples para simulación; en real usar hashing)
usuarios = {
    "SP": "shadow123",
    "KM": "sp es mi hermano",
    "guest": "guest",
    "Admin": "rootaccess",
    "JB": "3267935"
}

# Login
clear_screen()
try:
    login = input(f"{BOLD}{BLINK}Usuario: {RESET}")
except EOFError:
    login = "guest"
if login in usuarios:
    try:
        login_password = getpass.getpass(f"{BOLD}{BLINK}Contraseña: {RESET}")
    except EOFError:
        login_password = "guest"
    if login_password == usuarios[login]:
        type_text(f"{GREEN}{BOLD}{BLINK}Acceso concedido. Bienvenido {login}.{RESET}", delay=0.05)
        user = f"{CYAN}{login}@{host}{RESET}"
        type_text(f"""
        
{CYAN}_____________________
{CYAN}|                   |
{CYAN}| {user}{CYAN}/SpOS|
{CYAN}|Encriptado_{shadow} |
{CYAN}|___________________| 


        """, delay=0.02)
    else:
        type_text(f"{RED}{BOLD}{BLINK}Acceso denegado. Contraseña incorrecta.{RESET}", delay=0.05)
        time.sleep(1)
        sys.exit(1)
else:
    type_text(f"{RED}{BOLD}{BLINK}Acceso denegado. Usuario no reconocido.{RESET}", delay=0.05)
    sys.exit(1)

# ==================================== Carga inicial ====================================
print("\n")
type_text(f"{CYAN}{BOLD}{BLINK}Iniciando SpOS v1.0...{RESET}", delay=0.05)
for i in range(1, 101):
    barra = "█" * i + "░" * (100 - i)
    porcentaje = i
    sys.stdout.write(f"{GREEN}\r[{barra}] {porcentaje}%")
    sys.stdout.flush()
    time.sleep(random.uniform(0.05, 0.15))

type_text(f"\n{GREEN}{BOLD}{BLINK}Carga completa. Iniciando sistema...{RESET}", delay=0.05)
print("\n")

# Ruta al archivo de música (ajusta según tu sistema)
MUSIC_FILE = "https://raw.githubusercontent.com/bizancio11/SpOS/main/09.Revolve (R Mix).mp3"#os.path.join(os.path.dirname(__file__), "09. Revolve (R Mix).mp3") # Asegúrate de tener este archivo en el mismo directorio
  # Cambia a tu archivo: .mp3, .wav, .ogg

def play_background_music():
    """Intenta reproducir música en background usando reproductor del sistema"""
    if not os.path.exists(MUSIC_FILE):
        type_text(f"{YELLOW}Archivo de música '{MUSIC_FILE}' no encontrado. Usando fallback beeps.{RESET}", delay=0.05)
        return beep_fallback(4)

    system = platform.system()
    try:
        if system == "Windows":
            subprocess.Popen(f'start "" "{MUSIC_FILE}"', shell=True)
        
        elif system == "Linux":
            players = [
                ["mpg123", "-q", "--loop", "-1", MUSIC_FILE],
                ["aplay", "-q", MUSIC_FILE],  # wav solo
                ["ffplay", "-nodisp", "-autoexit", "-loop", "0", MUSIC_FILE]
            ]
            for player in players:
                try:
                    subprocess.Popen(player, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return  # Salir si uno funciona
                except:
                    continue
        
        elif system == "Darwin":  # macOS
            subprocess.Popen(["afplay", MUSIC_FILE])
        
    
    except Exception:
        type_text(f"{RED}No se pudo iniciar música. Reproduce manualmente.{RESET}", delay=0.05)

def beep_fallback(count=3):
    """Beeps cyberpunk si no hay música"""
    for _ in range(count):
        print("\a", end="", flush=True)
        time.sleep(0.4)



def boot_sequence():
    clear_screen()

    # Iniciar música durante el boot
    play_background_music()
    barra2 = "=" * 30 
    time.sleep(0.01) 
    type_text(f"{CYAN}{BOLD}{BLINK}Iniciando secuencia de arranque...\n{RESET}", delay=0.05)
    type_text(f"{CYAN}{barra2}{RESET}", delay=0.05)
    time.sleep(1.5)
    type_text(f"{CYAN}\nSoftware: SpOS v1.0 - Simulación de Sistema Operativo {RESET}", delay=0.05)
    time.sleep(1.5)
    type_text(f"{CYAN}\nDesarrollador: SP - Plataforma: {platform.system()} {platform.release()}{RESET}", delay=0.05)
    
     # Pausa larga para efecto dramático
    clear_screen()

    boot_msgs = [
        "SpOS Kernel v1.0 booting...",
        "Mounting filesystem...",
        "Initializing shadow protocols...",
        "Loading kernel modules...",
        "Bypassing Uplink-7 firewall...",
        "Obfuscating trace vector...",
        "Loading node cache... [47 nodes detected]",
        "Proxy chain established: 4 hops",
        "ETAS (Emergency Trace Aversion) online",
        f"Welcome back, operative {os.getlogin().upper()}/{user}.",
        "Type 'help' to begin sequence."
    ]

    for msg in boot_msgs:
        type_text(f"{CYAN}{DIM}> {msg}{RESET}", delay=0.018, extra_random=True)
        time.sleep(random.uniform(0.3, 1.1))

    print(f"\n{BRIGHT_GREEN}{BOLD}SYSTEM ONLINE - AWAITING COMMAND{RESET}\n")
    time.sleep(1.2)



def draw_header(current_dir, login, user, host):
    cols, _ = shutil.get_terminal_size()
    path = current_dir.replace(os.path.expanduser("~"), "~")
    header = f"SpOS v1.0  {user}{GREEN}:{path}{RESET} "
    border = "═" * (cols - len(header) - 4)

    print(f"{GREEN}{BOLD}╔{border}╗{RESET}")
    print(f"{GREEN}{BOLD}║ {header.center(cols-4)} ║{RESET}")
    print(f"{GREEN}{BOLD}╚{border}╝{RESET}\n")

def draw_side_info():
    print(f"{DARK_GREEN}{DIM}┌────── ACTIVE TRACE ──────┐{RESET}")
    print(f"{DARK_GREEN}{DIM}│ Uptime   : {time.strftime('%H:%M:%S')}      │{RESET}")
    print(f"{DARK_GREEN}{DIM}│ Hops     : 4                 │{RESET}")
    print(f"{DARK_GREEN}{DIM}│ Kernel   : SpOS v1.0         │{RESET}")
    print(f"{DARK_GREEN}{DIM}└──────────────────────────┘{RESET}\n")

def show_help():
    type_text(f"{CYAN}{BOLD}COMANDOS DISPONIBLES:{RESET}")
    cmds = [
        "help       → este panel",
        "info       → info del sistema",
        "ls [dir]   → listar nodos/archivos",
        "dir        → alias para ls",
        "cd <dir>   → cambiar directorio (soporta ~)",
        "pwd        → mostrar directorio actual",
        "mkdir <dir>→ crear directorio",
        "rmdir <dir>→ eliminar directorio vacío",
        "touch <file>→ crear archivo vacío",
        "rm <file>  → eliminar archivo",
        "cat <file> → ver contenido de archivo",
        "echo <text> [> <file>] → imprimir o escribir texto",
        "edit <file>→ editar archivo (nano/notepad)",
        "cp <src> <dst> → copiar archivo/directorio",
        "mv <src> <dst> → mover/renombrar",
        "whoami     → mostrar usuario actual",
        "uname      → info del sistema",
        "shadow true/false → ocultar/mostrar usuario",
        "date       → mostrar fecha/hora",
        "uptime     → tiempo de actividad",
        "probe      → analizar puertos",
        "ping <host>→ probar conexión",
        "hack <target>→ simular hackeo",
        "clear      → limpiar pantalla",
        "reboot     → reiniciar sistema",
        "exec       → ejecutar comando del sistema",
        "chat       → iniciar chat multiusuario (servidor local)",
        "chat join [host] [port] → unirse a sala de chat",
        "chat send <mensaje> → enviar mensaje en sala",
        "ETAS_ON/OFF → activar/desactivar modo oculto (ETAS)",
        "chat list → listar nuevos mensajes",
        "chat leave → salir de sala",
        "chat api   → info de la API HTTP (salas, si está disponible)",
        "exit       → salir (apagar)"
    ]
    for cmd in cmds:
        type_text(f"  {GREEN}{cmd}{RESET}", delay=0.012)

def hack():
    ip = input(f"{CYAN}Introduce la IP del equipo remoto: {RESET}")
    # Módulo opcional: no romper SpOS si no está instalado
    try:
        from smbprotocol.connection import Connection
    except ImportError:
        type_text(
            f"{YELLOW}El módulo 'smbprotocol' no está instalado. "
            f"Instálalo con 'pip install smbprotocol' para usar este comando.{RESET}",
            delay=0.05,
        )
        return

    try:
        conn = Connection(
            username=os.getlogin(),
            password=str(os.getpid()),
            my_name=socket.gethostname(),
            remote_name=ip,
            use_ntlm_v2=True,
        )
        conn.connect(ip, 139)
        type_text(f"{GREEN}Conexión establecida con éxito.{RESET}", delay=0.05)
        type_text(f"{GREEN}¡Hackeo simulado! Acceso concedido a {ip}.{RESET}", delay=0.05)
    except Exception as e:
        type_text(f"{RED}Error al establecer la conexión: {e}{RESET}", delay=0.05)



# Configurar autocompletado básico si readline disponible
if readline:
    commands = ["help", "ls", "dir", "cd", "pwd", "mkdir", "shadow_true", "shadow_false", "info", "bit", "reboot", "shadow", "shadow_overload", "rmdir", "touch", "rm", "cat", "echo", "edit", "cp", "mv", "whoami", "uname", "date", "uptime", "scan", "probe", "ping", "hack", "clear", "reboot", "chat", "exit"]
    def completer(text, state):
        options = [cmd for cmd in commands if cmd.startswith(text)]
        if state < len(options):
            return options[state]
        else:
            return None
    readline.parse_and_bind("tab: complete")
    readline.set_completer(completer)

def sp_os_shell(user, login, shadow, SHADOW):
    # Arrancar Chat API (Flask/Waitress) en segundo plano si está disponible
    try:
        from chat_api import start_in_background, CHAT_API_PORT
        start_in_background(CHAT_API_PORT)
        # Se muestra en help que la API está disponible
    except ImportError:
        pass  # flask/waitress no instalados; el chat por sockets sigue funcionando
    boot_sequence()
    current_dir = os.getcwd()
    start_time = time.time()
    # ──────────────────────────────────────────────
    # LOOP PRINCIPAL DE COMANDOS
    # ──────────────────────────────────────────────
    while True:
        try:
            draw_header(current_dir, login, user, host)
            draw_side_info()

            prompt = f"{BRIGHT_GREEN}{BOLD}{user}/SpOS:{GREEN}{current_dir.replace(os.path.expanduser('~'), '~')}$ {RESET}"
            type_text(prompt, delay=0.006, extra_random=False, end="")
            cmd_input = input("").strip()
            if readline:
                readline.add_history(cmd_input)  # Agregar al historial

            cmd_parts = cmd_input.split()
            if not cmd_parts:
                continue

            cmd = cmd_parts[0].lower()

            if cmd in ["exit", "logout", "quit"]:
                type_text(f"{RED}{BLINK}TRACE TERMINATED. SESSION CLOSED\nSHUTING DOWN SpOS v1.0.{RESET}", delay=0.03)
                time.sleep(1.8)
                print("\n")
                type_text(f"{RED}Apagando sistema...{RESET}")
                for i in range(1, 101):
                    barra = "█" * i + "░" * (100 - i)
                    porcentaje = i
                    sys.stdout.write(f"{RED}\r[{barra}] {porcentaje}%")
                    sys.stdout.flush()
                    time.sleep(random.uniform(0.05, 0.15))
                print()  # Nueva línea después de la barra
                type_text(f"{RED}SISTEMA APAGADO{RESET}", delay=0.05)
                type_text(f"""
                    {RED}________________________
                    {RED}|   SISTEMA APAGADO    |{RESET}
                    {RED}|  SPOS v1.0 CERRADO   |{RESET}
                    {RED}|______________________|{RESET}
                
                    """, delay=0.05)
                time.sleep(1)
                clear_screen()
                sys.exit(0)

            elif cmd == "help":
                show_help()

            elif cmd in ["ls", "dir"]:
                target_dir = cmd_parts[1] if len(cmd_parts) > 1 else current_dir
                target_dir = os.path.expanduser(target_dir) if target_dir.startswith("~") else target_dir
                try:
                    files = os.listdir(target_dir)
                    for f in sorted(files):
                        type_text(f"  → {GREEN}{f}{RESET}", delay=0.008)
                except Exception as e:
                    type_text(f"{RED}Error: {str(e)}{RESET}")

            elif cmd == "cd":
                if len(cmd_parts) < 2:
                    type_text(f"{RED}Uso: cd <dir>{RESET}")
                    continue
                target = " ".join(cmd_parts[1:])
                target = os.path.expanduser(target) if target.startswith("~") else target
                try:
                    os.chdir(target)
                    current_dir = os.getcwd()
                    type_text(f"{CYAN}Cambiado a: {target}{RESET}")
                except Exception as e:
                    type_text(f"{RED}Error: {str(e)}{RESET}")

            elif cmd == "pwd":
                type_text(f"{CYAN}{current_dir}{RESET}")

            elif cmd == "mkdir":
                if len(cmd_parts) < 2:
                    type_text(f"{RED}Uso: mkdir <dir>{RESET}")
                    continue
                target = " ".join(cmd_parts[1:])
                try:
                    os.makedirs(target, exist_ok=True)
                    type_text(f"{GREEN}Directorio creado: {target}{RESET}")
                except Exception as e:
                    type_text(f"{RED}Error: {str(e)}{RESET}")

            elif cmd == "rmdir":
                if len(cmd_parts) < 2:
                    type_text(f"{RED}Uso: rmdir <dir>{RESET}")
                    continue
                target = " ".join(cmd_parts[1:])
                try:
                    shutil.rmtree(target)
                    type_text(f"{GREEN}Directorio eliminado: {target}{RESET}")
                except Exception as e:
                    type_text(f"{RED}Error: {str(e)}{RESET}")

            elif cmd == "touch":
                if len(cmd_parts) < 2:
                    type_text(f"{RED}Uso: touch <file>{RESET}")
                    continue
                target = " ".join(cmd_parts[1:])
                try:
                    open(target, 'a').close()
                    type_text(f"{GREEN}Archivo creado: {target}{RESET}")
                except Exception as e:
                    type_text(f"{RED}Error: {str(e)}{RESET}")

            elif cmd == "rm":
                if len(cmd_parts) < 2:
                    type_text(f"{RED}Uso: rm <file>{RESET}")
                    continue
                target = " ".join(cmd_parts[1:])
                try:
                    if os.path.isdir(target):
                        shutil.rmtree(target)
                        type_text(f"{GREEN}Directorio eliminado: {target}{RESET}")
                    else:
                        os.remove(target)
                        type_text(f"{GREEN}Archivo eliminado: {target}{RESET}")
                except Exception as e:
                    type_text(f"{RED}Error: {str(e)}{RESET}")

            elif cmd == "cat":
                if len(cmd_parts) < 2:
                    type_text(f"{RED}Uso: cat <file>{RESET}")
                    continue
                target = " ".join(cmd_parts[1:])
                try:
                    with open(target, 'r') as f:
                        content = f.read()
                    type_text(f"{CYAN}{content}{RESET}", delay=0.01)
                except Exception as e:
                    type_text(f"{RED}Error: {str(e)}{RESET}")

            elif cmd == "echo":
                if len(cmd_parts) < 2:
                    type_text(f"{RED}Uso: echo <text> [> <file>]{RESET}")
                    continue
                if ">" in cmd_input:
                    parts = cmd_input.split(">", 1)
                    text = parts[0].replace("echo", "").strip()
                    file = parts[1].strip()
                    try:
                        with open(file, 'w') as f:
                            f.write(text + "\n")
                        type_text(f"{GREEN}Texto escrito en {file}{RESET}")
                    except Exception as e:
                        type_text(f"{RED}Error: {str(e)}{RESET}")
                else:
                    text = " ".join(cmd_parts[1:])
                    type_text(f"{CYAN}{text}{RESET}")

            elif cmd == "edit":
                edit_input = input(f"{CYAN}Ingrese el archivo a editar: {RESET}")
                edit_input2 = os.path.expanduser(edit_input) if edit_input.startswith("~") else edit_input
                editor = "notepad" if os.name == 'nt' else "nano"
                try:
                    subprocess.run([editor, edit_input2])
                except Exception as e:
                    type_text(f"{RED}Error: {str(e)}{RESET}")
        
            elif cmd == "cp":
                if len(cmd_parts) < 3:
                    type_text(f"{RED}Uso: cp <src> <dst>{RESET}")
                    continue
                src = cmd_parts[1]
                dst = " ".join(cmd_parts[2:])
                try:
                    if os.path.isdir(src):
                        shutil.copytree(src, dst)
                    else:
                        shutil.copy(src, dst)
                    type_text(f"{GREEN}Copiado: {src} a {dst}{RESET}")
                except Exception as e:
                    type_text(f"{RED}Error: {str(e)}{RESET}")

            elif cmd == "mv":
                if len(cmd_parts) < 3:
                    type_text(f"{RED}Uso: mv <src> <dst>{RESET}")
                    continue
                src = cmd_parts[1]
                dst = " ".join(cmd_parts[2:])
                try:
                    shutil.move(src, dst)
                    type_text(f"{GREEN}Movido: {src} a {dst}{RESET}")
                except Exception as e:
                    type_text(f"{RED}Error: {str(e)}{RESET}")

            elif cmd == "whoami":
                type_text(f"{CYAN}{user}{RESET}")

            elif cmd == "uname":
                type_text(f"{CYAN}SpOS v1.0 - {platform.system()} Kernel{RESET}")

            elif cmd == "date":
                type_text(f"{CYAN}{time.strftime('%Y-%m-%d %H:%M:%S')}{RESET}")

            elif cmd == "uptime":
                uptime_sec = time.time() - start_time
                uptime_str = time.strftime("%H:%M:%S", time.gmtime(uptime_sec))
                type_text(f"{CYAN}Uptime: {uptime_str}{RESET}")

            elif cmd == "chat":
                try:
                    # Chat no-bloqueante:
                    # - `chat` inicia servidor (puerto fijo DEFAULT_CHAT_PORT) en background
                    # - `chat join` conecta como cliente a DEFAULT_CHAT_HOST:DEFAULT_CHAT_PORT
                    # - `chat send <mensaje>` envía por cliente y/o a clientes conectados al servidor local
                    # - `chat list` muestra mensajes recibidos (cola)
                    # - `chat leave` desconecta cliente y detiene servidor
                    if len(cmd_parts) == 1:
                        ok, msg = chat_mgr.start_server(port=DEFAULT_CHAT_PORT)
                        if ok:
                            type_text(f"{GREEN}{msg}{RESET}")
                            type_text(f"{CYAN}El SpOS sigue corriendo mientras se conectan clientes. Usa `chat list` para ver actividad.{RESET}")
                        else:
                            type_text(f"{RED}{msg}{RESET}")
                        continue

                    sub = cmd_parts[1].lower()
                    if sub == "join":
                        chat_host = DEFAULT_CHAT_HOST
                        chat_port = DEFAULT_CHAT_PORT
                        if len(cmd_parts) >= 3:
                            chat_host = cmd_parts[2]
                        if len(cmd_parts) >= 4:
                            try:
                                chat_port = int(cmd_parts[3])
                            except ValueError:
                                type_text(f"{RED}Puerto inválido: {cmd_parts[3]}{RESET}")
                                continue
                        ok, msg = chat_mgr.connect_client(host=chat_host, port=chat_port)
                        type_text(f"{GREEN if ok else RED}{msg}{RESET}")
                        continue

                    if sub == "send":
                        if len(cmd_parts) < 3:
                            type_text(f"{RED}Uso: chat send <mensaje>{RESET}")
                            continue
                        message = " ".join(cmd_parts[2:])
                        ok, msg = chat_mgr.send(message)
                        type_text(f"{GREEN if ok else RED}{msg}{RESET}")
                        continue

                    if sub == "list":
                        items = chat_mgr.drain_inbox(max_items=50)
                        if not items:
                            type_text(f"{YELLOW}Sin mensajes nuevos.{RESET}")
                        else:
                            for it in items:
                                type_text(f"{MAGENTA}{it}{RESET}", delay=0.004)
                        continue

                    if sub == "leave":
                        ok1, msg1 = chat_mgr.disconnect_client()
                        ok2, msg2 = chat_mgr.stop_server()
                        type_text(f"{CYAN}{msg1}{RESET}")
                        type_text(f"{CYAN}{msg2}{RESET}")
                        continue

                    if sub == "api":
                        try:
                            from chat_api import CHAT_API_PORT
                            type_text(f"{GREEN}Chat API HTTP en http://127.0.0.1:{CHAT_API_PORT}{RESET}")
                            type_text(f"{CYAN}  GET  /         → estado | POST /create/<sala> | /join/<sala>/<user> | /send/<sala>/<user> | GET /messages/<sala> | /stats{RESET}")
                        except ImportError:
                            type_text(f"{YELLOW}Chat API no disponible (instala flask y waitress).{RESET}")
                        continue

                    type_text(f"{RED}Uso: chat | chat join | chat send <msg> | chat list | chat leave | chat api{RESET}")

                except Exception as e:
                    type_text(f"{RED}Error en el módulo de chat: {e}{RESET}")

            elif cmd == "probe":
                type_text(f"{MAGENTA}Probing ports...{RESET}")
                time.sleep(0.9)
                ports = [21, 22, 80, 443]
                for port in ports:
                    status = random.choice(['OPEN', 'CLOSED', 'FILTERED'])
                    type_text(f"  Port {port}   → {status}")

            elif cmd == "ping":
                ping_input = input(f"{CYAN}Ingrese el host a pingear: {RESET}")
                ping = os.system(f"ping {ping_input} -n 1" if os.name == 'nt' else f"ping {ping_input} -c 1")
                if ping == 0:
                    type_text(f"{CYAN}Ping a {ping_input} exitoso.{RESET}")
                else:
                    type_text(f"{CYAN}Ping a {ping_input} fallido.{RESET}")
                type_text(f"{CYAN}Ping a {ping_input} completado.{RESET}")

            elif cmd == "hack":
                hack()

            elif cmd == "clear":
                clear_screen()

            elif cmd == "reboot":
                boot_sequence()

            elif cmd == "shadow_overload":
                type_text(f"{RED}ENCRIPTADO SHADOW INICIADO", delay=0.05)
                ShadowInput = getpass.getpass(f"{BOLD}{BLINK}Contraseña: {RESET}")
                if ShadowInput == "45shadow67" and (login == "SP" or "KM" or "JB"):
                    type_text(f"{GREEN}{BOLD}{BLINK}Acceso concedido. Bienvenido {user}.{RESET}", delay=0.05)
                    type_text(f"""
                    {RED}____________________
                    {RED}|                   |
                    {RED}| {user}/sh/SpOS    |
                    {RED}| Encriptado_SHADOW |
                    {RED}|___________________|

                    """, delay=0.02)
                    ShadowInput2 = input(f"{CYAN}Ingrese el código de sobrecarga: shadow_OVERLOAD/{RESET}")
                    
                    while ShadowInput2 != "salir":
                        if ShadowInput2 == "usuarios":
                            type_text(f"{YELLOW}{usuarios}", delay=0.05)
                            ShadowInput2 = input(f"{CYAN}Ingrese el código de sobrecarga: shadow_OVERLOAD/{RESET}")
                            type_text("\n", delay=0.05)
                            continue
                        elif ShadowInput2 == "salir":
                            type_text(f"{RED}SALIENDO DE ENCRIPTADO SHADOW...{RESET}", delay=0.05)
                            time.sleep(1)
                            ShadowInput2 = input(f"{CYAN}Ingrese el código de sobrecarga: shadow_OVERLOAD/{RESET}")
                            type_text("\n", delay=0.05)
                            continue
                        elif ShadowInput2 == "shadow_help":
                            type_text(f"""
                            {CYAN}{BOLD}COMANDOS DISPONIBLES EN ENCRIPTADO SHADOW:{RESET}
                            {GREEN}usuarios       → listar usuarios del sistema
                                archivos       → listar archivos en el directorio actual
                                salir          → salir del modo encriptado shadow
                                shadow_help   → mostrar este panel de ayuda
                            """, delay=0.02)
                            ShadowInput2 = input(f"{CYAN}Ingrese el código de sobrecarga: shadow_OVERLOAD/{RESET}")
                            type_text("\n", delay=0.05)
                            continue
                        elif ShadowInput2 == "archivos":
                            files = os.listdir(current_dir)
                            for f in sorted(files):
                                type_text(f"  → {GREEN}{f}{RESET}", delay=0.008)
                            ShadowInput2 = input(f"{CYAN}Ingrese el código de sobrecarga: shadow_OVERLOAD/{RESET}")
                            type_text("\n", delay=0.05)
                            continue
                        elif ShadowInput2 == "salir":
                            type_text(f"{RED}SALIENDO DE ENCRIPTADO SHADOW...{RESET}", delay=0.05)
                            time.sleep(1)
                            break
                        
            
                            
                        else:
                            type_text(f"{RED}Comando no reconocido en ENCRIPTADO SHADOW. Usa 'shadow_help'{RESET}", delay=0.05)
                            ShadowInput2 = input(f"{CYAN}Ingrese el código de sobrecarga: shadow_OVERLOAD/{RESET}")
                            print("\n")
                            continue
                else:
                    type_text(f"{RED}{BOLD}{BLINK}Acceso denegado. Contraseña incorrecta\n\nENCRIPTADO SHADOW FINALIZADO\n{user}/SpOS.{RESET}", delay=0.05)
                    type_text(f"{RED}\nSALIENDO DE ENCRIPTADO SHADOW...{RESET}", delay=0.05)
                    continue
            
            elif cmd == "exec":
                exec_input = input(f"{CYAN}Ingrese el comando a ejecutar: {RESET}")
                result = subprocess.check_output(exec_input, shell=True, stderr=subprocess.STDOUT, universal_newlines=True)
                type_text(f"{CYAN}{result}{RESET}", delay=0.01)

            elif cmd == "info":
                type_text(f"{CYAN}SpOS v1.0 - Sistema Operativo Simulado Estilo Hacknet", delay=0.05)
                print("\n")
                type_text(f"{CYAN}Desarrollador: SP - Versión: 1.0", delay=0.05)   
                print("\n")
                type_text(f"{CYAN}Desarrollado en Python - Plataforma: {platform.system()} {platform.release()}", delay=0.05)
                print("\n")
                type_text(f"{CYAN}Usuario actual: {user}", delay=0.05)
                print("\n")
                type_text(f"{CYAN}Directorio actual: {current_dir}", delay=0.05)
                print("\n")
                uptime_sec = time.time() - start_time        
            
            elif cmd == "ETAS_ON":
                type_text(f"{RED}Usuario oculto. Trace ofuscado.{RESET}", delay=0.05)
                user = "*******"
            
            elif cmd == "ETAS_OFF":
                type_text(f"{GREEN}Usuario visible nuevamente.{RESET}", delay=0.05)
                user = f"{login}@{host}"   

            elif cmd == "ETAS":
                type_text(f"{RED}ETAS (Emergency Trace Aversion System) Activado\nEn Caso de una Vinculacion a otro dispocitivo se apagara el sistema. {RESET}", delay=0.05)
                Conection = input(f"{CYAN}¿Desea activar ETAS? (yes/no): {RESET}")
                if Conection.lower() in ["yes", "y"]:
                    type_text(f"{RED}ETAS ACTIVADO. SISTEMA EN MODO OCULTO.{RESET}", delay=0.05)
                    ConectionTrace = os.system("netstat -ano | findstr ESTABLISHED")
                    if ConectionTrace == 0:
                        type_text(f"{RED}Vinculación detectada. Apagando sistema...{RESET}", delay=0.05)
                        time.sleep(1)
                        clear_screen()
                        sys.exit(0) 
            
            else:
                type_text(f"{RED}Comando no reconocido. Usa 'help'{RESET}")
            

        except KeyboardInterrupt:
            type_text(f"\n{RED}INTERRUPT. Trace persistente.{RESET}")
        except Exception as e:
            type_text(f"{RED}KERNEL FAULT: {str(e)}{RESET}")

if __name__ == "__main__":
    clear_screen()
    sp_os_shell(user, login, shadow, SHADOW)
