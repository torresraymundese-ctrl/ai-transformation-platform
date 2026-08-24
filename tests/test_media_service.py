import hashlib
import io
import os
from pathlib import Path
import sqlite3
import zipfile

import pytest
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    TextStringObject,
)
from werkzeug.datastructures import FileStorage

import manage
import media_service
from media_service import (
    MediaInUseError,
    MediaValidationError,
    archive_media,
    recover_media_storage,
    store_media,
)


OOXML_MIMES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _upload(name, mime, data):
    return FileStorage(stream=io.BytesIO(data), filename=name, content_type=mime)


def _store(client, name, mime, data, *, confirmed=False):
    with client.application.app_context():
        return store_media(
            _upload(name, mime, data),
            metadata_review_confirmed=confirmed,
        )


def _image_bytes(fmt="PNG", *, size=(8, 6), exif=False):
    image = Image.new("RGB", size, (16, 80, 160))
    output = io.BytesIO()
    options = {}
    if exif:
        metadata = Image.Exif()
        metadata[315] = "private photographer"
        options["exif"] = metadata
    image.save(output, format=fmt, **options)
    return output.getvalue()


def _pdf_bytes(
    *,
    pages=1,
    metadata=None,
    action=False,
    attachment=False,
    encrypt=False,
    page_metadata=False,
    xfa=False,
    rich_media=False,
):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    writer.metadata = metadata
    if action:
        writer._root_object[NameObject("/OpenAction")] = DictionaryObject(
            {
                NameObject("/S"): NameObject("/JavaScript"),
                NameObject("/JS"): TextStringObject("app.alert('x')"),
            }
        )
    if attachment:
        writer.add_attachment("payload.txt", b"payload")
    if page_metadata:
        xmp = DecodedStreamObject()
        xmp.set_data(b'<x:xmpmeta xmlns:x="adobe:ns:meta/"/>')
        xmp[NameObject("/Type")] = NameObject("/Metadata")
        xmp[NameObject("/Subtype")] = NameObject("/XML")
        writer.pages[0][NameObject("/Metadata")] = writer._add_object(xmp)
    if xfa:
        form = DictionaryObject(
            {NameObject("/XFA"): TextStringObject("active form payload")}
        )
        writer._root_object[NameObject("/AcroForm")] = writer._add_object(form)
    if rich_media:
        annotation = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/RichMedia"),
                NameObject("/Rect"): ArrayObject(),
            }
        )
        writer.pages[0][NameObject("/Annots")] = ArrayObject(
            [writer._add_object(annotation)]
        )
    if encrypt:
        writer.encrypt("secret")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _ooxml_bytes(
    kind,
    *,
    extra=(),
    compression=zipfile.ZIP_STORED,
    main_type_override=None,
    content_type_overrides=(),
    main_xml=None,
):
    main_path = "word/document.xml" if kind == "docx" else "xl/workbook.xml"
    main_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
        if kind == "docx"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
    )
    main_type = main_type_override or main_type
    override_xml = "".join(
        f'<Override PartName="/{part}" ContentType="{content_type}"/>'
        for part, content_type in content_type_overrides
    )
    if main_xml is None:
        main_xml = (
            b'<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'
            if kind == "docx"
            else b'<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>'
        )
    base = [
        (
            "[Content_Types].xml",
            (
                '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                f'<Override PartName="/{main_path}" ContentType="{main_type}"/>'
                f"{override_xml}"
                "</Types>"
            ).encode(),
        ),
        (main_path, main_xml),
        (
            "docProps/core.xml",
            b'<?xml version="1.0"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"/>',
        ),
        (
            "docProps/app.xml",
            b'<?xml version="1.0"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Company/></Properties>',
        ),
    ]
    extra = tuple(extra)
    overridden = {name for name, _data in extra}
    entries = tuple(item for item in base if item[0] not in overridden) + extra
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as package:
        for name, data in entries:
            package.writestr(name, data)
    return output.getvalue()


def _row(db, asset_id):
    return db.execute("SELECT * FROM media_assets WHERE id=?", (asset_id,)).fetchone()


def _insert_pending(db, *, storage_name, mime, data):
    digest = hashlib.sha256(data).hexdigest()
    cursor = db.execute(
        "INSERT INTO media_assets "
        "(storage_name,display_name,detected_mime,byte_size,sha256,status,created_at,updated_at) "
        "VALUES (?,?,?,?,?,'pending','2026-08-24 10:00:00','2026-08-24 10:00:00')",
        (storage_name, "fixture.png", mime, len(data), digest),
    )
    db.commit()
    return cursor.lastrowid


