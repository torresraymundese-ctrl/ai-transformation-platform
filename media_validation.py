"""Bounded, signature-based validation for private media uploads."""

from dataclasses import dataclass
import hashlib
import io
import posixpath
from pathlib import Path, PurePosixPath
import re
import unicodedata
from urllib.parse import unquote, urlsplit
import warnings
import zipfile
from xml.parsers import expat

from PIL import Image, ImageOps
from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject

from validation import ValidationError


JPEG_MIME = "image/jpeg"
PNG_MIME = "image/png"
WEBP_MIME = "image/webp"
PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

IMAGE_MIMES = frozenset({JPEG_MIME, PNG_MIME, WEBP_MIME})
ATTACHMENT_MIMES = frozenset({PDF_MIME, DOCX_MIME, XLSX_MIME})
ALLOWED_MIMES = IMAGE_MIMES | ATTACHMENT_MIMES

TYPE_BY_EXTENSION = {
    ".jpg": (JPEG_MIME, ".jpg"),
    ".jpeg": (JPEG_MIME, ".jpg"),
    ".png": (PNG_MIME, ".png"),
    ".webp": (WEBP_MIME, ".webp"),
    ".pdf": (PDF_MIME, ".pdf"),
    ".docx": (DOCX_MIME, ".docx"),
    ".xlsx": (XLSX_MIME, ".xlsx"),
}

IMAGE_FORMATS = {
    "JPEG": (JPEG_MIME, ".jpg"),
    "PNG": (PNG_MIME, ".png"),
    "WEBP": (WEBP_MIME, ".webp"),
}

OOXML_CORE_PROPERTIES_ROOT = (
    "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}"
    "coreProperties"
)
OOXML_CORE_PERSONAL_FIELDS = frozenset(
    {
        "{http://purl.org/dc/elements/1.1/}creator",
        "{http://schemas.openxmlformats.org/package/2006/metadata/"
        "core-properties}lastModifiedBy",
    }
)
OOXML_EXTENDED_PROPERTIES_ROOT = (
    "{http://schemas.openxmlformats.org/officeDocument/2006/"
    "extended-properties}Properties"
)
OOXML_COMPANY_FIELD = frozenset(
    {
        "{http://schemas.openxmlformats.org/officeDocument/2006/"
        "extended-properties}Company"
    }
)


class MediaValidationError(ValidationError):
    """Raised when an upload violates the fixed media policy."""


@dataclass(frozen=True)
class ValidatedMedia:
    detected_mime: str
    extension: str
    byte_size: int
    sha256: str


@dataclass
class _OoxmlXmlBudget:
    remaining_nodes: int
    maximum_depth: int
    remaining_characters: int

    def consume_node(self, depth):
        self.remaining_nodes -= 1
        if self.remaining_nodes < 0:
            raise MediaValidationError("OOXML XML node count exceeds the limit")
        if depth > self.maximum_depth:
            raise MediaValidationError("OOXML XML depth exceeds the limit")

    def consume_characters(self, *values):
        self.remaining_characters -= sum(len(value) for value in values if value)
        if self.remaining_characters < 0:
            raise MediaValidationError("OOXML XML character work exceeds the limit")


@dataclass
class _OoxmlXmlFrame:
    tag: str
    attributes: dict
    has_non_whitespace_text: bool = False


def _validated_ooxml_limit(config, key, maximum):
    value = config.get(key)
    if type(value) is not int or value < 1 or value > maximum:
        raise MediaValidationError(f"{key} is invalid")
    return value


def upload_contract(filename, declared_mime):
    """Validate the untrusted name/MIME pair before any bytes are persisted."""
    if not isinstance(filename, str):
        raise MediaValidationError("media filename is required")
    normalized = unicodedata.normalize("NFC", filename)
    if (
        not normalized
        or len(normalized) > 255
        or normalized in {".", ".."}
        or any(ord(character) < 32 for character in normalized)
        or "/" in normalized
        or "\\" in normalized
        or re.match(r"^[A-Za-z]:", normalized)
    ):
        raise MediaValidationError("media filename is unsafe")
    extension = Path(normalized).suffix.casefold()
    contract = TYPE_BY_EXTENSION.get(extension)
    if contract is None or declared_mime != contract[0]:
        raise MediaValidationError("media type is not allowed")
    return normalized, contract


