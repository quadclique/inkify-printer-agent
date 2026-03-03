class AgentException(Exception):
    """Base exception"""
    pass


class ConfigException(AgentException):
    pass


class NetworkException(AgentException):
    pass


class PrinterException(AgentException):
    pass


class JobException(AgentException):
    pass


class StorageException(AgentException):
    pass


class UpdateException(AgentException):
    pass