def _mark_ready(db, asset_id):
    db.execute(
        "UPDATE media_assets SET status='ready',scan_result_code='validated',"
        "scan_checked_at='2026-08-24 10:00:00',ready_at='2026-08-24 10:00:00',"
        "updated_at='2026-08-24 10:00:00' WHERE id=?",
        (asset_id,),
    )
    db.commit()


def _publish_share_reference(db, asset_id):
    slug = f"duplicate-media-{asset_id}"
    group_id = db.execute(
        "INSERT INTO content_groups (entry_type,canonical_slug,created_at,updated_at) "
        "VALUES ('announcement',?,'2026-08-24 10:00:00','2026-08-24 10:00:00')",
        (slug,),
    ).lastrowid
    content_id = db.execute(
        "INSERT INTO content_items "
        "(content_group_id,entry_type,revision_number,slug,title,summary,seo_title,seo_description,"
        "share_image_media_id,status,lock_version,created_at,updated_at) "
        "VALUES (?,'announcement',1,?,'Title','Summary','SEO','Description',?,'draft',1,"
        "'2026-08-24 10:00:00','2026-08-24 10:00:00')",
        (group_id, slug, asset_id),
    ).lastrowid
    db.execute(
        "INSERT INTO announcement_content (content_item_id) VALUES (?)", (content_id,)
    )
    db.execute(
        "UPDATE content_items SET status='published',published_at='2026-08-24 10:00:00',"
        "updated_at='2026-08-24 10:00:00' WHERE id=?",
        (content_id,),
    )
    db.commit()


@pytest.mark.parametrize(
    "name,mime,data",
    [
        ("x.svg", "image/svg+xml", b"<svg><script/></svg>"),
        ("x.jpg", "image/jpeg", b"not-a-jpeg"),
        ("x.html", "text/html", b"<script>"),
        ("x.pdf", "application/pdf", _image_bytes("PNG")),
        ("x.png", "image/jpeg", _image_bytes("PNG")),
    ],
)
def test_media_rejects_extension_mime_or_signature_mismatch(
    client, media_root, name, mime, data
):
    with pytest.raises(MediaValidationError):
        _store(client, name, mime, data, confirmed=True)

    assert list(media_root.iterdir()) == []


@pytest.mark.parametrize(
    "name,mime,data,expected_mime,expected_extension",
    [
        ("photo.jpg", "image/jpeg", _image_bytes("JPEG"), "image/jpeg", ".jpg"),
        ("photo.jpeg", "image/jpeg", _image_bytes("JPEG"), "image/jpeg", ".jpg"),
        ("image.png", "image/png", _image_bytes("PNG"), "image/png", ".png"),
        ("image.webp", "image/webp", _image_bytes("WEBP"), "image/webp", ".webp"),
        ("report.pdf", "application/pdf", _pdf_bytes(), "application/pdf", ".pdf"),
        (
            "guide.docx",
            OOXML_MIMES["docx"],
            _ooxml_bytes("docx"),
            OOXML_MIMES["docx"],
            ".docx",
        ),
        (
            "sheet.xlsx",
            OOXML_MIMES["xlsx"],
            _ooxml_bytes("xlsx"),
            OOXML_MIMES["xlsx"],
            ".xlsx",
        ),
    ],
)
def test_media_accepts_only_the_six_exact_type_contracts(
    client, media_root, name, mime, data, expected_mime, expected_extension
):
    result = _store(client, name, mime, data, confirmed=True)
    stored = media_root / result.storage_name

    assert result.status == "ready"
    assert result.detected_mime == expected_mime
    assert stored.suffix == expected_extension
    assert stored.is_file()
    assert hashlib.sha256(stored.read_bytes()).hexdigest() == result.sha256
    if expected_extension in {".pdf", ".docx", ".xlsx"}:
        assert stored.read_bytes() == data


