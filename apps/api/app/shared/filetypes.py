"""Content type from magic bytes - `AC-DATA-04.4`.

`17-data-model.md` §4: "Content type is determined by magic bytes, not by the
client's claim."

`AC-DATA-04.4`: "A file whose extension says `.pdf` but whose magic bytes say
otherwise is rejected with `unsupported_file_type`."

**Why the client's claim is worthless here.** Three of its forms and what each
one costs:

* An honest mistake - somebody renames `cv.docx` to `cv.pdf` because a form
  demanded a PDF. The extractor is handed a zip and fails in whatever way its
  parser fails, which is a 500 and a résumé that never processes.
* A deliberate one - an upload with `Content-Type: application/pdf` and an
  executable, a polyglot, or an XML bomb inside. We do not execute it, but we do
  hand it to a parser, and a parser handed an adversarial file of the wrong
  format is the most reliable remote-crash surface in the product.
* A file that is *nothing* - an empty upload, or a truncated one. Recognising it
  as unsupported at the boundary means the user is told to try again; taking it
  means a résumé stuck in `extracting_text` with an error nobody can act on.

**Sniffing is not detection.** These signatures identify the formats R1 accepts
and reject everything else. A file whose first bytes are unrecognised is
refused, not guessed at - which is the opposite of what a content-type library
does, and the right way round for a gate. The list is deliberately short: every
entry is a format the pipeline can actually read.

**A DOCX is a ZIP**, so its signature is `PK\\x03\\x04` and so is a plain zip's,
a JAR's and an XLSX's. The magic bytes cannot tell them apart; only the archive
contents can, and reading them means expanding untrusted input. So a DOCX is
accepted on the ZIP signature *and* on the extension, and that pair is the honest
statement of what is known: this is a zip, and the client says it is a document.
`RES-01` then either parses it as a DOCX or fails, and a failure to parse is a
clear message rather than a crash.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

#: How many bytes the sniffer needs. Every signature below fits, and reading a
#: fixed prefix is what keeps this callable on a stream: §4 requires uploads to
#: be streamed, so nothing may need the whole file to decide.
SNIFF_BYTES = 512


class FileKind(StrEnum):
    """The formats R1 accepts. `ocr` inputs (images) arrive with `RES-02b`."""

    PDF = "pdf"
    DOCX = "docx"
    TEXT = "txt"


@dataclass(frozen=True, slots=True)
class Signature:
    kind: FileKind
    magic: bytes
    #: The extensions this signature may legitimately carry. A ZIP signature
    #: with a `.pdf` extension is the mismatch `AC-DATA-04.4` names.
    extensions: frozenset[str]
    mime: str


SIGNATURES: tuple[Signature, ...] = (
    Signature(FileKind.PDF, b"%PDF-", frozenset({"pdf"}), "application/pdf"),
    Signature(
        FileKind.DOCX,
        b"PK\x03\x04",
        frozenset({"docx"}),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
)

#: The MIME type a `.txt` gets. Plain text has no magic bytes - that is what
#: plain text means - so it is recognised by *absence* of any other signature
#: plus decodability, and only when the extension says so.
TEXT_MIME = "text/plain; charset=utf-8"


class UnsupportedFileType(ValueError):
    """`AC-DATA-04.4`'s rejection.

    Its own type so the router maps it to the `unsupported_file_type` error code
    rather than to a generic 400 - the user needs to be told the file is the
    wrong sort, which is actionable, rather than that their request was invalid,
    which is not.
    """


@dataclass(frozen=True, slots=True)
class Sniffed:
    kind: FileKind
    mime: str


def sniff(head: bytes, extension: str) -> Sniffed:
    """What `head` actually is, given a claimed `extension`. Raises otherwise.

    Both are needed and neither is trusted alone. The bytes decide the format;
    the extension has to agree. That asymmetry is the point: a PDF uploaded as
    `.docx` is refused as loudly as a zip uploaded as `.pdf`, because in both
    cases something downstream will be handed a file of a shape it did not
    expect.
    """
    claimed = extension.lower().lstrip(".")

    if not head:
        raise UnsupportedFileType(
            "the upload is empty. An empty file recognised at the boundary is a "
            "message the user can act on; accepted, it is a résumé stuck in "
            "`extracting_text` forever."
        )

    for signature in SIGNATURES:
        if head.startswith(signature.magic):
            if claimed not in signature.extensions:
                raise UnsupportedFileType(
                    f"the file's magic bytes say {signature.kind.value} but the "
                    f"extension says {claimed!r}. §4 determines content type by "
                    "magic bytes, not by the client's claim - a parser handed a "
                    "file of the wrong shape is the most reliable remote-crash "
                    "surface there is."
                )
            return Sniffed(kind=signature.kind, mime=signature.mime)

    if claimed == "txt" and _is_text(head):
        return Sniffed(kind=FileKind.TEXT, mime=TEXT_MIME)

    raise UnsupportedFileType(
        f"the file's first bytes match no format R1 accepts "
        f"({sorted(kind.value for kind in FileKind)}). Unrecognised input is "
        "refused rather than guessed at: guessing is what a content-type "
        "library does, and this is a gate."
    )


def _is_text(head: bytes) -> bool:
    """Whether `head` looks like text.

    A NUL byte is the giveaway - no text encoding this product accepts contains
    one, and every binary format does within the first few hundred bytes. Then
    UTF-8 decodability, tolerating a truncation mid-character because `head` is
    a prefix of a stream and cutting a multi-byte character in half is expected
    rather than suspicious.
    """
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as failure:
        # A failure at the very end is a character split by the 512-byte
        # boundary, not a binary file. Anywhere else, it is binary.
        return failure.start >= len(head) - 4
    return True


def extension_for(kind: FileKind) -> str:
    """The extension a key gets for a sniffed kind.

    From the sniff rather than from the upload, which is what closes the loop:
    `object_keys` refuses anything but a fixed set, and this is the only thing
    that supplies one.
    """
    return kind.value


__all__ = [
    "SIGNATURES",
    "SNIFF_BYTES",
    "TEXT_MIME",
    "FileKind",
    "Signature",
    "Sniffed",
    "UnsupportedFileType",
    "extension_for",
    "sniff",
]
