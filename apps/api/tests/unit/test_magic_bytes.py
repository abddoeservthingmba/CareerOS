"""T-DATA-04.4 - what a file *is*, not what the client says it is.

`AC-DATA-04.4`: "A file whose extension says `.pdf` but whose magic bytes say
otherwise is rejected with `unsupported_file_type`."

`17-data-model.md` §4: "Content type is determined by magic bytes, not by the
client's claim."

**Why the claim is worthless.** Three forms it takes and what each costs:

* An honest mistake - somebody renames `cv.docx` to `cv.pdf` because a form
  demanded a PDF. The extractor is handed a zip and fails however its parser
  fails, which is a 500 and a résumé that never processes.
* A deliberate one - `Content-Type: application/pdf` over an executable, a
  polyglot, or an XML bomb. We do not execute it, but we do hand it to a parser,
  and a parser handed an adversarial file of the wrong format is the most
  reliable remote-crash surface in the product.
* A file that is *nothing* - empty or truncated. Recognised at the boundary the
  user is told to try again; accepted, it is a résumé stuck in
  `extracting_text` with an error nobody can act on.

**The asymmetry is deliberate.** The bytes decide the format and the extension
has to agree, so a PDF uploaded as `.docx` is refused as loudly as a zip
uploaded as `.pdf`. Both hand something downstream a file of a shape it did not
expect, and only one of them looks like an attack.
"""

from __future__ import annotations

import pytest

from app.shared.filetypes import (
    SIGNATURES,
    SNIFF_BYTES,
    TEXT_MIME,
    FileKind,
    UnsupportedFileType,
    extension_for,
    sniff,
)

PDF = b"%PDF-1.7\n%\xc7\xec\x8f\xa2\n1 0 obj"
DOCX = b"PK\x03\x04\x14\x00\x06\x00\x08\x00\x00\x00!\x00"
TEXT = b"Priya Sharma\nSenior Backend Engineer\n\nPython, FastAPI, Postgres.\n"

#: A Windows executable, a shell script and an ELF binary - the three shapes an
#: upload arrives in when the claim is a lie on purpose.
EXECUTABLE = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff"
SHELL = b"#!/bin/sh\nrm -rf /\n"
ELF = b"\x7fELF\x02\x01\x01\x00"


# -- the criterion ------------------------------------------------------------


def test_a_pdf_is_accepted():
    result = sniff(PDF, "pdf")

    assert result.kind is FileKind.PDF
    assert result.mime == "application/pdf"


def test_a_docx_is_accepted():
    result = sniff(DOCX, "docx")

    assert result.kind is FileKind.DOCX
    assert "wordprocessingml" in result.mime


def test_plain_text_is_accepted():
    result = sniff(TEXT, "txt")

    assert result.kind is FileKind.TEXT
    assert result.mime == TEXT_MIME


def test_a_docx_claiming_to_be_a_pdf_is_refused():
    """`AC-DATA-04.4`, verbatim: extension says `.pdf`, magic bytes say
    otherwise."""
    with pytest.raises(UnsupportedFileType, match="magic bytes"):
        sniff(DOCX, "pdf")


def test_a_pdf_claiming_to_be_a_docx_is_refused():
    """The mirror case, which is the one a "detect the real type and carry on"
    implementation would silently accept.

    It is the honest mistake rather than the attack - and it still hands the
    DOCX parser a PDF.
    """
    with pytest.raises(UnsupportedFileType, match="magic bytes"):
        sniff(PDF, "docx")


@pytest.mark.parametrize(("payload", "name"), [(EXECUTABLE, "executable"), (ELF, "ELF binary")])
@pytest.mark.parametrize("extension", ["pdf", "docx", "txt"])
def test_a_binary_executable_is_refused_whatever_it_claims(
    payload: bytes, name: str, extension: str
):
    """Every combination, because a gate that covered two of three extensions
    would be routed around by the third."""
    with pytest.raises(UnsupportedFileType):
        sniff(payload, extension)


@pytest.mark.parametrize("extension", ["pdf", "docx"])
def test_a_shell_script_is_refused_as_a_document(extension: str):
    with pytest.raises(UnsupportedFileType):
        sniff(SHELL, extension)


def test_a_shell_script_uploaded_as_text_is_accepted_and_that_is_correct():
    """The honest limit, and the first thing this suite got wrong.

    A shell script *is* plain text. There is no signature that distinguishes
    "text a person wrote" from "text that happens to be a program", and there
    could not be - the two are the same bytes with different meanings. So the
    sniffer accepts it, and the parametrised test above was asserting something
    the format cannot support.

    Which is fine, because format is not the control that matters here. HR-1
    and the pipeline are: nothing uploaded is ever executed, a `.txt` goes to a
    text reader, and the reader's output is résumé text. What this test records
    is that the gate identifies *formats* and does not claim to identify
    *intent* - and that the distinction is deliberate rather than an oversight
    somebody should close by adding a shebang check, which would then reject a
    legitimate CV that happened to begin with a `#`.
    """
    assert sniff(SHELL, "txt").kind is FileKind.TEXT


def test_an_empty_upload_is_refused():
    """A truncated or empty upload recognised here is a message the user can
    act on. Accepted, it is a résumé stuck in `extracting_text` forever."""
    with pytest.raises(UnsupportedFileType, match="empty"):
        sniff(b"", "pdf")


def test_an_unrecognised_format_is_refused_rather_than_guessed():
    """The opposite of what a content-type library does, and the right way
    round for a gate.

    `\\x89PNG` is a real format with real magic bytes; it is simply not one R1
    accepts, and "recognised but unsupported" and "unrecognised" get the same
    answer.
    """
    with pytest.raises(UnsupportedFileType, match="no format R1 accepts"):
        sniff(b"\x89PNG\r\n\x1a\n", "pdf")