def test_media_limits_use_exact_policy_defaults_and_bound_the_stream(client):
    config = client.application.config
    assert config["MEDIA_IMAGE_MAX_BYTES"] == 8 * 1024 * 1024
    assert config["MEDIA_ATTACHMENT_MAX_BYTES"] == 20 * 1024 * 1024
    assert config["MEDIA_IMAGE_MAX_PIXELS"] == 40_000_000
    assert config["MEDIA_OOXML_MAX_MEMBERS"] == 1024
    assert config["MEDIA_OOXML_MAX_UNCOMPRESSED_BYTES"] == 100 * 1024 * 1024
    assert config["MEDIA_OOXML_MAX_COMPRESSION_RATIO"] == 20
    assert config["MEDIA_OOXML_XML_MAX_NODES"] == 250_000
    assert config["MEDIA_OOXML_XML_MAX_DEPTH"] == 128
    assert config["MEDIA_PDF_MAX_PAGES"] == 500

    with pytest.raises(MediaValidationError):
        _store(client, "large.jpg", "image/jpeg", b"x" * (8 * 1024 * 1024 + 1))


def test_attachment_stream_is_rejected_above_twenty_mebibytes(client, media_root):
    with pytest.raises(MediaValidationError):
        _store(
            client,
            "large.pdf",
            "application/pdf",
            b"%PDF-" + b"x" * (20 * 1024 * 1024),
            confirmed=True,
        )

    assert list(media_root.iterdir()) == []


def test_image_dimension_bomb_is_rejected_before_decode(client, media_root):
    bomb = _image_bytes("PNG", size=(8_000, 5_001))

    with pytest.raises(MediaValidationError):
        _store(client, "bomb.png", "image/png", bomb)

    assert list(media_root.iterdir()) == []


def test_image_is_reencoded_without_exif_or_private_metadata(client, media_root):
    original = _image_bytes("JPEG", exif=True)
    result = _store(client, "private.jpg", "image/jpeg", original)
    stored_bytes = (media_root / result.storage_name).read_bytes()

    with Image.open(io.BytesIO(stored_bytes)) as stored:
        assert not stored.getexif()
        assert "exif" not in stored.info
    assert b"private photographer" not in stored_bytes
    assert result.byte_size == len(stored_bytes)
    assert result.sha256 == hashlib.sha256(stored_bytes).hexdigest()


@pytest.mark.parametrize("name", ["../x.jpg", "..\\x.jpg", "/x.jpg", "C:\\x.jpg"])
def test_path_traversal_upload_names_are_rejected(client, media_root, name):
    with pytest.raises(MediaValidationError):
        _store(client, name, "image/jpeg", _image_bytes("JPEG"))

    assert list(media_root.iterdir()) == []


@pytest.mark.parametrize(
    "kind,extra",
    [
        (
            "docx",
            (("docProps/core.xml", b'<cp:coreProperties xmlns:cp="x" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>Alice</dc:creator></cp:coreProperties>'),),
        ),
        (
            "xlsx",
            (("docProps/core.xml", b'<cp:coreProperties xmlns:cp="x"><cp:lastModifiedBy>Alice</cp:lastModifiedBy></cp:coreProperties>'),),
        ),
        (
            "docx",
            (("docProps/app.xml", b'<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Company>Private Co</Company></Properties>'),),
        ),
        ("xlsx", (("docProps/custom.xml", b"<Properties/>"),)),
        ("docx", (("word/vbaProject.bin", b"macro"),)),
        ("xlsx", (("xl/embeddings/oleObject1.bin", b"object"),)),
        ("docx", (("word/activeX/activeX1.bin", b"active object"),)),
        (
            "docx",
            (("word/_rels/document.xml.rels", b'<Relationships><Relationship TargetMode="External" Target="https://example.invalid/x"/></Relationships>'),),
        ),
        ("xlsx", (("../escape.bin", b"escape"),)),
        ("docx", (("WORD/DOCUMENT.XML", b"duplicate"),)),
    ],
)
def test_ooxml_rejects_metadata_active_content_and_unsafe_members(
    client, media_root, kind, extra
):
    with pytest.raises(MediaValidationError):
        _store(
            client,
            f"unsafe.{kind}",
            OOXML_MIMES[kind],
            _ooxml_bytes(kind, extra=extra),
            confirmed=True,
        )

    assert list(media_root.iterdir()) == []


