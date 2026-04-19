import abc
from typing import List, Dict, Optional, Callable

class BasePrinterManager(abc.ABC):
    """Abstract base class for OS-specific printer operations."""

    @abc.abstractmethod
    def get_printers(self) -> List[Dict[str, str]]:
        """Returns a list of available printers and their statuses."""
        pass

    @abc.abstractmethod
    def get_printer_capabilities(self, printer_name: str) -> Dict[str, bool]:
        """Returns capabilities like color and duplex support."""
        pass

    @abc.abstractmethod
    def print_file_async(
        self,
        printer_name: str,
        file_path: str,
        title: str = "Inkify_Job",
        copies: int = 1,
        is_color: bool = False,
        on_success: Optional[Callable[[], None]] = None,
        on_failure: Optional[Callable[[str], None]] = None,
    ) -> Optional[str]:
        """Dispatches a print job and monitors its completion."""
        pass

    @abc.abstractmethod
    def clear_queue(self, printer_name: str) -> bool:
        """Clears all pending jobs for a specific printer."""
        pass