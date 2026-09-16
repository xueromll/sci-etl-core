from __future__ import annotations

from lxml import etree

from sci_etl_core.exceptions import ParsingError


def parse_untrusted_xml(content: bytes, label: str) -> etree._Element:
    """Parse XML from an untrusted source without resolving entities, loading DTDs, or using the network.

    Raises:
        ParsingError: The bytes are not well-formed XML.
    """
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
    try:
        return etree.fromstring(content, parser)
    except etree.XMLSyntaxError as exc:
        raise ParsingError(f"{label} is not well-formed XML: {exc}") from exc


def local_name(element: etree._Element) -> str:
    """Return an element's tag without its namespace, or ``""`` for a comment or processing instruction."""
    if not isinstance(element.tag, str):
        return ""
    return etree.QName(element).localname
