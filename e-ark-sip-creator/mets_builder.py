"""METS XML generation for E-ARK SIP packages.

Pure XML generation from structured data. No file I/O beyond
returning an lxml ElementTree.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from xml.etree.ElementTree import QName

from lxml import etree

APP_NAME = "E-ARK SIP Creator"
APP_VERSION = "1.1.0-beta.2"

METS_NS = "http://www.loc.gov/METS/"

NS = {
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "xlink": "http://www.w3.org/1999/xlink",
    "sip": "https://DILCIS.eu/XML/METS/SIPExtensionMETS",
    "csip": "https://DILCIS.eu/XML/METS/CSIPExtensionMETS",
}

# Namespace -> schema pairs for xsi:schemaLocation, taken verbatim (values and
# order) from the example METS root in the E-ARK SIP METS profile v2.1.0.
# The namespace URIs are identifiers, not download locations; appending .xsd
# to them does not give a working URL. xlink points at LoC's copy because
# mets.xsd references attribute groups that the W3C xlink.xsd lacks.
SCHEMA_LOCATIONS = [
    (METS_NS, "http://www.loc.gov/standards/mets/mets.xsd"),
    (NS["xlink"], "http://www.loc.gov/standards/mets/xlink.xsd"),
    (NS["csip"], "https://earkcsip.dilcis.eu/schema/DILCISExtensionMETS.xsd"),
    (NS["sip"], "https://earksip.dilcis.eu/schema/DILCISExtensionSIPMETS.xsd"),
]


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
    othercontentinformationtype: str | None = None,
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
        othercontentinformationtype: If set, added as
            csip:OTHERCONTENTINFORMATIONTYPE on the fileGrp. Carries the
            custom value when contentinformationtype is "OTHER".
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
    if othercontentinformationtype:
        file_grp.set(
            str(QName(NS["csip"], "OTHERCONTENTINFORMATIONTYPE")),
            othercontentinformationtype,
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


def _descriptive_mdtype(file_info: dict) -> tuple[str, str | None]:
    """MDTYPE and OTHERMDTYPE for a dmdSec, from what collect_files detected.

    An entry without detection data (one built by hand) is OTHER with the
    file extension, the same rule as for a file that is not XML.
    """
    mdtype = file_info.get("mdtype", "OTHER")
    othermdtype = file_info.get("othermdtype")
    if mdtype != "OTHER":
        return mdtype, None
    if not othermdtype:
        name = file_info.get("fgsfilename") or file_info.get("filelink", "")
        othermdtype = Path(name).suffix.lstrip(".").lower() or "unknown"
    return "OTHER", othermdtype


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
        lxml ElementTree of the complete METS document. Its OBJID, and the
        LABEL of the root structMap div, hold a provisional IP_<uuid>;
        create_package replaces both with the package name through
        set_package_name, because the name is only known once the
        package folder has been claimed.
    """
    representations = file_categories.get("representation", {})
    schemas = file_categories.get("schema", {})
    descriptive_md = file_categories.get("descriptivemetadata", {})
    preservation_md = file_categories.get("preservationmetadata", {})
    documentation = file_categories.get("documentation", {})
    representation_md = file_categories.get("representationmetadata", {})

    # Content information type. The CSIP schema restricts
    # csip:CONTENTINFORMATIONTYPE to a fixed list, so for a custom value it
    # stays "OTHER" and the value goes into csip:OTHERCONTENTINFORMATIONTYPE.
    cit = header.contentinformationtype
    other_cit = header.other_contentinformationtype if cit == "OTHER" else ""

    # TYPE. Same pattern as the content information type: a custom value keeps
    # the vocabulary term "Other" in TYPE and goes into csip:OTHERTYPE, the
    # attribute the CSIP schema declares for it.
    mets_type = header.type
    other_type = header.other_type if mets_type == "Other" else ""

    # ── Root element ──
    root = etree.Element(
        "mets",
        attrib={"xmlns": METS_NS},
        nsmap=NS,
    )
    root.set(
        str(QName(NS["xsi"], "schemaLocation")),
        " ".join(f"{ns} {xsd}" for ns, xsd in SCHEMA_LOCATIONS),
    )
    objid = f"IP_{uuid.uuid4()}"  # provisional, see set_package_name
    root.set("OBJID", objid)
    if header.label:
        root.set("LABEL", header.label)
    root.set("TYPE", mets_type)
    if other_type:
        root.set(str(QName(NS["csip"], "OTHERTYPE")), other_type)
    root.set("PROFILE", "https://earksip.dilcis.eu/profile/E-ARK-SIP.xml")
    root.set(str(QName(NS["csip"], "CONTENTINFORMATIONTYPE")), cit)
    if other_cit:
        root.set(str(QName(NS["csip"], "OTHERCONTENTINFORMATIONTYPE")), other_cit)

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
    # One dmdSec per descriptive file. The METS schema allows at most one
    # mdRef in a metadata section, so several files cannot share one.
    dmd_ids: list[str] = []
    dmd_created = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for file_info in descriptive_md.values():
        dmd_sec = etree.SubElement(root, "dmdSec")
        dmd_id = _new_uuid()
        dmd_sec.set("ID", dmd_id)
        dmd_sec.set("CREATED", dmd_created)
        dmd_sec.set("STATUS", "CURRENT")
        dmd_ids.append(dmd_id)
        md_ref = etree.SubElement(dmd_sec, "mdRef")
        md_ref.set("LOCTYPE", "URL")
        mdtype, othermdtype = _descriptive_mdtype(file_info)
        md_ref.set("MDTYPE", mdtype)
        if othermdtype:
            md_ref.set("OTHERMDTYPE", othermdtype)
        md_ref.set(str(QName(NS["xlink"], "type")), "simple")
        md_ref.set(str(QName(NS["xlink"], "href")), file_info["filelink"])
        md_ref.set("MIMETYPE", file_info["mimetype"])
        md_ref.set("SIZE", file_info["filesize"])
        md_ref.set("CREATED", file_info["createdate"])
        md_ref.set("CHECKSUM", file_info["hashvalue"])
        md_ref.set("CHECKSUMTYPE", "SHA-256")

    amd_ids: list[str] = []

    # ── amdSec ──
    # A single amdSec holds both kinds of administrative metadata. The METS
    # schema defines its children as an ordered sequence (techMD, rightsMD,
    # sourceMD, digiprovMD), so techMD must be written before digiprovMD.
    if representation_md or preservation_md:
        amd_sec = etree.SubElement(root, "amdSec")
        amd_sec.set("ID", _new_uuid())

        # Representation metadata
        for file_info in representation_md.values():
            tech_md = etree.SubElement(amd_sec, "techMD")
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

        # Preservation metadata. Only these IDs go into amd_ids, which feeds
        # the package-level Metadata div's ADMID.
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

    # ── fileSec ──
    # Only written when there are files to list. The METS schema requires at
    # least one fileGrp, and the PRD allows metadata-only packages.
    if documentation or schemas or representations or representation_md:
        file_sec = etree.SubElement(root, "fileSec")
        file_sec.set("ID", _new_uuid())

        _add_file_group(file_sec, documentation, "Documentation")
        _add_file_group(file_sec, schemas, "Schemas")
        _add_file_group(
            file_sec, representations, "Representations",
            contentinformationtype=cit,
            othercontentinformationtype=other_cit,
        )
        _add_file_group(file_sec, representation_md, "RepresentationMetadata")

    # ── structMap ──
    struct_map = etree.SubElement(root, "structMap")
    struct_map.set("ID", _new_uuid())
    struct_map.set("TYPE", "PHYSICAL")
    struct_map.set("LABEL", "CSIP")

    root_div = etree.SubElement(struct_map, "div")
    root_div.set("ID", _new_uuid())
    # CSIP: the root div's LABEL is the package identifier, the same value
    # as mets/@OBJID. Both are replaced together by set_package_name.
    root_div.set("LABEL", objid)

    # Metadata div (always present)
    metadata_div = etree.SubElement(root_div, "div")
    metadata_div.set("ID", _new_uuid())
    metadata_div.set("LABEL", "Metadata")
    if amd_ids:
        metadata_div.set("ADMID", " ".join(amd_ids))
    if dmd_ids:
        metadata_div.set("DMDID", " ".join(dmd_ids))

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
        # No ADMID here: the digiprovMD entries describe the whole package,
        # and are referenced from the package-level Metadata div instead.

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


def set_package_name(tree: etree._ElementTree, name: str) -> None:
    """Write the package name into the METS as its package identifier.

    CSIP requires mets/@OBJID to be the package identifier, which is the
    name of the package root folder, or of the zip without ".zip", and
    the root structMap div's LABEL to be that same value. The name is
    only known once create_package has claimed it, "_1" suffix included,
    so build_mets writes a provisional IP_<uuid> and create_package calls
    this with the final name before METS.xml is written.

    Args:
        tree: A document from build_mets. Updated in place.
        name: The package name, for example "IP_20260927T101010_1".

    Raises:
        ValueError: The tree has no structMap root div, so it was not
            built by build_mets. Nothing is changed then.
    """
    root = tree.getroot()
    root_div = root.find("structMap/div")
    if root_div is None:
        raise ValueError("METS has no structMap root div to carry the package name")
    root.set("OBJID", name)
    root_div.set("LABEL", name)