def validate_media_file(path, *, filename, declared_mime, config, confirmed=False):
    """Validate and, for images, rewrite a temporary upload in place."""
    _display_name, expected = upload_contract(filename, declared_mime)
    expected_mime, expected_extension = expected
    if expected_mime in ATTACHMENT_MIMES and confirmed is not True:
        raise MediaValidationError("document privacy review is required")

    path = Path(path)
    if expected_mime in IMAGE_MIMES:
        detected_mime, extension = _validate_and_rewrite_image(path, config)
    elif expected_mime == PDF_MIME:
        _validate_pdf(path, config)
        detected_mime, extension = PDF_MIME, ".pdf"
    else:
        detected_mime, extension = _validate_ooxml(path, config)

    if detected_mime != expected_mime or extension != expected_extension:
        raise MediaValidationError("media signature does not match its type")

    byte_size, digest = _fingerprint(path)
    maximum = (
        int(config["MEDIA_IMAGE_MAX_BYTES"])
        if detected_mime in IMAGE_MIMES
        else int(config["MEDIA_ATTACHMENT_MAX_BYTES"])
    )
    if byte_size < 1 or byte_size > maximum:
        raise MediaValidationError("media exceeds its size limit")
    return ValidatedMedia(detected_mime, extension, byte_size, digest)


def _fingerprint(path):
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _validate_and_rewrite_image(path, config):
    maximum_pixels = int(config["MEDIA_IMAGE_MAX_PIXELS"])
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as source:
                detected = IMAGE_FORMATS.get(source.format)
                if detected is None:
                    raise MediaValidationError("image format is not allowed")
                width, height = source.size
                if width < 1 or height < 1 or width * height > maximum_pixels:
                    raise MediaValidationError("image dimensions exceed the limit")
                source.load()
                clean = ImageOps.exif_transpose(source)
                has_alpha = clean.mode in {"RGBA", "LA"} or (
                    clean.mode == "P" and "transparency" in clean.info
                )
                if detected[0] == JPEG_MIME:
                    clean = clean.convert("RGB")
                else:
                    clean = clean.convert("RGBA" if has_alpha else "RGB")
                output = io.BytesIO()
                if detected[0] == JPEG_MIME:
                    clean.save(output, format="JPEG", quality=90, optimize=True)
                elif detected[0] == PNG_MIME:
                    clean.save(output, format="PNG", optimize=True)
                else:
                    clean.save(output, format="WEBP", lossless=True, method=6)
    except MediaValidationError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        ValueError,
    ):
        raise MediaValidationError("image cannot be safely decoded") from None

    rewritten = output.getvalue()
    if not rewritten or len(rewritten) > int(config["MEDIA_IMAGE_MAX_BYTES"]):
        raise MediaValidationError("media exceeds its size limit")
    path.write_bytes(rewritten)
    try:
        with Image.open(path) as verified:
            final = IMAGE_FORMATS.get(verified.format)
            if final != detected:
                raise MediaValidationError("image rewrite changed its type")
            if verified.width * verified.height > maximum_pixels:
                raise MediaValidationError("image dimensions exceed the limit")
            verified.load()
    except MediaValidationError:
        raise
    except (Image.DecompressionBombError, OSError, ValueError):
        raise MediaValidationError("image rewrite cannot be verified") from None
    return detected


def _validate_pdf(path, config):
    try:
        with Path(path).open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                raise MediaValidationError("PDF signature is invalid")
        reader = PdfReader(str(path), strict=True)
        if reader.is_encrypted:
            raise MediaValidationError("encrypted PDFs are not allowed")
        if len(reader.pages) > int(config["MEDIA_PDF_MAX_PAGES"]):
            raise MediaValidationError("PDF page count exceeds the limit")
        metadata = reader.metadata
        if metadata and any(
            str(value).strip()
            for value in metadata.values()
            if value is not None
        ):
            raise MediaValidationError("PDF metadata is not allowed")
        root = reader.trailer["/Root"]
        if "/Metadata" in root:
            raise MediaValidationError("PDF metadata is not allowed")
        _reject_active_pdf_objects(root)
        for page in reader.pages:
            _reject_active_pdf_objects(page)
    except MediaValidationError:
        raise
    except Exception:
        raise MediaValidationError("PDF cannot be safely parsed") from None


