"""Couverture technique constatée, distincte de la disponibilité déclarée des fonds (#145)."""
from __future__ import annotations

from . import couverture_3e, couverture_recensements
from .acces_archives import ecarte_adaptateur_service
from .sources import registres

CAPACITES = ("resolution_ark", "navigation", "telechargement", "recherche", "archivage")


def couverture(service: dict, recette: dict, document: str = "") -> dict:
    """Ne propage jamais une recette de ressource à tous les fonds d'un service."""
    if ecarte_adaptateur_service(service, document):
        # Un accès typé d'un autre éditeur n'hérite ni du routage d'adaptateur ni de la recette.
        service = {k: v for k, v in service.items() if k not in ("resolution_image", "ark_naan", "recette")}
        recette = {}
    reference = service.get("recette") or {}
    fonds = reference.get("document", "inconnu")
    applicable = not document or document == fonds
    adaptateur = (service.get("resolution_image") or {}).get("type") == "visualizer_api" or service.get("ark_naan") == "12148"
    capacites = {c: "inconnu" for c in CAPACITES}
    if adaptateur:
        for c in CAPACITES[:3]:
            capacites[c] = "implemente_non_eprouve"
    formulaires = (service.get("recherche_registres") or {}).get("formulaires") or {}
    # un acte précis exige le formulaire d'état civil (AD25 : tables, matricules et successions seulement, #242)
    recherche = document in ("", "naissance", "mariage", "deces") and (
        service["code"] == "AD59" or ("etat_civil" in formulaires if document else bool(formulaires)))
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
              "Après 0.24.0 : mesurer les références depuis le VPS (#150), éprouver la recherche par commune des services Mnesys (#128, relevé du 2026-11-18) au-delà d'une commune chacun, puis qualifier les autres types de fonds (tables décennales, matricules, enregistrement ; #112). Ces objectifs restent à valider ; les compteurs ci-dessous décrivent uniquement les preuves enregistrées.", "",
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
    try:
        classeur = couverture_3e.referentiel()
        lignes.extend(["## AD59 : classeur 3 E", "",
                       f"Hors des niveaux ci-dessus : le classeur 3 E des AD59 (`ad59_3e.json`, relevé du {classeur['releve_le']}, "
                       f"{classeur['volumes']} volumes, {len(classeur['communes'])} libellés de commune) donne la cote et l'année de mise en ligne "
                       "prévue des registres d'état civil. `archives_registres` le joint (`classeur_3e`) quand la recherche est vide ou qu'un "
                       "volume n'est pas en ligne ; un volume inconnu du classeur n'est pas inexistant. Voir `docs/recherche-registres-ad59.md`.", ""])
    except (OSError, ValueError, KeyError):
        pass
    try:
        etat = couverture_recensements.referentiel()
        lignes.extend(["## AD59 : recensements de population", "",
                       f"Hors des niveaux ci-dessus : l'état de la collection des recensements des AD59 (`ad59_recensements.json`, relevé du {etat['releve_le']}, "
                       f"{etat['volumes']} volumes, {len(etat['communes'])} libellés de commune, {etat['en_ligne']} en ligne, {etat['salle_de_lecture']} en salle de lecture) "
                       "donne la cote et le mode d'accès de chaque millésime. `archives_registres(type_acte=\"REC\")` le joint (`couverture_recensements`) quand la "
                       "recherche est vide ou qu'un recensement n'est qu'en salle de lecture ; un millésime inconnu du référentiel n'est pas inexistant. "
                       "Voir `docs/recensements.md`.", ""])
    except (OSError, ValueError, KeyError):
        pass
    lignes.extend(["## AD59 : registres matricules", "",
                   f"Hors des niveaux ci-dessus : `archives_registres(type_acte=\"RM\")` interroge pour les AD59 les deux formulaires de la série 1 R (relevé du {registres.RELEVE_RM}) : "
                   f"tables alphabétiques et fiches des états signalétiques ({registres.PERIODE_FICHES_RM} d'après le formulaire), par classe et bureau de recrutement. "
                   "Aucun référentiel local des cotes : la cote vient de la réponse ; un résultat vide ne prouve pas l'absence du registre. "
                   "Navigation et lecture des vues de ces registres non testées. Voir `docs/recherche-registres-ad59.md`.", ""])
    lignes.extend(["## AD59 : tables des successions et fiches décès", "",
                   f"Hors des niveaux ci-dessus : `archives_registres` interroge pour les AD59 le formulaire des tables des successions et absences (`type_acte=\"SUCC\"`, série 3 Q, {registres.PERIODE_SUCC} d'après le service) "
                   f"et celui des fiches décès de l'enregistrement (`type_acte=\"FD\"`, versements W, {registres.PERIODE_FD}), par bureau de l'enregistrement (relevé du {registres.RELEVE_ENREGISTREMENT}). "
                   "Aucun référentiel local des cotes : la cote vient de la réponse ; un résultat vide ne prouve ni l'absence d'un décès ni celle d'une succession. "
                   f"Fiches décès : le service affirme un délai de {registres.DELAI_FD} ans, non vérifié par le plugin ; elles ne sont jamais présentées comme librement communicables. "
                   "Navigation et lecture des vues de ces fonds non testées. Voir `docs/recherche-registres-ad59.md`.", ""])
    lignes.extend(["## AD59 : hypothèques", "",
                   f"Hors des niveaux ci-dessus : `archives_registres(type_acte=\"HYP\")` interroge pour les AD59 les trois formulaires de la sous-série 4 Q (relevé du {registres.RELEVE_HYP}) : "
                   "indicateurs, tables alphabétiques et répertoires des formalités hypothécaires, par bureau des hypothèques (`HYPI`, `HYPT`, `HYPR` pour une seule catégorie). "
                   f"D'après le service : {registres.PERIODE_HYP}. Aucune date dans ces formulaires ; bureau, période et plage alphabétique sont lus dans le titre des volumes, "
                   "et le nom cherché n'est jamais envoyé. Aucun référentiel local des cotes : la cote vient de la réponse ; un résultat vide ne prouve ni l'absence du registre ni celle d'une formalité. "
                   "Navigation et lecture des vues de ces fonds non testées. Voir `docs/recherche-registres-ad59.md`.", ""])
    lignes.extend(["## AD59 : plans du cadastre", "",
                   f"Hors des niveaux ci-dessus : `archives_registres(type_acte=\"CAD\")` interroge pour les AD59 les deux formulaires des plans du cadastre (relevé du {registres.RELEVE_CAD}) : "
                   "cadastre dit du Consulat (cotes P 30) et cadastre dit napoléonien (cotes P 31), par commune, chaque formulaire ayant son vocabulaire. "
                   f"D'après le service : {registres.PERIODE_CAD}. Aucune date dans ces formulaires ; seuls les plans dont la date affichée ne recoupe pas la période demandée sont écartés. "
                   "Plans seulement, non nominatifs : matrices cadastrales et états de sections ne sont pas couverts. Aucun référentiel local des cotes : la cote vient de la réponse ; un résultat vide ne prouve pas qu'aucun plan n'existe. "
                   "Navigation éprouvée sur un seul lot (métadonnées, aucune image) ; planche-contact et lecture des plans non testées. Voir `docs/recherche-registres-ad59.md`.", ""])
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