def test_ooxml_rejects_member_count_uncompressed_and_ratio_bombs(client, media_root):
    cases = []
    many = tuple((f"word/items/{index}.xml", b"") for index in range(1021))
    cases.append(_ooxml_bytes("docx", extra=many))

    cumulative = _ooxml_bytes("docx", extra=(("word/large.bin", b"x" * 4_096),))
    cases.append(cumulative)

    ratio = _ooxml_bytes(
        "docx",
        extra=(("word/compressed.bin", b"A" * 50_000),),
        compression=zipfile.ZIP_DEFLATED,
    )
    cases.append(ratio)

    original_total = client.application.config["MEDIA_OOXML_MAX_UNCOMPRESSED_BYTES"]
    for index, data in enumerate(cases):
        if index == 1:
            with zipfile.ZipFile(io.BytesIO(data)) as package:
                total = sum(item.file_size for item in package.infolist())
            client.application.config["MEDIA_OOXML_MAX_UNCOMPRESSED_BYTES"] = total - 1
        else:
            client.application.config["MEDIA_OOXML_MAX_UNCOMPRESSED_BYTES"] = original_total
        with pytest.raises(MediaValidationError):
            _store(
                client,
                "bomb.docx",
                OOXML_MIMES["docx"],
                data,
                confirmed=True,
            )

    assert list(media_root.iterdir()) == []


def test_ooxml_rejects_main_part_content_type_mismatch(client, media_root):
    data = _ooxml_bytes(
        "docx",
        main_type_override=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
        ),
    )

    with pytest.raises(MediaValidationError):
        _store(
            client,
            "mismatch.docx",
            OOXML_MIMES["docx"],
            data,
            confirmed=True,
        )

    assert list(media_root.iterdir()) == []


@pytest.mark.parametrize(
    "kind,relationship_type,target,part_name",
    [
        (
            "docx",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject",
            "payload/item.bin",
            "word/payload/item.bin",
        ),
        (
            "xlsx",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/control",
            "payload/control.bin",
            "xl/payload/control.bin",
        ),
        (
            "xlsx",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/package",
            "../payload/package.bin",
            "payload/package.bin",
        ),
        (
            "docx",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties",
            "../metadata/arbitrary.xml",
            "metadata/arbitrary.xml",
        ),
    ],
    ids=["ole", "activex", "embedded-package", "custom-properties"],
)
def test_ooxml_rejects_forbidden_relationship_semantics_with_arbitrary_part_names(
    client, media_root, kind, relationship_type, target, part_name
):
    rels_path = (
        "word/_rels/document.xml.rels"
        if kind == "docx"
        else "xl/_rels/workbook.xml.rels"
    )
    relationships = (
        '<?xml version="1.0"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{relationship_type}" Target="{target}"/>'
        "</Relationships>"
    ).encode()
    data = _ooxml_bytes(
        kind,
        extra=((rels_path, relationships), (part_name, b"opaque payload")),
    )

    with pytest.raises(MediaValidationError):
        _store(
            client,
            f"semantic.{kind}",
            OOXML_MIMES[kind],
            data,
            confirmed=True,
        )

    assert list(media_root.iterdir()) == []


@pytest.mark.parametrize(
    "kind,part_name,content_type,part_data",
    [
        (
            "docx",
            "word/data/arbitrary.bin",
            "application/vnd.openxmlformats-officedocument.oleObject",
            b"opaque",
        ),
        (
            "xlsx",
            "xl/data/arbitrary.xml",
            "application/vnd.ms-office.activeX+xml",
            b"<control/>",
        ),
        (
            "docx",
            "metadata/arbitrary.xml",
            "application/vnd.openxmlformats-officedocument.custom-properties+xml",
            b"<Properties/>",
        ),
        (
            "xlsx",
            "metadata/arbitrary.xml",
            "application/vnd.openxmlformats-package.core-properties+xml",
            b'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>Alice</dc:creator></cp:coreProperties>',
        ),
    ],
    ids=["ole", "activex", "custom-properties", "core-properties"],
)
def test_ooxml_rejects_forbidden_content_types_with_arbitrary_part_names(
    client, media_root, kind, part_name, content_type, part_data
):
    data = _ooxml_bytes(
        kind,
        extra=((part_name, part_data),),
        content_type_overrides=((part_name, content_type),),
    )

    with pytest.raises(MediaValidationError):
        _store(
            client,
            f"semantic.{kind}",
            OOXML_MIMES[kind],
            data,
            confirmed=True,
        )

    assert list(media_root.iterdir()) == []


