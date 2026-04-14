"""METS XML generation for E-ARK SIP packages.

Pure XML generation from structured data. No file I/O beyond
returning an lxml ElementTree.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from xml.etree.ElementTree import QName

from lxml import etree

APP_NAME = "E-ARK SIP Creator"
APP_VERSION = "1.0.0-beta.1"

NS = {
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "xlink": "http://www.w3.org/1999/xlink",
    "ext": "ExtensionMETS",
    "sip": "https://DILCIS.eu/XML/METS/SIPExtensionMETS",
    "csip": "https://DILCIS.eu/XML/METS/CSIPExtensionMETS",
}


@dataclass
class Agent:
    """Represents a METS agent element."""

    role: str
    type: str
    name: str
    note: str | None = None
    othertype: str | None = None
    otherrole: str | None = None
    notetype: str | None = None


@dataclass
class AltRecordID:
    """Represents a METS altRecordID element."""

    type: str
    value: str


@dataclass
class MetsHeader:
    """Container for all METS header values."""

    label: str = ""
    type: str = "Datasets"
    other_type: str = ""
    contentinformationtype: str = "citserms_v2_1"
    other_contentinformationtype: str = ""
    recordstatus: str = "NEW"
    agents: list[Agent] = field(default_factory=list)
    alt_record_ids: list[AltRecordID] = field(default_factory=list)


def _new_uuid() -> str:
    """Generate a uuid string in E-ARK format."""
    return f"uuid-{uuid.uuid4()}"


def _add_agent_element(
    parent: etree._Element, agent: Agent
) -> None:
    """Add a single agent element to the parent."""
    agent_el = etree.SubElement(parent, "agent")
    agent_el.set("ROLE", agent.role)
    agent_el.set("TYPE", agent.type)
    if agent.othertype:
        agent_el.set("OTHERTYPE", agent.othertype)
    if agent.otherrole:
        agent_el.set("OTHERROLE", agent.otherrole)
    name_el = etree.SubElement(agent_el, "name")
    name_el.text = agent.name
    if agent.note:
        note_el = etree.SubElement(agent_el, "note")
        if agent.notetype:
            note_el.set(
                str(QName(NS["csip"], "NOTETYPE")), agent.notetype
            )
        note_el.text = agent.note


def _add_file_group(
    file_sec: etree._Element,
    files: dict,
    use_label: str,
    contentinformationtype: str | None = None,
) -> None:
    """Add a fileGrp element with file entries to fileSec.

    Deduplicates the four near-identical fileGrp blocks from
    the original script into one reusable function.

    Args:
        file_sec: The fileSec parent element.
        files: Dict of file metadata (keyed by path).
        use_label: USE attribute value (e.g. 'Schemas').
        contentinformationtype: If set, added as csip:CONTENTINFORMATIONTYPE
            on the fileGrp (used for Representations).
    """
    if not files:
        return

    file_grp = etree.SubElement(file_sec, "fileGrp")
    file_grp.set("ID", _new_uuid())
    file_grp.set("USE", use_label)
    if contentinformationtype:
        file_grp.set(
            str(QName(NS["csip"], "CONTENTINFORMATIONTYPE")),
            contentinformationtype,
        )

    for file_info in files.values():
        file_el = etree.SubElement(file_grp, "file")
        file_el.set("ID", file_info["uuid"])
        file_el.set("MIMETYPE", file_info["mimetype"])
        file_el.set("SIZE", file_info["filesize"])
        file_el.set("CREATED", file_info["createdate"])
        file_el.set("CHECKSUM", file_info["hashvalue"])
        file_el.set("CHECKSUMTYPE", "SHA-256")
        flocat = etree.SubElement(file_el, "FLocat")
        flocat.set("LOCTYPE", "URL")
        flocat.set(str(QName(NS["xlink"], "type")), "simple")
        flocat.set(str(QName(NS["xlink"], "href")), file_info["filelink"])


def _add_struct_div(
    parent_div: etree._Element,
    files: dict,
    label: str,
) -> None:
    """Add a structMap div with fptr entries.

    Args:
        parent_div: Parent div element.
        files: Dict of file metadata.
        label: LABEL attribute for the div.
    """
    if not files:
        return

    div = etree.SubElement(parent_div, "div")
    div.set("ID", _new_uuid())
    div.set("LABEL", label)
    for file_info in files.values():
        fptr = etree.SubElement(div, "fptr")
        fptr.set("FILEID", file_info["uuid"])


def build_mets(
    header: MetsHeader,
    file_categories: dict[str, dict],
) -> etree._ElementTree:
    """Build a complete METS XML document.

    Args:
        header: MetsHeader with all header values and agents.
        file_categories: Dict mapping category names to file
            metadata dicts. Expected keys: 'representation',
            'schema', 'descriptivemetadata', 'preservationmetadata',
            'documentation', 'representationmetadata'.

    Returns:
        lxml ElementTree of the complete METS document.
    """
    representations = file_categories.get("representation", {})
    schemas = file_categories.get("schema", {})
    descriptive_md = file_categories.get("descriptivemetadata", {})
    preservation_md = file_categories.get("preservationmetadata", {})
    documentation = file_categories.get("documentation", {})
    representation_md = file_categories.get("representationmetadata", {})

    # Resolve effective content information type
    cit = header.contentinformationtype
    if cit == "OTHER" and header.other_contentinformationtype:
        cit = header.other_contentinformationtype

    # Resolve effective TYPE
    mets_type = header.type
    if mets_type == "Other" and header.other_type:
        mets_type = header.other_type

    # ── Root element ──
    root = etree.Element(
        "mets",
        attrib={"xmlns": "http://www.loc.gov/METS/"},
        nsmap=NS,
    )
    root.set("OBJID", f"IP_{uuid.uuid4()}")
    if header.label:
        root.set("LABEL", header.label)
    root.set("TYPE", mets_type)
    root.set("PROFILE", "https://earksip.dilcis.eu/profile/E-ARK-SIP.xml")
    root.set(str(QName(NS["csip"], "CONTENTINFORMATIONTYPE")), cit)

    # ── metsHdr ──
    mets_hdr = etree.SubElement(root, "metsHdr")
    mets_hdr.set(
        "CREATEDATE",
        datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    mets_hdr.set("RECORDSTATUS", header.recordstatus)
    mets_hdr.set(str(QName(NS["csip"], "OAISPACKAGETYPE")), "SIP")

    # Hardcoded creator software agent (identifies this tool)
    _add_agent_element(
        mets_hdr,
        Agent(
            role="CREATOR",
            type="OTHER",
            othertype="SOFTWARE",
            name=APP_NAME,
            note=APP_VERSION,
            notetype="SOFTWARE VERSION",
        ),
    )

    # User-defined agents
    for agent in header.agents:
        _add_agent_element(mets_hdr, agent)

    # altRecordIDs
    for record in header.alt_record_ids:
        if record.value:
            alt = etree.SubElement(mets_hdr, "altRecordID")
            alt.set("TYPE", record.type)
            alt.text = record.value

    # ── dmdSec ──
    amd_ids: list[str] = []
    dmd_uuid: str | None = None

    if descriptive_md:
        dmd_sec = etree.SubElement(root, "dmdSec")
        dmd_uuid = _new_uuid()
        dmd_sec.set("ID", dmd_uuid)
        dmd_sec.set(
            "CREATED",
            datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        dmd_sec.set("STATUS", "CURRENT")
        for file_info in descriptive_md.values():
            md_ref = etree.SubElement(dmd_sec, "mdRef")
            md_ref.set("LOCTYPE", "URL")
            md_ref.set("MDTYPE", "EAD")
            md_ref.set(str(QName(NS["xlink"], "type")), "simple")
            md_ref.set(str(QName(NS["xlink"], "href")), file_info["filelink"])
            md_ref.set("MIMETYPE", file_info["mimetype"])
            md_ref.set("SIZE", file_info["filesize"])
            md_ref.set("CREATED", file_info["createdate"])
            md_ref.set("CHECKSUM", file_info["hashvalue"])
            md_ref.set("CHECKSUMTYPE", "SHA-256")

    # ── amdSec (preservation metadata) ──
    if preservation_md:
        amd_sec = etree.SubElement(root, "amdSec")
        for file_info in preservation_md.values():
            amd_uuid = _new_uuid()
            digiprov = etree.SubElement(amd_sec, "digiprovMD")
            digiprov.set("ID", amd_uuid)
            digiprov.set("STATUS", "CURRENT")
            amd_ids.append(amd_uuid)
            md_ref = etree.SubElement(digiprov, "mdRef")
            md_ref.set("LOCTYPE", "URL")
            md_ref.set("MDTYPE", "PREMIS")
            md_ref.set(str(QName(NS["xlink"], "type")), "simple")
            md_ref.set(str(QName(NS["xlink"], "href")), file_info["filelink"])
            md_ref.set("MIMETYPE", file_info["mimetype"])
            md_ref.set("SIZE", file_info["filesize"])
            md_ref.set("CREATED", file_info["createdate"])
            md_ref.set("CHECKSUM", file_info["hashvalue"])
            md_ref.set("CHECKSUMTYPE", "SHA-256")

    # ── amdSec (representation metadata) ──
    if representation_md:
        amd_sec_rep = etree.SubElement(root, "amdSec")
        amd_sec_rep.set("ID", _new_uuid())
        for file_info in representation_md.values():
            tech_md = etree.SubElement(amd_sec_rep, "techMD")
            tech_md.set("ID", _new_uuid())
            tech_md.set("STATUS", "CURRENT")
            md_ref = etree.SubElement(tech_md, "mdRef")
            md_ref.set("LOCTYPE", "URL")
            md_ref.set("MDTYPE", "OTHER")
            md_ref.set("OTHERMDTYPE", "RepresentationMetadata")
            md_ref.set(str(QName(NS["xlink"], "type")), "simple")
            md_ref.set(str(QName(NS["xlink"], "href")), file_info["filelink"])
            md_ref.set("MIMETYPE", file_info["mimetype"])
            md_ref.set("SIZE", file_info["filesize"])
            md_ref.set("CREATED", file_info["createdate"])
            md_ref.set("CHECKSUM", file_info["hashvalue"])
            md_ref.set("CHECKSUMTYPE", "SHA-256")

    # ── fileSec ──
    file_sec = etree.SubElement(root, "fileSec")
    file_sec.set("ID", _new_uuid())

    _add_file_group(file_sec, documentation, "Documentation")
    _add_file_group(file_sec, schemas, "Schemas")
    _add_file_group(
        file_sec, representations, "Representations",
        contentinformationtype=cit,
    )
    _add_file_group(file_sec, representation_md, "RepresentationMetadata")

    # ── structMap ──
    struct_map = etree.SubElement(root, "structMap")
    struct_map.set("ID", _new_uuid())
    struct_map.set("TYPE", "PHYSICAL")
    struct_map.set("LABEL", "CSIP")

    root_div = etree.SubElement(struct_map, "div")
    root_div.set("ID", _new_uuid())

    # Metadata div (always present)
    metadata_div = etree.SubElement(root_div, "div")
    metadata_div.set("ID", _new_uuid())
    metadata_div.set("LABEL", "Metadata")
    if amd_ids:
        metadata_div.set("ADMID", " ".join(amd_ids))
    if dmd_uuid:
        metadata_div.set("DMDID", dmd_uuid)

    # Schemas div
    _add_struct_div(root_div, schemas, "Schemas")

    # Documentation div
    _add_struct_div(root_div, documentation, "Documentation")

    # Representations div
    if representations or representation_md:
        rep_div = etree.SubElement(root_div, "div")
        rep_div.set("ID", _new_uuid())
        rep_div.set("LABEL", "Representations")

        rep1_div = etree.SubElement(rep_div, "div")
        rep1_div.set("ID", _new_uuid())
        rep1_div.set("LABEL", "rep_1")
        if amd_ids:
            rep1_div.set("ADMID", " ".join(amd_ids))

        # Data sub-div
        if representations:
            data_div = etree.SubElement(rep1_div, "div")
            data_div.set("ID", _new_uuid())
            data_div.set("LABEL", "Data")
            for file_info in representations.values():
                fptr = etree.SubElement(data_div, "fptr")
                fptr.set("FILEID", file_info["uuid"])

        # Metadata sub-div
        if representation_md:
            meta_div = etree.SubElement(rep1_div, "div")
            meta_div.set("ID", _new_uuid())
            meta_div.set("LABEL", "Metadata")
            for file_info in representation_md.values():
                fptr = etree.SubElement(meta_div, "fptr")
                fptr.set("FILEID", file_info["uuid"])

    return etree.ElementTree(root)
