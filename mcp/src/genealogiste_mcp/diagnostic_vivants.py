"""Contrôles « vivants » du diagnostic en mode gramps (#264) : comptes et ``gramps_id`` seulement, jamais un nom.

- ``gramps_vivants`` : personnes présumées vivantes non privées alors que l'instance est exposée à un compte Invité
  (rôle 0, qui ne voit pas le privé) ou à l'inscription libre ; « non vérifiable » quand l'API ne le dit pas ;
- ``gramps_prive_a_retirer`` : privés posés par Genealogiste pour des personnes qui ne sont plus présumées vivantes ;
- ``gramps_regle_vivants`` : divergence entre la règle du plugin (moins de 100 ans sans décès, ``vivant`` forcé) et
  le calcul de Gramps (``GET /api/living/<handle>``, ``probably_alive``), sur un échantillon borné de la zone
  d'incertitude.
"""

from __future__ import annotations

from datetime import date

PLAFOND_REQUETES = 30  # requêtes /api/living/ au plus par diagnostic
PAUSE = 0.1  # secondes entre deux requêtes
FENETRE = (85, 125)  # zone d'incertitude : naissance au plus tard il y a 85 à 125 ans, sans décès
REGLE_PLUGIN = 100  # privacy.LIVING_YEARS
REMEDE_PROTEGER = ("gramps_proteger_vivants prépare le marquage privé des vivants et de leurs données propres "
                   "(diff, accord explicite, annulable). Ou fermer l'accès : aucun compte Invité, inscription libre "
                   "fermée (REGISTRATION_DISABLED=True).")


def _ctl(controle: str, etat: str, detail: str = "", remede: str = "", **extra) -> dict:
    out = {"controle": controle, "etat": etat, "detail": detail}
    if remede:
        out["remede"] = remede
    out.update(extra)
    return out


def _motif(exc: BaseException) -> str:
    return (str(exc) or type(exc).__name__)[:200]


def comptes_invites(a) -> int | None:
    """Comptes de rôle Invité (0) de l'arbre : ``GET /api/users/`` (droit ViewOtherUser, rôle Owner). None : non
    lisible avec ce compte (Editor : 403), ou réponse inattendue. Aucun nom de compte n'est gardé."""
    try:
        r = a.gramps().request("GET", "/users/")
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, list):
        return None
    return sum(1 for u in data if isinstance(u, dict) and u.get("role") == 0)


def non_lance(a, inscription: bool | None) -> list[dict]:
    """Diagnostic par défaut : contrôle des vivants NON lancé (ni lecture de l'arbre, ni requête /api/living/), une
    ligne d'information. Seule exception, gratuite : inscription libre ouverte (lue par ``gramps_reglages``) et
    ``GENEALOGISTE_GRAMPS_PRIVE_VIVANTS=off`` : ``attention`` avec la recommandation."""
    if a.config.backend != "gramps":
        return []
    cout = (f"diagnostic(vivants=true) le lance : lecture complète de l'arbre et au plus {PLAFOND_REQUETES} requêtes "
            "/api/living/")
    if inscription and getattr(a.config, "gramps_prive_vivants", "off") == "off":
        return [_ctl("gramps_vivants", "attention",
                     "contrôle des vivants non lancé ; l'inscription libre est ouverte et "
                     "GENEALOGISTE_GRAMPS_PRIVE_VIVANTS=off : les vivants non privés sont lisibles d'un compte Invité",
                     f"Lancer {cout} ; ou préparer leur protection : gramps_proteger_vivants (proposition, accord "
                     "explicite).", lance=False)]
    return [_ctl("gramps_vivants", "ok", f"contrôle des vivants non lancé ({cout})", lance=False)]


def controles(a, inscription: bool | None) -> list[dict]:
    if a.config.backend != "gramps":
        return []
    try:
        etat = a.backend.etat_vivants()
    except Exception as exc:  # noqa: BLE001
        return [_ctl("gramps_vivants", "attention", f"vivants non vérifiés : {_motif(exc)}",
                     "Relancer le diagnostic une fois l'arbre Gramps Web lisible.")]
    out = [_exposition(a, etat, inscription)]
    if etat["a_retirer"]:
        out.append(_ctl("gramps_prive_a_retirer", "attention",
                        f"{len(etat['a_retirer'])} personne(s) marquée(s) privée(s) par Genealogiste ne sont plus "
                        f"présumées vivantes ({etat['objets_a_retirer']} objet(s))",
                        "gramps_proteger_vivants propose le retrait (accord explicite ; rien n'est retiré "
                        "automatiquement).", personnes=etat["a_retirer"]))
    out.append(regle(a))
    return out


def _exposition(a, etat: dict, inscription: bool | None) -> dict:
    n = len(etat["vivants_non_prives"])
    invites = comptes_invites(a)
    valeurs = {"vivants": etat["vivants"], "vivants_non_prives": n, "comptes_invites": invites,
               "inscription_libre": inscription}
    if n == 0:
        return _ctl("gramps_vivants", "ok", f"{etat['vivants']} personne(s) présumée(s) vivante(s), toutes privées",
                    valeurs=valeurs)
    causes = []
    if invites:
        causes.append(f"{invites} compte(s) Invité (rôle 0)")
    if inscription:
        causes.append("inscription libre ouverte")
    if causes:
        return _ctl("gramps_vivants", "attention",
                    f"{n} personne(s) présumée(s) vivante(s) non privée(s) alors que l'instance est exposée : "
                    f"{', '.join(causes)} (un Invité voit tout ce qui n'est pas privé)", REMEDE_PROTEGER,
                    valeurs=valeurs)
    inconnu = []
    if invites is None:
        inconnu.append("comptes Invité non vérifiables (liste des comptes : rôle Owner)")
    if inscription is None:
        inconnu.append("inscription libre non vérifiable (API < 3.26.0 ou illisible)")
    if inconnu:
        return _ctl("gramps_vivants", "attention",
                    f"{n} personne(s) présumée(s) vivante(s) non privée(s) ; exposition non vérifiable : "
                    f"{' ; '.join(inconnu)}", "Vérifier dans Gramps Web (Administration, utilisateurs) qu'aucun "
                    "compte n'a le rôle Invité et que l'inscription est fermée ; sinon " + REMEDE_PROTEGER,
                    valeurs=valeurs)
    return _ctl("gramps_vivants", "ok", f"{n} personne(s) présumée(s) vivante(s) non privée(s) ; aucun compte "
                "Invité, inscription fermée : rien n'est exposé à un Invité", valeurs=valeurs)