def test_ooxml_resolves_core_properties_relationship_target_before_inspection(
    client, media_root
):
    relationships = (
        b'<?xml version="1.0"?>'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="../metadata/renamed.xml"/>'
        b"</Relationships>"
    )
    private_core = (
        b'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        b'xmlns:cp2="http://schemas.openxmlformats.org/package/2006/metadata/core-properties">'
        b"<cp2:lastModifiedBy>Alice</cp2:lastModifiedBy></cp:coreProperties>"
    )
    data = _ooxml_bytes(
        "docx",
        extra=(
            ("word/_rels/document.xml.rels", relationships),
            ("metadata/renamed.xml", private_core),
        ),
    )

    with pytest.raises(MediaValidationError):
        _store(client, "private.docx", OOXML_MIMES["docx"], data, confirmed=True)

    assert list(media_root.iterdir()) == []


@pytest.mark.parametrize(
    "kind,main_xml",
    [
        (
            "docx",
            b'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>',
        ),
        ("xlsx", b"<workbook/>"),
        ("docx", b"<not-well-formed"),
    ],
    ids=["wrong-root", "wrong-namespace", "malformed"],
)
def test_ooxml_rejects_invalid_exact_main_xml_part(client, media_root, kind, main_xml):
    with pytest.raises(MediaValidationError):
        _store(
            client,
            f"invalid-main.{kind}",
            OOXML_MIMES[kind],
            _ooxml_bytes(kind, main_xml=main_xml),
            confirmed=True,
        )

    assert list(media_root.iterdir()) == []


@pytest.mark.parametrize(
    "kind,main_xml,max_nodes,max_depth",
    [
        (
            "docx",
            (
                b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                + (b"<w:r/>" * 64)
                + b"</w:document>"
            ),
            64,
            128,
        ),
        (
            "xlsx",
            (
                b'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                + (b"<sheet>" * 8)
                + (b"</sheet>" * 8)
                + b"</workbook>"
            ),
            64,
            8,
        ),
    ],
    ids=["node-budget", "depth-budget"],
)
def test_ooxml_main_xml_is_rejected_above_node_or_depth_budget(
    client, media_root, kind, main_xml, max_nodes, max_depth
):
    client.application.config["MEDIA_OOXML_XML_MAX_NODES"] = max_nodes
    client.application.config["MEDIA_OOXML_XML_MAX_DEPTH"] = max_depth

    with pytest.raises(MediaValidationError):
        _store(
            client,
            f"bounded.{kind}",
            OOXML_MIMES[kind],
            _ooxml_bytes(kind, main_xml=main_xml),
            confirmed=True,
        )

    assert list(media_root.iterdir()) == []


def test_ooxml_resolved_core_metadata_is_rejected_above_node_budget(
    client, media_root
):
    client.application.config["MEDIA_OOXML_XML_MAX_NODES"] = 32
    renamed_core = (
        b'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties">'
        + (b"<cp:category/>" * 32)
        + b"</cp:coreProperties>"
    )
    data = _ooxml_bytes(
        "docx",
        extra=(("metadata/renamed.xml", renamed_core),),
        content_type_overrides=(
            (
                "metadata/renamed.xml",
                "application/vnd.openxmlformats-package.core-properties+xml",
            ),
        ),
    )

    with pytest.raises(MediaValidationError):
        _store(client, "bounded.docx", OOXML_MIMES["docx"], data, confirmed=True)

    assert list(media_root.iterdir()) == []


def test_ooxml_rejects_duplicate_canonical_content_type_declarations(
    client, media_root
):
    content_types = (
        b'<?xml version="1.0"?>'
        b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        b'<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.oleObject"/>'
        b'<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        b"</Types>"
    )
    data = _ooxml_bytes(
        "docx", extra=(("[Content_Types].xml", content_types),)
    )

    with pytest.raises(MediaValidationError):
        _store(client, "ambiguous.docx", OOXML_MIMES["docx"], data, confirmed=True)

    assert list(media_root.iterdir()) == []


