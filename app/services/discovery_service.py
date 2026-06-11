import os
import time
import logging
import platform
import threading
from typing import Callable, List

from app.core.config import config

logger = logging.getLogger(__name__)


class DiscoveryService:
    """
    Watches for OS-level printer connect/disconnect events and immediately
    triggers a cloud sync — replacing slow interval polling with instant detection.

    Strategy per OS:
      - macOS/Linux: watchdog on CUPS socket directory + periodic fallback poll.
      - Windows: WMI async subscription to Win32_Printer + periodic fallback poll.
    """

    def __init__(self, on_change: Callable[[], None]):
        """
        Args:
            on_change: Callback to invoke when a printer event is detected.
                       Typically `printer_service.check_for_hardware_changes`.
        """
        self.on_change = on_change
        self._stop_event = threading.Event()
        self._threads: List[threading.Thread] = []
        self._system = platform.system().lower()

        # Debounce: avoid rapid re-syncs when multiple events fire at once
        self._last_trigger_time: float = 0.0
        self._debounce_seconds: float = 3.0
        self._trigger_lock = threading.Lock()

    # Public Interface
    def start(self) -> None:
        """Spawns OS-specific watcher threads plus the fallback poll thread."""
        logger.info(f"DiscoveryService starting on {self._system}...")
        self._stop_event.clear()

        if self._system in ("darwin", "linux"):
            self._start_unix_watcher()
        elif self._system == "windows":
            self._start_windows_watcher()

        # Always start the fallback poll thread as a safety net
        fallback_thread = threading.Thread(
            target=self._run_fallback_poll,
            name="DiscoveryFallbackThread",
            daemon=True,
        )
        fallback_thread.start()
        self._threads.append(fallback_thread)
        logger.info(
            f"DiscoveryService started on {self._system} "
            f"(fallback interval: {config.PRINTER_SYNC_INTERVAL}s)."
        )

    def stop(self) -> None:
        """Signals all watcher threads to shut down."""
        logger.info("DiscoveryService stopping...")
        self._stop_event.set()
        for t in self._threads:
            if not isinstance(t, threading.Thread) and hasattr(t, "stop"):
                try:
                    t.stop()
                except Exception:
                    pass
            # Join actual Thread instances so we wait for their shutdown.
            if isinstance(t, threading.Thread):
                t.join(timeout=5)
        self._threads.clear()
        logger.debug("DiscoveryService stopped.")

    # Trigger with Debounce
    def _trigger(self, reason: str) -> None:
        """
        Fires the on_change callback with debounce protection.
        Multiple rapid events (USB enumeration) are collapsed into one sync.
        """        
        with self._trigger_lock:
            now = time.time()
            if now - self._last_trigger_time < self._debounce_seconds:
                logger.debug(f"DiscoveryService: debounced event ({reason})")
                return
            self._last_trigger_time = now
        logger.info(f"DiscoveryService: hardware change detected ({reason}). Triggering sync...")
        try:
            self.on_change()
        except Exception as e:
            logger.error(f"DiscoveryService: on_change callback raised an error: {e}")


    # Fallback Polling Thread (all platforms)
    def _run_fallback_poll(self) -> None:
        """Periodic safety-net poll. Guarantees sync even if OS events are missed."""
        while not self._stop_event.is_set():
            self._stop_event.wait(config.PRINTER_SYNC_INTERVAL)
            if not self._stop_event.is_set():
                self._trigger("periodic fallback poll")

    # Unix (macOS + Linux): watchdog + CUPS socket watcher

    def _start_unix_watcher(self) -> None:
        """
        Uses the `watchdog` library to monitor the CUPS socket directory.
        When the directory changes (printer added/removed from CUPS queue),
        we trigger an immediate sync.
        """
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
            # Directories that change when a CUPS printer queue is added/removed
            cups_dirs = self._get_cups_watch_dirs()

            class _CUPSEventHandler(FileSystemEventHandler):
                def __init__(self_inner, trigger_fn):
                    self_inner._trigger_fn = trigger_fn

                def on_any_event(self_inner, event):
                    # Filter to relevant file types only (CUPS socket/printer files)
                    src = getattr(event, "src_path", "")
                    if self._is_relevant_cups_event(src):
                        self_inner._trigger_fn(f"CUPS fs event: {src}")

            observer = Observer()
            watched_any = False
            for cups_dir in cups_dirs:
                if os.path.isdir(cups_dir):
                    observer.schedule(
                        _CUPSEventHandler(self._trigger),
                        path=cups_dir,
                        recursive=False,
                    )
                    logger.debug(f"DiscoveryService: watching CUPS dir: {cups_dir}")
                    watched_any = True

            if watched_any:
                observer.daemon = True
                observer.start()
                self._threads.append(observer)
                logger.info("DiscoveryService: watchdog CUPS observer active.")
            else:
                logger.warning(
                    "DiscoveryService: No CUPS directories found for watchdog. "
                    "Relying on fallback poll only."
                )

        except ImportError:
            logger.warning(
                "DiscoveryService: 'watchdog' not installed. falling back to interval poll. "
                "Install it with: pip install watchdog"
            )
        except Exception as e:
            logger.error(f"DiscoveryService: Failed to start watchdog observer: {e}")

    def _get_cups_watch_dirs(self) -> list[str]:
        """Returns OS-appropriate directories to watch for CUPS changes."""
        candidates = [
            "/run/cups",          # Modern Linux (systemd tmpfiles)
            "/var/run/cups",      # Legacy Linux / macOS
            "/etc/cups/ppd",      # PPD files directory — changes on add/remove
            "/etc/cups",          # macOS CUPS config dir
        ]
        return candidates

    def _is_relevant_cups_event(self, path: str) -> bool:
        """
        Filters filesystem events to ones that indicate a printer queue change.
        Avoids reacting to log file writes or other CUPS-internal churn.
        """
        if not path:
            return False
        path_lower = path.lower()
        # React to PPD files (.ppd), CUPS printer conf files, or socket events
        relevant_extensions = (".ppd", ".conf", ".printers", "printers.conf")
        return any(path_lower.endswith(ext) for ext in relevant_extensions)

    # Windows: WMI async printer change subscription
    def _start_windows_watcher(self) -> None:
        """
        Spawns a thread that blocks on a WMI async notification for printer changes.
        This fires instantly when Windows Spooler detects a printer connect/disconnect.
        """
        watcher_thread = threading.Thread(
            target=self._run_windows_wmi_watcher,
            name="DiscoveryWMIThread",
            daemon=True,
        )
        watcher_thread.start()
        self._threads.append(watcher_thread)

    def _run_windows_wmi_watcher(self) -> None:
        """
        Blocks on a WMI notification query. Wakes up on any printer state change.
        Requires pywin32 (already a project dependency on Windows).
        """
        try:
            import win32com.client  # type: ignore
            import pythoncom  # type: ignore

            pythoncom.CoInitialize()
            wmi = win32com.client.Dispatch("WbemScripting.SWbemLocator")
            svc = wmi.ConnectServer(".", "root\\cimv2")

            # WQL query: notify on any instance change to Win32_Printer
            watcher = svc.ExecNotificationQuery(
                "SELECT * FROM __InstanceOperationEvent WITHIN 2 "
                "WHERE TargetInstance ISA 'Win32_Printer'"
            )

            logger.info("DiscoveryService: WMI printer watcher active on Windows.")

            while not self._stop_event.is_set():
                try:
                    # NextEvent with a 2000ms timeout so we can check stop_event
                    event = watcher.NextEvent(2000)
                    if event:
                        self._trigger("WMI Win32_Printer change")
                except pythoncom.com_error:
                    pass  # Expected COM timeout when no event occurs within 2000ms
                except Exception as e:
                    logger.debug(f"Transient WMI event error: {e}")

        except ImportError:
            logger.warning(
                "DiscoveryService: pywin32 not installed. "
                "WMI watcher unavailable. Relying on fallback poll."
            )
        except Exception as e:
            logger.error(f"DiscoveryService: WMI watcher failed: {e}")
        finally:
            try:
                import pythoncom  # type: ignore
                pythoncom.CoUninitialize()
            except Exception:
                pass
