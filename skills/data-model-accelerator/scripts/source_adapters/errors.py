"""Typed adapter failures; CLI diagnostics never render exception messages.

ValueError inheritance and the original code as the message preserve callers
that already catch or compare these failures. Only CLI-allowlisted codes may be
disclosed; arbitrary exception text is not a diagnostic contract.
"""


class SourceAdapterError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)
