import os
import sys
import time
import threading
import subprocess
import shutil
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from retriqs.utils import logger


_ENV_VAR_NAME = "OLLAMA_FLASH_ATTENTION"
_ENV_TARGET_VALUE = "false"
_CHECK_LOCK = threading.Lock()
_HAS_RUN = False
_CHECKED_HOSTS: set[str] = set()


def ensure_ollama_flash_attention_fix(args=None) -> None:
    global _HAS_RUN
    with _CHECK_LOCK:
        if _HAS_RUN:
            return
        _HAS_RUN = True

    _ensure_env_var()

    local_hosts = _collect_local_ollama_hosts(args)
    if not local_hosts:
        logger.debug("No localhost Ollama hosts configured; skipping fix.")
        return

    for host in sorted(local_hosts):
        _ensure_local_ollama_host(host)


def _ensure_env_var() -> None:
    current_value = os.environ.get(_ENV_VAR_NAME)
    if current_value is None or current_value.lower() != _ENV_TARGET_VALUE:
        os.environ[_ENV_VAR_NAME] = _ENV_TARGET_VALUE
        logger.info(f"Set {_ENV_VAR_NAME}={_ENV_TARGET_VALUE} for current process")


def _collect_local_ollama_hosts(args) -> set[str]:
    hosts: set[str] = set()

    if args is not None:
        if getattr(args, "llm_binding", None) == "ollama":
            hosts.add(getattr(args, "llm_binding_host", None))
        if getattr(args, "embedding_binding", None) == "ollama":
            hosts.add(getattr(args, "embedding_binding_host", None))

    try:
        from retriqs.api.database.settings_manager import get_graph_storages
        from retriqs.api.config import build_storage_args, get_config

        base_args = args if args is not None else get_config()
        storages = get_graph_storages()
        for storage in storages:
            try:
                storage_args = build_storage_args(storage, base_args)
            except Exception as e:
                logger.warning(f"Failed to build args for storage {storage.id}: {e}")
                continue
            if storage_args.llm_binding == "ollama":
                hosts.add(storage_args.llm_binding_host)
            if storage_args.embedding_binding == "ollama":
                hosts.add(storage_args.embedding_binding_host)
    except Exception as e:
        logger.debug(f"Skipping storage host discovery: {e}")

    local_hosts: set[str] = set()
    for host in hosts:
        normalized = _normalize_local_host(host)
        if normalized is not None:
            local_hosts.add(normalized)

    return local_hosts


def _normalize_local_host(host: str | None) -> str | None:
    if not host:
        return None

    raw = host.strip()
    if not raw:
        return None

    if "://" not in raw:
        raw = f"http://{raw}"

    parsed = urlparse(raw)
    hostname = parsed.hostname
    if not hostname:
        return None

    hostname_lower = hostname.lower()
    if hostname_lower in ("127.0.0.1", "::1"):
        hostname_lower = "localhost"

    if hostname_lower != "localhost":
        return None

    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80

    scheme = parsed.scheme or "http"
    return f"{scheme}://{hostname_lower}:{port}"


def _ensure_local_ollama_host(host: str) -> None:
    if host in _CHECKED_HOSTS:
        return
    _CHECKED_HOSTS.add(host)

    reachable = _probe_ollama(host)
    if not reachable:
        logger.info(f"Ollama not reachable at {host}; starting new instance")
        if not _start_ollama():
            logger.warning(
                f"Skipping Ollama wait for {host} because the executable is not available"
            )
            return
        _wait_for_ollama(host)
        return

    processes = _find_ollama_serve_processes()
    if not processes:
        logger.warning(
            "Ollama is reachable but no serve process was detected; skipping restart"
        )
        return

    env_statuses = [_process_env_status(proc) for proc in processes]
    if any(status is True for status in env_statuses):
        logger.info("Ollama is running with correct flash attention setting")
        return

    if not any(status is False for status in env_statuses):
        logger.warning(
            "Unable to verify Ollama environment; skipping restart to avoid disruption"
        )
        return

    logger.info("Restarting Ollama to apply flash attention setting")
    _stop_ollama_processes(processes)
    if not _start_ollama():
        logger.warning(
            f"Skipping Ollama wait for {host} because the executable is not available"
        )
        return
    _wait_for_ollama(host)


def _probe_ollama(host: str) -> bool:
    endpoints = ("/api/version", "/api/tags")
    for endpoint in endpoints:
        url = f"{host}{endpoint}"
        try:
            req = Request(url, headers={"User-Agent": "LightRAG"})
            with urlopen(req, timeout=2):
                return True
        except Exception:
            continue
    return False


def _find_ollama_serve_processes():
    try:
        import psutil
    except Exception as e:
        logger.debug(f"psutil unavailable, skipping process inspection: {e}")
        return []

    processes = []
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline = proc.info.get("cmdline") or []
            cmd_text = " ".join(cmdline).lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

        if "ollama" not in name and "ollama" not in cmd_text:
            continue
        if "serve" not in cmd_text:
            continue

        processes.append(proc)

    return processes


def _process_env_status(proc):
    try:
        env = proc.environ()
    except Exception:
        return None

    value = env.get(_ENV_VAR_NAME)
    if value is None:
        return False
    return value.lower() == _ENV_TARGET_VALUE


def _stop_ollama_processes(processes) -> None:
    for proc in processes:
        try:
            proc.terminate()
        except Exception as e:
            logger.warning(f"Failed to terminate Ollama process {proc.pid}: {e}")

    for proc in processes:
        try:
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception as e:
                logger.warning(f"Failed to kill Ollama process {proc.pid}: {e}")


def _start_ollama() -> bool:
    exe = shutil.which("ollama")
    if not exe:
        logger.warning("Ollama executable not found in PATH")
        return False

    env = os.environ.copy()
    env[_ENV_VAR_NAME] = _ENV_TARGET_VALUE

    if sys.platform.startswith("win"):
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        subprocess.Popen(
            [exe, "serve"],
            env=env,
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        subprocess.Popen(
            [exe, "serve"],
            env=env,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return True


def _wait_for_ollama(host: str) -> None:
    for _ in range(10):
        if _probe_ollama(host):
            logger.info(f"Ollama is ready at {host}")
            return
        time.sleep(0.5)
    logger.warning(f"Ollama did not respond at {host} after restart")
