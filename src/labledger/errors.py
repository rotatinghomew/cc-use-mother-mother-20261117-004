class LedgerError(Exception):
    """可向项目使用者安全呈现的错误基类。"""


class ContractError(LedgerError):
    pass


class DuplicateRunError(LedgerError):
    pass


class UnknownStudyError(LedgerError):
    pass


class EvidenceUnavailableError(LedgerError):
    pass


class StorageError(LedgerError):
    pass
