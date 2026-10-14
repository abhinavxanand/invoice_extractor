class InvoiceExtractorError(Exception):
    pass


class UnsupportedOrEmptyFile(InvoiceExtractorError):
    pass


class EncryptedDocument(InvoiceExtractorError):
    pass


class CorruptDocument(InvoiceExtractorError):
    pass


class DocumentTooLarge(InvoiceExtractorError):
    pass


class ExtractionFailed(InvoiceExtractorError):
    pass