def test_ooxml_rejects_duplicate_relationship_ids(client, media_root):
    relationships = (
        b'<?xml version="1.0"?>'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/a.png"/>'
        b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/b.png"/>'
        b"</Relationships>"
    )
    data = _ooxml_bytes(
        "docx",
        extra=(
            ("word/_rels/document.xml.rels", relationships),
            ("word/media/a.png", b"a"),
            ("word/media/b.png", b"b"),
        ),
    )

    with pytest.raises(MediaValidationError):
        _store(client, "ambiguous.docx", OOXML_MIMES["docx"], data, confirmed=True)

    assert list(media_root.iterdir()) == []


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(_pdf_bytes(metadata={"/Author": "Alice"}), id="metadata"),
        pytest.param(_pdf_bytes(action=True), id="action"),
        pytest.param(_pdf_bytes(attachment=True), id="embedded-file"),
        pytest.param(_pdf_bytes(encrypt=True), id="encrypted"),
        pytest.param(b"%PDF-1.7\nnot a real PDF", id="parse-failure"),
        pytest.param(_pdf_bytes(pages=501), id="page-bomb"),
    ],
)
def test_pdf_rejects_metadata_actions_embedded_files_encryption_parse_and_page_bombs(
    client, media_root, data
):
    with pytest.raises(MediaValidationError):
        _store(client, "unsafe.pdf", "application/pdf", data, confirmed=True)

    assert list(media_root.iterdir()) == []


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(_pdf_bytes(page_metadata=True), id="page-xmp-metadata"),
        pytest.param(_pdf_bytes(xfa=True), id="xfa-acroform"),
        pytest.param(_pdf_bytes(rich_media=True), id="rich-media"),
    ],
)
def test_pdf_rejects_nested_metadata_forms_and_rich_media(
    client, media_root, data
):
    with pytest.raises(MediaValidationError):
        _store(client, "active.pdf", "application/pdf", data, confirmed=True)

    assert list(media_root.iterdir()) == []


@pytest.mark.parametrize("kind", ["pdf", "docx", "xlsx"])
def test_document_upload_requires_fixed_metadata_privacy_confirmation(
    client, media_root, kind
):
    data = _pdf_bytes() if kind == "pdf" else _ooxml_bytes(kind)
    mime = "application/pdf" if kind == "pdf" else OOXML_MIMES[kind]

    with pytest.raises(MediaValidationError):
        _store(client, f"document.{kind}", mime, data, confirmed=False)

    assert list(media_root.iterdir()) == []


def test_sha256_duplicate_reuses_ready_asset_and_single_file(client, db, media_root):
    data = _ooxml_bytes("docx")
    first = _store(client, "first.docx", OOXML_MIMES["docx"], data, confirmed=True)
    second = _store(client, "second.docx", OOXML_MIMES["docx"], data, confirmed=True)

    assert second.id == first.id
    assert db.execute("SELECT COUNT(*) FROM media_assets").fetchone()[0] == 1
    assert [path.name for path in media_root.iterdir()] == [first.storage_name]


def test_duplicate_ready_upload_restores_missing_file_with_published_reference(
    client, db, media_root
):
    data = _image_bytes("PNG")
    first = _store(client, "published.png", "image/png", data)
    stored_path = media_root / first.storage_name
    expected_bytes = stored_path.read_bytes()
    _publish_share_reference(db, first.id)
    stored_path.unlink()

    restored = _store(client, "duplicate.png", "image/png", data)

    assert restored.id == first.id
    assert stored_path.read_bytes() == expected_bytes
    assert hashlib.sha256(stored_path.read_bytes()).hexdigest() == first.sha256
    assert _row(db, first.id)["status"] == "ready"
    assert db.execute("SELECT COUNT(*) FROM media_assets").fetchone()[0] == 1
    assert db.execute(
        "SELECT COUNT(*) FROM content_items "
        "WHERE status='published' AND share_image_media_id=?",
        (first.id,),
    ).fetchone()[0] == 1


def test_duplicate_ready_upload_rejects_corrupt_file_without_overwriting_evidence(
    client, db, media_root
):
    data = _image_bytes("PNG")
    first = _store(client, "original.png", "image/png", data)
    stored_path = media_root / first.storage_name
    corrupt_evidence = b"corrupt durable media evidence"
    stored_path.write_bytes(corrupt_evidence)
    before = dict(_row(db, first.id))

    with pytest.raises(MediaValidationError):
        _store(client, "duplicate.png", "image/png", data)

    assert stored_path.read_bytes() == corrupt_evidence
    assert dict(_row(db, first.id)) == before
    assert db.execute("SELECT COUNT(*) FROM media_assets").fetchone()[0] == 1
    assert not any(path.name.startswith(".upload-") for path in media_root.iterdir())