def _reject_active_pdf_objects(value):
    forbidden_keys = {
        "/OpenAction",
        "/AA",
        "/A",
        "/JS",
        "/JavaScript",
        "/EmbeddedFiles",
        "/EF",
        "/Metadata",
        "/AcroForm",
        "/XFA",
        "/RichMediaContent",
        "/RichMediaSettings",
        "/3D",
        "/Movie",
    }
    forbidden_types = {
        "/EmbeddedFile",
        "/Filespec",
        "/FileAttachment",
        "/RichMedia",
        "/Movie",
        "/Sound",
        "/Screen",
        "/3D",
    }
    forbidden_actions = {
        "/JavaScript",
        "/Launch",
        "/GoToR",
        "/SubmitForm",
        "/ImportData",
        "/URI",
    }
    visited = set()

    def visit(item):
        if isinstance(item, IndirectObject):
            identity = (item.idnum, item.generation)
            if identity in visited:
                return
            visited.add(identity)
            item = item.get_object()
        if isinstance(item, DictionaryObject):
            for key, child in item.items():
                key_text = str(key)
                if key_text in forbidden_keys:
                    raise MediaValidationError("active PDF content is not allowed")
                if key_text in {"/Type", "/Subtype"} and str(child) in forbidden_types:
                    raise MediaValidationError("embedded PDF content is not allowed")
                if key_text == "/S" and str(child) in forbidden_actions:
                    raise MediaValidationError("active PDF content is not allowed")
                visit(child)
        elif isinstance(item, ArrayObject):
            for child in item:
                visit(child)

    visit(value)


def _validate_ooxml(path, config):
    try:
        with Path(path).open("rb") as handle:
            if handle.read(4) != b"PK\x03\x04":
                raise MediaValidationError("OOXML signature is invalid")
        with zipfile.ZipFile(path) as package:
            members = package.infolist()
            if not members or len(members) > int(config["MEDIA_OOXML_MAX_MEMBERS"]):
                raise MediaValidationError("OOXML member count exceeds the limit")
            total_size = sum(member.file_size for member in members)
            total_compressed = sum(member.compress_size for member in members)
            if total_size > int(config["MEDIA_OOXML_MAX_UNCOMPRESSED_BYTES"]):
                raise MediaValidationError("OOXML expanded size exceeds the limit")
            maximum_ratio = float(config["MEDIA_OOXML_MAX_COMPRESSION_RATIO"])
            if total_size and total_size / max(total_compressed, 1) > maximum_ratio:
                raise MediaValidationError("OOXML compression ratio exceeds the limit")

            names = {}
            for member in members:
                canonical = _safe_zip_member_name(member.filename)
                key = canonical.casefold()
                if key in names:
                    raise MediaValidationError("OOXML contains duplicate members")
                names[key] = member
                if member.flag_bits & 0x1:
                    raise MediaValidationError("encrypted OOXML members are not allowed")
                if (
                    member.file_size
                    and member.file_size / max(member.compress_size, 1)
                    > maximum_ratio
                ):
                    raise MediaValidationError("OOXML compression ratio exceeds the limit")
                if _is_active_ooxml_member(key):
                    raise MediaValidationError("active OOXML content is not allowed")

            content_types_member = names.get("[content_types].xml")
            if content_types_member is None:
                raise MediaValidationError("OOXML content types are missing")
            xml_budget = _OoxmlXmlBudget(
                _validated_ooxml_limit(
                    config, "MEDIA_OOXML_XML_MAX_NODES", 1_000_000
                ),
                _validated_ooxml_limit(
                    config, "MEDIA_OOXML_XML_MAX_DEPTH", 256
                ),
                _validated_ooxml_limit(
                    config, "MEDIA_OOXML_XML_MAX_CHARACTERS", 16_000_000
                ),
            )
            overrides, defaults = _parse_ooxml_content_types(
                package, content_types_member, xml_budget
            )
            has_docx = "word/document.xml" in names
            has_xlsx = "xl/workbook.xml" in names
            if has_docx == has_xlsx:
                raise MediaValidationError("OOXML package type is ambiguous")
            expected_main_type = (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document.main+xml"
                if has_docx
                else "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet.main+xml"
            )
            main_part = "word/document.xml" if has_docx else "xl/workbook.xml"
            if overrides.get(main_part) != expected_main_type:
                raise MediaValidationError("OOXML main content type is invalid")
            expected_main_root = (
                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document"
                if has_docx
                else "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}workbook"
            )
            _parse_ooxml_xml(
                package,
                names[main_part],
                xml_budget,
                expected_root=expected_main_root,
            )

            if "docprops/custom.xml" in names:
                raise MediaValidationError("custom OOXML metadata is not allowed")
            metadata_scans = set()
            _reject_ooxml_semantic_content_types(
                package,
                names,
                overrides,
                defaults,
                xml_budget,
                metadata_scans,
            )
            _reject_ooxml_personal_metadata(
                package, names, xml_budget, metadata_scans
            )
            _reject_ooxml_relationships(
                package, names, xml_budget, metadata_scans
            )
            return (DOCX_MIME, ".docx") if has_docx else (XLSX_MIME, ".xlsx")
    except MediaValidationError:
        raise
    except (OSError, ValueError, zipfile.BadZipFile, expat.ExpatError):
        raise MediaValidationError("OOXML cannot be safely parsed") from None


