import platform
import logging
from app.platform.base import BasePrinterManager

logger = logging.getLogger(__name__)

def get_printer_manager() -> BasePrinterManager:
    """Returns the correct printer manager based on the host OS."""
    system = platform.system()

    if system == "Windows":
        logger.info("Initializing Windows Print Spooler interface...")
        from app.platform.windows import WindowsPrinterManager
        return WindowsPrinterManager()
    
    elif system in ["Darwin", "Linux"]:
        logger.info(f"Initializing CUPS interface for {system}...")
        from app.platform.unix import UnixPrinterManager
        return UnixPrinterManager()
    
    else:
        logger.warning(f"Unknown OS: {system}. Defaulting to CUPS.")
        from app.platform.unix import UnixPrinterManager
        return UnixPrinterManager()