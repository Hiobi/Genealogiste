"""Gallica (BnF) : SRU, recherche plein texte dans un document, texte brut, ALTO, IIIF."""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET

from .base import DAY, SourceContext, envelope, error_envelope

SRU = "https://gallica.bnf.fr/SRU"
BASE = "https://gallica.bnf.fr"
NS = {"srw": "http://www.loc.gov/zing/srw/", "dc": "http://purl.org/dc/elements/1.1/",
      "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/"}
TYPES = {"presse": "fascicule", "livre": "monographie", "carte": "carte", "image": "image", "manuscrit": "manuscrit"}


def ark_id(v: str) -> str:
    """'https://gallica.bnf.fr/ark:/12148/bpt6k123/f2.item' -> 'bpt6k123'."""
    m = re.search(r"(?:ark:/12148/)?((?:bpt6k|btv1b|cb)[0-9a-z]+)", v or "")
    if not m:
        raise ValueError(f"Identifiant ARK Gallica non reconnu : {v!r}")
    return m.group(1)


def build_query(texte: str, type_doc: str = "", titre: str = "", debut: str = "", fin: str = "",
                exact: bool = True) -> str:
    q = f'gallica {"adj" if exact else "all"} "{texte.replace(chr(34), "")}"'
    if type_doc:
        q += f' and dc.type all "{TYPES.get(type_doc, type_doc)}"'
    if titre:
        q += f' and dc.title all "{titre}"'
    if debut:
        q += f' and gallicapublication_date>="{debut}"'
    if fin:
        q += f' and gallicapublication_date<="{fin}"'
    return q


def parse_sru(xml_text: str) -> tuple[int, list[dict]]:
    root = ET.fromstring(xml_text)
    total = int(root.findtext("srw:numberOfRecords", "0", NS) or 0)
    out = []
    for rec in root.iterfind(".//srw:record", NS):
        dc = rec.find(".//oai_dc:dc", NS)
        if dc is None:
            continue

        def all_(tag, _dc=dc):
            return [e.text.strip() for e in _dc.findall(f"dc:{tag}", NS) if e.text]

        ident = next((i for i in all_("identifier") if "ark:/12148" in i), "")
        try:
            ark = ark_id(ident)
        except ValueError:
            ark = ""
        titre = " ; ".join(all_("title"))
        date = ", ".join(all_("date"))
        out.append({
            "source": "gallica", "id_externe": ark, "titre": titre, "date": date,
            "type": ", ".join(all_("type")), "editeur": ", ".join(all_("publisher")),
            "url": ident or (f"{BASE}/ark:/12148/{ark}" if ark else ""),
            "iiif_manifest": f"{BASE}/iiif/ark:/12148/{ark}/manifest.json" if ark else "",
            "citation_suggeree": {
                "titre_source": titre, "page": f"{date}, {BASE}/ark:/12148/{ark}" if ark else date,
                "type_source": "originale" if "fascicule" in ", ".join(all_("type")) else "indeterminee",
                "information": "indeterminee", "preuve": "directe", "url": ident,
                "note": "Presse/annuaire : information souvent secondaire ; préciser la page (fN) citée.",
            },
        })
    return total, out


def search(ctx: SourceContext, texte: str, type_doc: str = "", titre: str = "", debut: str = "", fin: str = "",
           exact: bool = True, nombre: int = 20, depart: int = 1, personne: str | None = None) -> dict:
    query = build_query(texte, type_doc, titre, debut, fin, exact)
    params = {"operation": "searchRetrieve", "version": "1.2", "query": query,
              "maximumRecords": str(min(nombre, 50)), "startRecord": str(depart)}
    try:
        xml_text, cached = ctx.http.get(SRU, params=params, ttl=90 * DAY, source="gallica", parse="text")
        total, records = parse_sru(xml_text)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(ctx, "gallica", "sru", {"query": query}, exc, personne)
    return envelope(ctx, "gallica", "sru", {"query": query}, records, total, cached, personne,
                    suite="gallica_recherche_document(ark, texte) pour trouver la page exacte, puis gallica_texte.")