def _safe_zip_member_name(name):
    if not isinstance(name, str):
        raise MediaValidationError("OOXML member name is invalid")
    normalized = unicodedata.normalize("NFC", name.replace("\\", "/"))
    path = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or re.match(r"^[A-Za-z]:", normalized)
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise MediaValidationError("OOXML member path is unsafe")
    return path.as_posix()


def _is_active_ooxml_member(name):
    return (
        "vbaproject" in name
        or name.endswith("vbadata.xml")
        or "/embeddings/" in f"/{name}"
        or "/activex/" in f"/{name}"
        or "oleobject" in name
        or name.endswith(".xla")
        or name.endswith(".xlam")
    )


def _local_name(tag):
    return str(tag).rsplit("}", 1)[-1]


def _canonical_ooxml_part_name(name):
    value = str(name).strip()
    if not value.startswith("/"):
        raise MediaValidationError("OOXML part name is invalid")
    return _safe_zip_member_name(unquote(value[1:])).casefold()


def _expanded_ooxml_name(name):
    value = str(name)
    if "}" in value:
        return "{" + value
    return value


def _parse_ooxml_xml(
    package, member, budget, *, expected_root=None, on_end=None
):
    root_tag = None
    stack = []

    def reject_dtd_or_entity(*_args):
        raise MediaValidationError("OOXML DTD and entities are not allowed")

    def inspect_namespace(prefix, uri):
        budget.consume_characters(prefix or "", uri or "")

    def inspect_start(name, attributes):
        nonlocal root_tag
        tag = _expanded_ooxml_name(name)
        exact_attributes = {
            _expanded_ooxml_name(key): str(value)
            for key, value in attributes.items()
        }
        budget.consume_characters(name)
        for key, value in attributes.items():
            budget.consume_characters(key, value)
        stack.append(_OoxmlXmlFrame(tag, exact_attributes))
        budget.consume_node(len(stack))
        if root_tag is None:
            root_tag = tag
            if expected_root is not None and root_tag != expected_root:
                raise MediaValidationError("OOXML XML root is invalid")

    def inspect_text(value):
        budget.consume_characters(value)
        if stack and value.strip():
            stack[-1].has_non_whitespace_text = True

    def inspect_end(_name):
        frame = stack.pop()
        if on_end is not None:
            on_end(frame)
        if stack and frame.has_non_whitespace_text:
            stack[-1].has_non_whitespace_text = True

    def inspect_xml_declaration(version, encoding, standalone):
        budget.consume_characters(
            version or "", encoding or "", "" if standalone == -1 else str(standalone)
        )

    def inspect_processing_instruction(target, data):
        budget.consume_characters(target or "", data or "")

    parser = expat.ParserCreate(namespace_separator="}")
    parser.buffer_text = True
    parser.StartNamespaceDeclHandler = inspect_namespace
    parser.StartElementHandler = inspect_start
    parser.CharacterDataHandler = inspect_text
    parser.EndElementHandler = inspect_end
    parser.XmlDeclHandler = inspect_xml_declaration
    parser.ProcessingInstructionHandler = inspect_processing_instruction
    parser.CommentHandler = budget.consume_characters
    parser.StartDoctypeDeclHandler = reject_dtd_or_entity
    parser.EntityDeclHandler = reject_dtd_or_entity
    parser.UnparsedEntityDeclHandler = reject_dtd_or_entity
    parser.ExternalEntityRefHandler = reject_dtd_or_entity
    parser.NotationDeclHandler = reject_dtd_or_entity
    parser.SkippedEntityHandler = reject_dtd_or_entity
    with package.open(member) as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            parser.Parse(chunk, False)
        parser.Parse(b"", True)
    if root_tag is None:
        raise MediaValidationError("OOXML XML document is empty")


