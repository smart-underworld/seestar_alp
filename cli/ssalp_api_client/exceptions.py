class SSAlpError(Exception):
    """Raised when the Alpaca API returns a non-zero ErrorNumber."""

    def __init__(self, message: str, error_number: int = -1) -> None:
        super().__init__(message)
        self.error_number = error_number


class SSAlpConnectionError(Exception):
    """Raised when a network or transport failure occurs."""