def search_in_document(ctx: SourceContext, ark: str, texte: str) -> dict:
    ark = ark_id(ark)
    params = {"ark": ark, "query": texte}
    try:
        xml_text, cached = ctx.http.get(f"{BASE}/services/ContentSearch", params=params, ttl=90 * DAY,
                                        source="gallica", parse="text")
        root = ET.fromstring(xml_text)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(ctx, "gallica", "contentsearch", params, exc)
    hits = []
    for item in root.iter("item"):
        pid = item.findtext("p_id") or ""
        page = int(pid.split("_")[-1]) if pid.split("_")[-1].isdigit() else None
        content = re.sub(r"<[^>]+>", "", html.unescape(item.findtext("content") or ""))
        hits.append({"source": "gallica", "id_externe": f"{ark}/f{page}", "titre": f"{ark} page {page}",
                     "page": page, "extrait": content.strip()[:500],
                     "url": f"{BASE}/ark:/12148/{ark}/f{page}.item" if page else f"{BASE}/ark:/12148/{ark}",
                     "image": f"{BASE}/iiif/ark:/12148/{ark}/f{page}/full/full/0/native.jpg" if page else ""})
    return envelope(ctx, "gallica", "contentsearch", params, hits, len(hits), cached)


def text(ctx: SourceContext, ark: str, page: int | None = None, max_caracteres: int = 20000) -> dict:
    a = ark_id(ark)
    url = f"{BASE}/ark:/12148/{a}" + (f"/f{page}" if page else "") + ".texteBrut"
    try:
        raw, cached = ctx.http.get(url, ttl=365 * DAY, source="gallica", parse="text")
    except Exception as exc:  # noqa: BLE001
        return error_envelope(ctx, "gallica", "texteBrut", {"ark": a, "page": page}, exc)
    body = re.sub(r"(?is)<(script|style).*?</\1>", "", raw)
    body = re.sub(r"<br\s*/?>|</p>", "\n", body)
    body = html.unescape(re.sub(r"<[^>]+>", "", body))
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    ctx.journal.add("gallica", "texteBrut", {"ark": a, "page": page}, "positif" if body else "negatif",
                    nb_resultats=1 if body else 0, cache=cached, references=[url])
    return {"source": "gallica", "ark": a, "page": page, "url": url, "longueur": len(body),
            "texte": body[:max_caracteres], "tronque": len(body) > max_caracteres,
            "avertissement": "Texte OCR : vérifier toute donnée sur l'image (gallica_iiif) avant de la citer."}


def alto(ctx: SourceContext, ark: str, page: int) -> dict:
    a = ark_id(ark)
    params = {"O": a, "E": "ALTO", "Deb": str(page)}
    try:
        raw, cached = ctx.http.get(f"{BASE}/RequestDigitalElement", params=params, ttl=365 * DAY,
                                   source="gallica", parse="text")
        root = ET.fromstring(raw)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(ctx, "gallica", "alto", params, exc)
    lines = []
    for el in root.iter():
        if el.tag.endswith("TextLine"):
            words = [s.get("CONTENT", "") for s in el if s.tag.endswith("String")]
            confs = [float(s.get("WC")) for s in el if s.tag.endswith("String") and s.get("WC")]
            lines.append({"texte": " ".join(words), "confiance": round(sum(confs) / len(confs), 2) if confs else None,
                          "x": el.get("HPOS"), "y": el.get("VPOS")})
    ctx.journal.add("gallica", "alto", params, "positif" if lines else "negatif", nb_resultats=len(lines), cache=cached)
    return {"source": "gallica", "ark": a, "page": page, "lignes": lines[:2000], "nb_lignes": len(lines)}


def iiif(ark: str, page: int | None = None, region: str = "full", taille: str = "full") -> dict:
    a = ark_id(ark)
    out = {"manifest": f"{BASE}/iiif/ark:/12148/{a}/manifest.json", "visionneuse": f"{BASE}/ark:/12148/{a}"}
    if page:
        out["image"] = f"{BASE}/iiif/ark:/12148/{a}/f{page}/{region}/{taille}/0/native.jpg"
        out["info"] = f"{BASE}/iiif/ark:/12148/{a}/f{page}/info.json"
        out["visionneuse"] = f"{BASE}/ark:/12148/{a}/f{page}.item"
    return out