def _parse_ooxml_content_types(package, member, budget):
    overrides = {}
    defaults = {}

    def inspect(element):
        local_name = _local_name(element.tag)
        if local_name == "Override":
            part_name = _canonical_ooxml_part_name(
                element.attributes.get("PartName", "")
            )
            if part_name in overrides:
                raise MediaValidationError("OOXML content type declaration is ambiguous")
            content_type = str(element.attributes.get("ContentType", "")).strip()
            if not content_type:
                raise MediaValidationError("OOXML content type is invalid")
            overrides[part_name] = content_type
        elif local_name == "Default":
            extension = (
                str(element.attributes.get("Extension", "")).lstrip(".").casefold()
            )
            if not extension or extension in defaults:
                raise MediaValidationError("OOXML content type declaration is ambiguous")
            content_type = str(element.attributes.get("ContentType", "")).strip()
            if not content_type:
                raise MediaValidationError("OOXML content type is invalid")
            defaults[extension] = content_type
        else:
            return
        lowered = content_type.casefold()
        if "macroenabled" in lowered or "vbaproject" in lowered:
            raise MediaValidationError("macro-enabled OOXML is not allowed")

    _parse_ooxml_xml(
        package,
        member,
        budget,
        expected_root=(
            "{http://schemas.openxmlformats.org/package/2006/content-types}Types"
        ),
        on_end=inspect,
    )
    return overrides, defaults


def _reject_ooxml_semantic_content_types(
    package, names, overrides, defaults, budget, metadata_scans
):
    for name, member in names.items():
        content_type = overrides.get(name)
        if content_type is None:
            extension = PurePosixPath(name).suffix.lstrip(".").casefold()
            content_type = defaults.get(extension, "")
        semantic_type = str(content_type).casefold()
        if (
            "oleobject" in semantic_type
            or "activex" in semantic_type
            or "embedded-package" in semantic_type
            or "officedocument.package" in semantic_type
        ):
            raise MediaValidationError("active OOXML content is not allowed")
        if "custom-properties" in semantic_type:
            raise MediaValidationError("custom OOXML metadata is not allowed")
        if "core-properties" in semantic_type:
            _reject_ooxml_metadata_part(
                package,
                member,
                OOXML_CORE_PERSONAL_FIELDS,
                budget,
                metadata_scans,
                expected_root=OOXML_CORE_PROPERTIES_ROOT,
            )
        if "extended-properties" in semantic_type:
            _reject_ooxml_metadata_part(
                package,
                member,
                OOXML_COMPANY_FIELD,
                budget,
                metadata_scans,
                expected_root=OOXML_EXTENDED_PROPERTIES_ROOT,
            )


def _reject_ooxml_metadata_part(
    package,
    member,
    fields,
    budget,
    metadata_scans,
    *,
    expected_root,
):
    scan_key = (member.filename.casefold(), expected_root, frozenset(fields))
    if scan_key in metadata_scans:
        return
    has_personal_metadata = False

    def inspect(element):
        nonlocal has_personal_metadata
        if element.tag in fields and element.has_non_whitespace_text:
            has_personal_metadata = True

    _parse_ooxml_xml(
        package,
        member,
        budget,
        expected_root=expected_root,
        on_end=inspect,
    )
    metadata_scans.add(scan_key)
    if has_personal_metadata:
        raise MediaValidationError("personal OOXML metadata is not allowed")


def _reject_ooxml_personal_metadata(package, names, budget, metadata_scans):
    for member_name, fields, expected_root in (
        (
            "docprops/core.xml",
            OOXML_CORE_PERSONAL_FIELDS,
            OOXML_CORE_PROPERTIES_ROOT,
        ),
        (
            "docprops/app.xml",
            OOXML_COMPANY_FIELD,
            OOXML_EXTENDED_PROPERTIES_ROOT,
        ),
    ):
        member = names.get(member_name)
        if member is None:
            continue
        _reject_ooxml_metadata_part(
            package,
            member,
            fields,
            budget,
            metadata_scans,
            expected_root=expected_root,
        )


