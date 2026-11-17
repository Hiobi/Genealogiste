"""Couverture technique constatée, distincte de la disponibilité déclarée des fonds (#145)."""
from __future__ import annotations

CAPACITES = ("resolution_ark", "navigation", "telechargement", "recherche", "archivage")


def couverture(service: dict, recette: dict, document: str = "") -> dict:
    """Ne propage jamais une recette de ressource à tous les fonds d'un service."""
    reference = service.get("recette") or {}
    fonds = reference.get("document", "inconnu")
    applicable = not document or document == fonds
    adaptateur = (service.get("resolution_image") or {}).get("type") == "visualizer_api" or service.get("ark_naan") == "12148"
    capacites = {c: "inconnu" for c in CAPACITES}
    if adaptateur:
        for c in CAPACITES[:3]:
            capacites[c] = "implemente_non_eprouve"
    recherche = service["code"] == "AD59" and document in ("", "naissance", "mariage", "deces")
    if recherche:
        capacites["recherche"] = "implemente_non_eprouve"
    mesures = dict(recette.get("mesures") or {})
    if recette.get("resultat") and not mesures:
        mesures["inconnu"] = {
            "verdict": {"ok": "oui", "protection": "defi", "echec": "echec"}.get(recette["resultat"], "inconnu"),
            "date_mesure": recette.get("dernier_essai"), "detail": recette.get("detail", ""),
        }
    niveau = 4 if recherche else 3 if adaptateur else 0
    qualifiees = [env for env, m in mesures.items() if env in ("local", "ci", "vps")
                  and m.get("verdict") == "oui" and m.get("date_mesure") and m.get("revision")
                  and m.get("reference") == reference]
    pertinentes = [m for m in mesures.values() if m.get("reference") == reference]
    resultat = None
    if pertinentes:
        derniere = max(pertinentes, key=lambda m: m.get("date_mesure") or "")
        resultat = {"oui": "ok", "defi": "protection", "echec": "echec"}.get(derniere.get("verdict"))
    elif not any(m.get("reference") for m in mesures.values()):
        resultat = recette.get("resultat")  # historique, environnement/révision inconnus
    if applicable and reference and resultat == "ok":
        for c in CAPACITES[:3]:
            capacites[c] = "teste"
        if qualifiees:
            niveau = 5
    elif applicable and reference and resultat in ("protection", "echec"):
        for c in CAPACITES[:3]:
            capacites[c] = "bloque" if resultat == "protection" else "echec_recette"
    return {"niveau": niveau, "document": document or fonds, "fonds_recette": fonds,
            "capacites": capacites, "reference": reference, "mesures": mesures,
            "environnements_qualifies": qualifiees if applicable else [],
            "recette_applicable": applicable, "chaine_complete": False,
            "limite": "Niveau 5 : contrat ARK/navigation/image sur la référence seulement ; recherche et archivage non validés par ce contrat. Une protection ou un résultat vide ne prouve pas l'absence d'acte."}


def tableau(services: list | tuple, recettes: dict, documents: tuple = ()) -> str:
    lignes = ["# Couverture technique des archives", "",
              "Document généré par `uv --directory mcp run python ../scripts/generer_couverture_archives.py`. Ne pas modifier à la main.", "",
              "## Objectif du prochain lot M2", "",
              "Pour la version cible 0.23.0 : qualifier trois services avec recette ARK/navigation/image qualifiée (AD25, AD39, AD59 ; date, environnement et révision requis), mesurer les quatre références depuis le VPS, puis qualifier une chaîne recherche → navigation → téléchargement → archivage sur AD59. Ces objectifs restent à valider ; les compteurs ci-dessous décrivent uniquement les preuves enregistrées.", "",
              "Les niveaux 0 à 4 indiquent la capacité implémentée la plus avancée : 0 lien, 1 ARK, 2 navigation, 3 image, 4 recherche. Le niveau 5 désigne une recette de contrat réussie sur une référence avec date, environnement identifié et révision testée ; il ne garantit ni la recherche ni l'archivage. Les niveaux ne forment pas une chaîne cumulative.", "",
              "Un fonds inconnu reste inconnu : aucune recette n'est extrapolée aux autres types. Les mesures anciennes sans environnement restent « inconnu ». Une réussite locale ne qualifie pas le VPS. Consulter les dates et refaire les recettes avant usage ; une ancienne réussite ne garantit pas l'accès actuel.", "",
              "| Service | Fonds testé | Niveau | Recherche | Navigation | Image | Archivage | Mesures (environnement : verdict, date) |", "|---|---|---:|---|---|---|---|---|"]
    comptes = 0
    for s in services:
        c = couverture(s, recettes.get(s["code"]) or {})
        comptes += c["niveau"] == 5
        mesures = "; ".join(f"{env} : {m.get('verdict', 'inconnu')}, {m.get('date_mesure') or 'date inconnue'}" for env, m in sorted(c["mesures"].items())) or "inconnu"
        caps = c["capacites"]
        cellules = [s["code"], c["fonds_recette"], str(c["niveau"]), *[caps[k] for k in ("recherche", "navigation", "telechargement", "archivage")], mesures]
        lignes.append("| " + " | ".join(str(v).replace("|", "\\|").replace("\n", " ") for v in cellules) + " |")
    lignes.extend(["", f"Total : {len(services)} services ; {comptes} recettes de référence qualifiées (niveau 5).", "",
                   "Les URL et pages de référence sont dans `archives_fr.json` ; les verdicts et détails d'échec dans `recettes_archives.json`. `archives_service` expose les mêmes informations sous `couverture_technique`, avec les capacités et mesures séparées.", ""])
    if documents:
        lignes.extend(["## Niveaux par type de document", "",
                       "Chaque cellule reprend le niveau de `archives_service(document=...)`. Une recette dont le fonds n'est pas renseigné ne qualifie aucune de ces colonnes. Les niveaux 0–4 sont des capacités implémentées, toujours à éprouver sur le fonds demandé.", "",
                       "| Service | " + " | ".join(documents) + " |",
                       "|---|" + "---:|" * len(documents)])
        for service in services:
            valeurs = [str(couverture(service, recettes.get(service["code"]) or {}, doc)["niveau"]) for doc in documents]
            lignes.append("| " + service["code"] + " | " + " | ".join(valeurs) + " |")
        lignes.append("")
    return "\n".join(lignes)
