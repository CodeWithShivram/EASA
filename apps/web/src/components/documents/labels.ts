import type { Level } from "@/lib/api/documents";

export const LEVEL_LABELS: Record<Level, string> = {
  employee: "Everyone",
  manager: "Managers and administrators",
  administrator: "Administrators only",
};

/** Why processing failed (API section 3.4.4), in words. */
export const FAILURE_REASONS: Record<string, string> = {
  encrypted_file: "The file is password-protected.",
  corrupt_file: "The file could not be read.",
  too_many_pages: "The PDF has too many pages.",
  resource_limit_exceeded: "The file needed too much processing.",
  text_too_large: "The document contains too much text.",
  document_too_complex: "The document is too complex to split into parts.",
  no_extractable_text: "No text found (scanned PDFs are not supported).",
  processing_error: "Processing failed unexpectedly.",
};

/** Upload refusals (API section 3.4.1 and P6-M3), in words. */
export const UPLOAD_ERRORS: Record<string, string> = {
  invalid_filename: "The file name is not allowed.",
  file_too_large: "The file is larger than 10 MB.",
  request_too_large: "The file is larger than 10 MB.",
  unsupported_file_type: "Only PDF, DOCX and TXT files can be uploaded.",
  file_content_mismatch: "The file's content does not match its extension.",
  empty_file: "The file is empty.",
  invalid_text_encoding: "Text files must be UTF-8.",
  corrupt_file: "The file could not be read.",
  encrypted_file: "Password-protected files are not supported.",
  archive_limits_exceeded: "The DOCX file exceeds the size or compression limits.",
  macros_not_allowed: "DOCX files with macros are not allowed.",
  document_exists: "A document with the same content already exists.",
  min_role_not_allowed: "You cannot restrict a document above your own role.",
  forbidden: "Your role cannot upload documents.",
};

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function fileType(mediaType: string): string {
  if (mediaType === "application/pdf") return "PDF";
  if (mediaType.includes("wordprocessingml")) return "DOCX";
  if (mediaType === "text/plain") return "TXT";
  return mediaType;
}