def _relationship_source_directory(relationship_name):
    if relationship_name == "_rels/.rels":
        return ""
    marker = "/_rels/"
    if marker not in relationship_name:
        raise MediaValidationError("OOXML relationship path is invalid")
    prefix, relationship_leaf = relationship_name.rsplit(marker, 1)
    if not relationship_leaf.endswith(".rels"):
        raise MediaValidationError("OOXML relationship path is invalid")
    source_leaf = relationship_leaf[: -len(".rels")]
    return posixpath.dirname(f"{prefix}/{source_leaf}")


def _resolve_ooxml_relationship_target(relationship_name, target):
    parsed = urlsplit(str(target).strip())
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise MediaValidationError("OOXML relationship target is invalid")
    decoded = unquote(parsed.path).replace("\\", "/")
    if not decoded:
        raise MediaValidationError("OOXML relationship target is invalid")
    if decoded.startswith("/"):
        combined = decoded.lstrip("/")
    else:
        combined = posixpath.join(
            _relationship_source_directory(relationship_name), decoded
        )
    normalized = posixpath.normpath(combined)
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        raise MediaValidationError("OOXML relationship target is unsafe")
    return _safe_zip_member_name(normalized).casefold()


def _reject_ooxml_relationships(package, names, budget, metadata_scans):
    relationships_root = (
        "{http://schemas.openxmlformats.org/package/2006/relationships}"
        "Relationships"
    )
    relationship_element = (
        "{http://schemas.openxmlformats.org/package/2006/relationships}"
        "Relationship"
    )
    allowed_attributes = {"Id", "Type", "Target", "TargetMode"}
    required_attributes = {"Id", "Type", "Target"}
    forbidden_types = {
        "oleobject",
        "package",
        "control",
        "activexcontrol",
        "activexcontrolbinary",
        "custom-properties",
    }
    for name, member in names.items():
        if not name.endswith(".rels"):
            continue
        relationship_ids = set()
        metadata_targets = []

        def inspect(relationship):
            if relationship.tag == relationships_root:
                return
            if relationship.tag != relationship_element:
                raise MediaValidationError("OOXML relationship element is invalid")
            if set(relationship.attributes) - allowed_attributes:
                raise MediaValidationError("OOXML relationship attributes are invalid")
            attributes = {
                key: str(value).strip()
                for key, value in relationship.attributes.items()
            }
            if any(not attributes.get(key) for key in required_attributes):
                raise MediaValidationError("OOXML relationship attributes are invalid")
            target_mode = attributes.get("TargetMode", "Internal")
            if target_mode not in {"Internal", "External"}:
                raise MediaValidationError("OOXML relationship target mode is invalid")
            relationship_id = attributes["Id"]
            if not relationship_id or relationship_id in relationship_ids:
                raise MediaValidationError("OOXML relationship ID is ambiguous")
            relationship_ids.add(relationship_id)
            if target_mode == "External":
                raise MediaValidationError("external OOXML relationships are not allowed")
            relationship_type = attributes["Type"].rstrip("/")
            semantic_type = relationship_type.rsplit("/", 1)[-1].casefold()
            if semantic_type in forbidden_types:
                raise MediaValidationError("active OOXML content is not allowed")
            if semantic_type == "core-properties":
                metadata_targets.append(
                    (
                        attributes["Target"],
                        OOXML_CORE_PERSONAL_FIELDS,
                        OOXML_CORE_PROPERTIES_ROOT,
                    )
                )
            if semantic_type == "extended-properties":
                metadata_targets.append(
                    (
                        attributes["Target"],
                        OOXML_COMPANY_FIELD,
                        OOXML_EXTENDED_PROPERTIES_ROOT,
                    )
                )

        _parse_ooxml_xml(
            package,
            member,
            budget,
            expected_root=(
                relationships_root
            ),
            on_end=inspect,
        )
        for target, fields, expected_root in metadata_targets:
            target_name = _resolve_ooxml_relationship_target(name, target)
            target_member = names.get(target_name)
            if target_member is None:
                raise MediaValidationError("OOXML relationship target is missing")
            _reject_ooxml_metadata_part(
                package,
                target_member,
                fields,
                budget,
                metadata_scans,
                expected_root=expected_root,
            )