def test_missing_duplicate_fails_if_ready_row_is_archived_during_restoration(
    client, db, media_root, monkeypatch
):
    data = _image_bytes("PNG")
    first = _store(client, "original.png", "image/png", data)
    stored_path = media_root / first.storage_name
    expected_bytes = stored_path.read_bytes()
    stored_path.unlink()
    restore = media_service._reuse_or_restore_ready_duplicate

    def archive_at_restoration_boundary(root, temporary_path, row):
        archive_media(row["id"])
        return restore(root, temporary_path, row)

    monkeypatch.setattr(
        media_service,
        "_reuse_or_restore_ready_duplicate",
        archive_at_restoration_boundary,
    )

    with pytest.raises(MediaValidationError):
        _store(client, "duplicate.png", "image/png", data)

    assert _row(db, first.id)["status"] == "archived"
    assert stored_path.read_bytes() == expected_bytes
    assert hashlib.sha256(stored_path.read_bytes()).hexdigest() == first.sha256
    assert db.execute("SELECT COUNT(*) FROM media_assets").fetchone()[0] == 1
    assert not any(path.name.startswith(".upload-") for path in media_root.iterdir())


def test_rename_failure_archives_pending_row_and_cleans_temporary_file(
    client, db, media_root, monkeypatch
):
    def fail_rename(source, destination):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(media_service.os, "replace", fail_rename)

    with pytest.raises(OSError):
        _store(client, "photo.png", "image/png", _image_bytes("PNG"))

    rows = db.execute("SELECT status,storage_name FROM media_assets").fetchall()
    assert [row["status"] for row in rows] == ["archived"]
    assert list(media_root.iterdir()) == []


def test_ready_transition_failure_archives_row_but_retains_renamed_media(
    client, db, media_root, monkeypatch
):
    def fail_ready(connection, asset_id, timestamp):
        raise sqlite3.OperationalError("simulated ready failure")

    monkeypatch.setattr(media_service, "_mark_media_ready", fail_ready)

    with pytest.raises(sqlite3.OperationalError):
        _store(client, "photo.png", "image/png", _image_bytes("PNG"))

    row = db.execute("SELECT status,storage_name FROM media_assets").fetchone()
    assert row["status"] == "archived"
    assert (media_root / row["storage_name"]).is_file()
    assert not any(path.name.startswith(".upload-") for path in media_root.iterdir())


def test_archive_keeps_file_and_direct_sql_trigger_rejects_published_reference(
    client, db, media_root
):
    asset = _store(client, "share.png", "image/png", _image_bytes("PNG"))
    group_id = db.execute(
        "INSERT INTO content_groups (entry_type,canonical_slug,created_at,updated_at) "
        "VALUES ('announcement','media-ref','2026-08-24 10:00:00','2026-08-24 10:00:00')"
    ).lastrowid
    content_id = db.execute(
        "INSERT INTO content_items "
        "(content_group_id,entry_type,revision_number,slug,title,summary,seo_title,seo_description,"
        "share_image_media_id,status,lock_version,created_at,updated_at) "
        "VALUES (?,'announcement',1,'media-ref','Title','Summary','SEO','Description',?,'draft',1,"
        "'2026-08-24 10:00:00','2026-08-24 10:00:00')",
        (group_id, asset.id),
    ).lastrowid
    db.execute(
        "INSERT INTO announcement_content (content_item_id) VALUES (?)", (content_id,)
    )
    db.execute(
        "UPDATE content_items SET status='published',published_at='2026-08-24 10:00:00',"
        "updated_at='2026-08-24 10:00:00' WHERE id=?",
        (content_id,),
    )
    db.commit()

    with pytest.raises(sqlite3.IntegrityError, match="published content still references"):
        db.execute(
            "UPDATE media_assets SET status='archived',archived_at='2026-08-24 11:00:00',"
            "updated_at='2026-08-24 11:00:00' WHERE id=?",
            (asset.id,),
        )
    db.rollback()
    with client.application.app_context(), pytest.raises(MediaInUseError):
        archive_media(asset.id)

    assert (media_root / asset.storage_name).is_file()
    assert _row(db, asset.id)["status"] == "ready"


def test_archive_unreferenced_media_changes_only_database_status(client, db, media_root):
    asset = _store(client, "unused.png", "image/png", _image_bytes("PNG"))

    with client.application.app_context():
        archived = archive_media(asset.id)

    assert archived.status == "archived"
    assert (media_root / asset.storage_name).is_file()
    assert _row(db, asset.id)["status"] == "archived"