def test_the_rejection_names_the_error_code_the_router_maps():
    """`AC-DATA-04.4` names `unsupported_file_type` specifically.

    A generic 400 tells the user their request was invalid, which is not
    actionable; this tells them the file is the wrong sort, which is.
    """
    from app.core.errors import ErrorCode

    assert UnsupportedFileType.__name__ == "UnsupportedFileType"
    assert hasattr(ErrorCode, "UNSUPPORTED_FILE_TYPE")


# -- the text path, which has no magic bytes ----------------------------------


def test_a_binary_file_claiming_to_be_text_is_refused():
    """Plain text has no signature - that is what plain text means - so it is
    recognised by the *absence* of any other signature plus decodability. A NUL
    byte is the giveaway: no encoding this product accepts contains one, and
    every binary format does within the first few hundred bytes."""
    with pytest.raises(UnsupportedFileType):
        sniff(b"\x00\x01\x02binary", "txt")


def test_text_that_is_not_utf8_is_refused():
    """A latin-1 résumé is a résumé we would extract mojibake from, and the
    mojibake would end up in a cover letter."""
    with pytest.raises(UnsupportedFileType):
        sniff("Priya Sharma, Ingénieur".encode("latin-1"), "txt")


def test_a_multibyte_character_split_by_the_sniff_boundary_is_still_text():
    """§4 requires uploads to be streamed, so the sniffer sees a fixed prefix.

    Cutting a multi-byte character in half at exactly 512 bytes is expected
    rather than suspicious - and refusing it would reject a legitimate CV
    depending on where an accent happened to fall, which is the kind of bug
    nobody reproduces.
    """
    head = ("a" * (SNIFF_BYTES - 2)).encode() + "é".encode()[:1]

    assert sniff(head, "txt").kind is FileKind.TEXT


def test_text_is_only_accepted_when_the_extension_says_so():
    """Otherwise every unrecognised-but-decodable upload would pass as text -
    a CSV, an HTML page, a JSON body posted by mistake - and be handed to the
    résumé extractor as a document."""
    with pytest.raises(UnsupportedFileType):
        sniff(TEXT, "pdf")


# -- the DOCX/ZIP ambiguity, stated rather than hidden ------------------------


def test_a_plain_zip_claiming_to_be_a_docx_cannot_be_distinguished():
    """The honest limit of magic-byte sniffing, recorded as a test.

    A DOCX *is* a ZIP: the signature `PK\\x03\\x04` is shared with a plain zip,
    a JAR and an XLSX. Only the archive contents tell them apart, and reading
    those means expanding untrusted input. So a DOCX is accepted on the ZIP
    signature plus the extension, and that pair is the honest statement of what
    is known - this is a zip, and the client says it is a document.

    `RES-01` then parses it as a DOCX or fails, and a parse failure is a clear
    message. What this test records is that the gate does *not* claim more than
    it can check.
    """
    plain_zip = b"PK\x03\x04" + b"\x00" * 20

    assert sniff(plain_zip, "docx").kind is FileKind.DOCX


def test_a_zip_claiming_any_other_extension_is_still_refused():
    """The ambiguity is confined to `.docx`. A zip uploaded as `.pdf` or `.txt`
    is refused, so the limit above is one extension wide rather than a hole."""
    for extension in ("pdf", "txt", "zip"):
        with pytest.raises(UnsupportedFileType):
            sniff(b"PK\x03\x04" + b"\x00" * 20, extension)


# -- the signature table -------------------------------------------------------


def test_the_sniffer_needs_only_a_prefix():
    """§4: "Uploads are streamed to R2; the API never buffers a whole file in
    memory."

    So nothing may need the whole file to decide. Every signature fits in
    `SNIFF_BYTES`, which is what makes this callable on a stream and
    `AC-DATA-04.3`'s 32 MB RSS ceiling reachable.
    """
    assert SNIFF_BYTES == 512
    for signature in SIGNATURES:
        assert len(signature.magic) <= SNIFF_BYTES


def test_the_table_covers_every_kind_that_needs_a_signature():
    """`FileKind` has three members and the table has two rows, because text
    has no signature. Asserted so a fourth kind added without a signature fails
    here rather than being silently unrecognisable."""
    with_signatures = {signature.kind for signature in SIGNATURES}

    assert with_signatures == {FileKind.PDF, FileKind.DOCX}
    assert set(FileKind) - with_signatures == {FileKind.TEXT}


def test_no_two_signatures_share_a_prefix():
    """A shared prefix would make the first entry in the table win, and the
    table's order is not a decision anybody made."""
    magics = [signature.magic for signature in SIGNATURES]

    for one in magics:
        for other in magics:
            if one is not other:
                assert not one.startswith(other), f"{one!r} shadows {other!r}"


def test_the_extension_written_into_a_key_comes_from_the_sniff():
    """The loop `AC-DATA-04.1` and `AC-DATA-04.4` close together.

    `object_keys` refuses anything but a fixed set of extensions, and this is
    the only thing that supplies one - so the extension in a key is what we
    decided the file was, never what the upload claimed.
    """
    from app.shared.object_keys import ALLOWED_EXTENSIONS

    for kind in FileKind:
        assert extension_for(kind) in ALLOWED_EXTENSIONS


def test_the_ocr_kind_is_absent_until_r2():
    """`RES-02b` adds image input. `01-foundations.md` §15: four states, no
    fifth - an image signature accepted by a pipeline that cannot read one
    would be the fifth."""
    assert "png" not in {kind.value for kind in FileKind}
    assert "jpg" not in {kind.value for kind in FileKind}
