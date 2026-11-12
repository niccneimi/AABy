class AgentError(Exception):
    """Only a stable code may cross the API boundary, never provider exception text."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