def candidats(tree, annee: int | None = None) -> list[tuple[int, str]]:
    """Personnes où la règle du plugin et celle de Gramps peuvent diverger, par priorité : 0 statut forcé
    (``vivant`` Y/N, ignoré par Gramps) ou décès réfuté (ignoré par le plugin, lu par Gramps) ; 1 sans décès,
    naissance au plus tard estimée dans la fenêtre autour des seuils (100 ans pour le plugin, 110 par défaut pour
    Gramps) ; 2 sans aucune date (présumée vivante par le plugin ; Gramps peut conclure d'après les proches)."""
    from . import privacy

    annee = annee or date.today().year
    out = []
    for pid, p in sorted(tree.personnes.items()):
        st = privacy.is_living(tree, p)
        if p.vivant or any("réfuté" in c for c in st.get("contradictions", [])):
            out.append((0, pid))
        elif "naissance_estimee" in st and annee - FENETRE[1] <= st["naissance_estimee"] <= annee - FENETRE[0]:
            out.append((1, pid))
        elif st["vivant"] and "naissance_estimee" not in st:
            out.append((2, pid))
    return sorted(out)


def regle(a, plafond: int = PLAFOND_REQUETES) -> dict:
    """Divergences plugin / Gramps sur un échantillon borné (``plafond`` requêtes, pause entre deux). Une divergence
    est réinterrogée avec ``max_age_probably_alive=100`` : « seuil » si Gramps rejoint alors le plugin (seul l'âge
    maximal diffère), « méthode » sinon (statut forcé, proches, événements pris en compte)."""
    from . import privacy

    try:
        tree = a.tree()
        db = a.backend.snapshot(fresh=False)
    except Exception as exc:  # noqa: BLE001
        return _ctl("gramps_regle_vivants", "attention", f"règles non comparées : {_motif(exc)}")
    gh = {o.get("gramps_id"): h for h, o in db.all("Person").items()}
    liste = [(prio, pid) for prio, pid in candidats(tree) if pid in gh]
    client = a.gramps()
    requetes, examinees = 0, 0
    plugin_seul: list[str] = []
    gramps_seul: list[str] = []
    causes: dict[str, str] = {}
    try:
        for _, pid in liste:
            if requetes >= plafond:
                break
            if requetes:
                client.sleep(PAUSE)
            g = client.living(gh[pid])
            requetes += 1
            if g is None:
                continue
            examinees += 1
            v = privacy.is_living(tree, tree.personnes[pid])["vivant"]
            if v == g:
                continue
            (plugin_seul if v else gramps_seul).append(pid)
            if requetes < plafond:
                client.sleep(PAUSE)
                g100 = client.living(gh[pid], max_age_probably_alive=REGLE_PLUGIN)
                requetes += 1
                causes[pid] = "seuil" if g100 == v else "méthode"
    except Exception as exc:  # noqa: BLE001
        return _ctl("gramps_regle_vivants", "attention", f"calcul de Gramps illisible : {_motif(exc)}",
                    "Relancer le diagnostic ; /api/living/<handle> existe dans toutes les versions testées.")
    extra = {"zone_incertitude": len(liste), "examinees": examinees, "non_examinees": len(liste) - examinees,
             "requetes": requetes, "plafond": plafond, "plugin_vivant_gramps_non": plugin_seul,
             "gramps_vivant_plugin_non": gramps_seul, "cause": causes,
             "parametres_gramps": "réglages de Gramps (max-age-prob-alive, défaut 110 ans), puis 100 pour une "
                                  "divergence"}
    detail = (f"{examinees} personne(s) examinée(s) sur {len(liste)} dans la zone d'incertitude ({requetes} "
              f"requête(s), plafond {plafond}) ; vivant pour le plugin seul : {len(plugin_seul)} ; pour Gramps "
              f"seul : {len(gramps_seul)}")
    if not liste:
        return _ctl("gramps_regle_vivants", "ok", "aucune personne dans la zone d'incertitude (statut forcé, "
                    "décès réfuté, naissance proche des seuils, aucune date)", **extra)
    if plugin_seul or gramps_seul:
        return _ctl("gramps_regle_vivants", "attention", detail,
                    "Les deux règles ne masquent pas les mêmes personnes. Le plugin protège selon sa règle "
                    "(arbre_vivant ; exports, notes, garde réseau, gramps_proteger_vivants) ; Gramps applique la sienne "
                    "à ses exports et rapports « vivants ». Aligner Gramps Desktop (Préférences > Limites, « Espérance "
                    "de vie maximale » = 100 ; non réglable par l'API de Gramps Web) ou forcer le statut (marquer_vivant) ; docs/gramps-web.md, « Vivants et "
                    "privé ».", **extra)
    return _ctl("gramps_regle_vivants", "ok", detail, **extra)
