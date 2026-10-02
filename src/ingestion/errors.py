class IngestError(Exception):
    """A document was rejected before anything was stored.

    status_code is the HTTP status the API answers with (400, 413, 415 or 422).
    """

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code
