"""
Public documents are discovered with ``filetype:`` dorks and fetched/parsed by collectors/documents.py using
extractors/document_extractor.py (pypdf / python-docx / openpyxl).  No dedicated document search provider is
required; any SearchProvider with ``supports_filetype_operator`` participates.
"""
