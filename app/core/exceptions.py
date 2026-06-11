class AgentException(Exception):
    """Base exception for all Inkify Agent errors."""
    pass


class ConfigException(AgentException):
    """Raised when configuration is invalid or missing."""
    pass


class NetworkException(AgentException):
    """Raised on network/API communication failures."""
    pass


class PrinterException(AgentException):
    """Raised when a printer operation fails."""
    pass


class JobException(AgentException):
    """Raised when a print job encounters an error."""
    pass


class StorageException(AgentException):
    """Raised when a file/disk operation fails."""
    pass


class UpdateException(AgentException):
    """Raised during a self-update failure."""
    pass


class PairingException(AgentException):
    """Raised when agent registration/pairing fails."""
    pass