def test_recovery_dry_run_reports_without_names_or_writes_and_apply_reconciles(
    client, db, media_root
):
    data = _image_bytes("PNG")
    recoverable_id = _insert_pending(
        db, storage_name="recoverable.png", mime="image/png", data=data
    )
    (media_root / "recoverable.png").write_bytes(data)
    missing_pending_id = _insert_pending(
        db, storage_name="pending-missing.png", mime="image/png", data=data + b"x"
    )
    ready_missing_id = _insert_pending(
        db, storage_name="ready-missing.png", mime="image/png", data=data + b"y"
    )
    _mark_ready(db, ready_missing_id)
    (media_root / "orphan-secret-name.png").write_bytes(data)

    with client.application.app_context():
        preview = recover_media_storage(apply=False)

    assert [(item.asset_id, item.status) for item in preview.findings] == [
        (recoverable_id, "pending_recoverable"),
        (missing_pending_id, "pending_missing"),
        (ready_missing_id, "ready_missing"),
        (None, "orphan_file"),
    ]
    assert _row(db, recoverable_id)["status"] == "pending"
    assert _row(db, missing_pending_id)["status"] == "pending"
    assert _row(db, ready_missing_id)["status"] == "ready"
    assert "orphan-secret-name.png" not in repr(preview)

    with client.application.app_context():
        applied = recover_media_storage(apply=True)

    assert [(item.asset_id, item.status) for item in applied.findings] == [
        (recoverable_id, "pending_recovered"),
        (missing_pending_id, "pending_archived"),
        (ready_missing_id, "missing_archived"),
        (None, "orphan_file"),
    ]
    assert _row(db, recoverable_id)["status"] == "ready"
    assert _row(db, missing_pending_id)["status"] == "archived"
    assert _row(db, ready_missing_id)["status"] == "archived"
    assert (media_root / "orphan-secret-name.png").is_file()


def test_recovery_archives_pending_hash_mismatch_without_deleting_file(
    client, db, media_root
):
    expected = _image_bytes("PNG")
    asset_id = _insert_pending(
        db, storage_name="mismatch.png", mime="image/png", data=expected
    )
    (media_root / "mismatch.png").write_bytes(expected + b"changed")

    with client.application.app_context():
        result = recover_media_storage(apply=True)

    assert [(item.asset_id, item.status) for item in result.findings] == [
        (asset_id, "pending_mismatch_archived")
    ]
    assert _row(db, asset_id)["status"] == "archived"
    assert (media_root / "mismatch.png").is_file()


@pytest.mark.parametrize("apply", [False, True], ids=["dry-run", "apply"])
def test_recovery_refuses_missing_root_without_filesystem_or_database_changes(
    client, db, media_root, apply
):
    data = _image_bytes("PNG")
    pending_id = _insert_pending(
        db, storage_name="pending.png", mime="image/png", data=data
    )
    ready_id = _insert_pending(
        db, storage_name="ready.png", mime="image/png", data=data + b"ready"
    )
    _mark_ready(db, ready_id)
    missing_root = media_root.parent / f"missing-recovery-root-{apply}"
    client.application.config["MEDIA_UPLOAD_ROOT"] = str(missing_root)

    with client.application.app_context(), pytest.raises(OSError):
        recover_media_storage(apply=apply)

    assert not missing_root.exists()
    assert _row(db, pending_id)["status"] == "pending"
    assert _row(db, ready_id)["status"] == "ready"


def test_recover_media_cli_is_dry_run_first_and_never_prints_storage_names(
    client, db, media_root, monkeypatch, capsys
):
    data = _image_bytes("PNG")
    asset_id = _insert_pending(
        db, storage_name="private-storage-name.png", mime="image/png", data=data
    )
    (media_root / "private-storage-name.png").write_bytes(data)
    monkeypatch.setenv("AI_PLATFORM_MEDIA_ROOT", str(media_root))

    assert manage.main(["recover-media-storage"]) == 0
    dry_output = capsys.readouterr().out.strip()
    assert dry_output == (
        f"mode=dry-run count=1 findings={asset_id}:pending_recoverable"
    )
    assert "private-storage-name" not in dry_output
    assert _row(db, asset_id)["status"] == "pending"

    assert manage.main(["recover-media-storage", "--apply"]) == 0
    apply_output = capsys.readouterr().out.strip()
    assert apply_output == f"mode=apply count=1 findings={asset_id}:pending_recovered"
    assert "private-storage-name" not in apply_output
    assert _row(db, asset_id)["status"] == "ready"
