"""Construit mcp/src/genealogiste_mcp/referentiels/sites_tiers.json (#181).

Entrées relevées à la main (issue #181, 2026-11-16) + cercles régionaux et départementaux de l'annuaire FFG
(https://www.genefede.eu/associations-federees-par-departements/, JSON de la carte, département du siège).
Aucun accès réseau : la page de l'annuaire est enregistrée au préalable par l'opérateur.

Usage : python3 -I scripts/importer_sites_tiers.py <page FFG enregistrée (.html) ou JSON> <sortie.json>
verifie_le reste vide : seule une vérification humaine le renseigne (docs/sites-tiers.md).
"""
import json
import re
import sys
from urllib.parse import urlsplit

_src = open(sys.argv[1], encoding="utf-8").read()
if _src.lstrip().startswith("["):
    ffg = json.loads(_src)
else:  # page HTML enregistrée : données de la carte dans <script data-ffgmap-data>
    ffg = json.loads(re.search(r"data-ffgmap-data>(\[.*?\])</script>", _src, re.S).group(1))
OUT = sys.argv[2]
R16 = "2026-11-16"
R18 = "2026-11-18"
ISSUE = "https://github.com/Hiobi/Genealogiste/issues/181"
def S(code, nom, url, type_, zone, acces, nature, *, actes=None, periode=None, recherche="", protection="aucune",
      repond=R16, notes="", origine=f"relevé curl/WebFetch du {R16} (#181)", themes=None):
    e = {"code": code, "nom": nom, "url": url, "type": type_, "zone": zone, "acces": acces, "nature": nature}
    if actes:
        e["actes"] = actes
    if periode:
        e["periode"] = periode
    if themes:
        e["themes"] = themes
    if recherche:
        e["recherche"] = recherche
    e["protection"] = protection
    if repond:
        e["site_repond_le"] = repond
    e["verifie_le"] = ""
    e["origine"] = origine
    if notes:
        e["notes"] = notes
    return e
FR = ["FR"]
manuels = [
 S("GENEABANK","GeneaBank","https://www.geneabank.org/frenind.php","releves_benevoles",FR,"mixte","index",
   actes=["BMS","NMD"], recherche="https://gbkcouples.geneabank.org?nom={nom}&nomconjoint=&prenom={prenom}&prenomconjoint=",
   notes="Relevés de dizaines d'associations ; recherche par couple libre, acte payé en points d'association. Index menant à un relevé dérivé."),
 S("FFG-ANNUAIRE","Fédération française de généalogie — associations par département","https://www.genefede.eu/associations-federees-par-departements/","annuaire",FR,"libre","outil",
   notes="152 associations fédérées ; filtres par région, département et thème. Source du peuplement des cercles (département du siège)."),
 S("FFG-BASES","Fédération française de généalogie — bases de données","https://www.genefede.eu/bases-de-donnees/","base_thematique",FR,"libre","index",
   notes="Métiers anciens, villages disparus, GénéaDico, Cavaliers de Napoléon : une page par base."),
 S("RFG-ANNUAIRE","Revue française de généalogie — annuaire","https://www.rfgenealogie.com/annuaire/associations","annuaire",FR,"libre","outil",
   notes="Associations, archives et professionnels. Le filtre GET par département (idd) n'a pas filtré lors du relevé du 2026-11-18 : passer par le formulaire."),
 S("GENEAWIKI-RELEVES","Geneawiki — annuaire des relevés collaboratifs libres et gratuits","https://fr.geneawiki.com/wiki/Annuaire_des_relev%C3%A9s_collaboratifs_libres_et_gratuits","annuaire",FR,"libre","outil",
   protection="cloudflare", notes="Relevés gratuits classés par département (wiki)."),
 S("FRANCEGENWEB","FranceGenWeb","https://www.francegenweb.org/","releves_benevoles",FR,"libre","releve_derive",
   actes=["BMS","NMD","notaires"], protection="captcha", notes="Actes en vrac, Migranet, protestants, notaires, cimetières ; recherche /multibases/index.php avec code anti-robot."),
 S("GENNPDC","GenNPdC — Nord–Pas-de-Calais","https://www.gennpdc.net/","releves_benevoles",["59","62"],"inscription_gratuite","releve_derive",
   protection="aucune", notes="Forum d'entraide et relevés ; accès à confirmer (inscription au forum). Réponse partielle au relevé."),
 S("CGF-RECIF","Centre généalogique du Finistère — RECIF","https://recif.cgf.bzh/cgf.php?ctxt=0","cercle_departemental",["29"],"mixte","index",
   actes=["BMS","NMD"], notes="11,9 M d'actes avec connexion ; base hors état civil (victimes de conflits, bagnards, conscrits, douaniers)."),
 S("CGHVY","Cercle généalogique et héraldique de Versailles et des Yvelines","https://www.cgvy.org/","cercle_departemental",["78"],"mixte","releve_derive",
   notes="« Métiers du Château » ouvert à tous, le reste réservé aux adhérents."),
 S("AUBE-GENEALOGIE","Aube Généalogie","https://www.aubegenealogie.com/","cercle_departemental",["10"],"mixte","releve_derive",
   notes="Relevés en accès libre et base « Morts pour la France »."),
 S("EGMT","Entraide généalogique du Midi toulousain","https://egmt.org/","cercle_departemental",["31","81"],"adhesion","releve_derive",
   notes="Relevés via GeneaBank."),
 S("CG-SAINTONGE","Cercle généalogique de Saintonge","https://www.cgsaintonge.fr/","cercle_departemental",["17"],"adhesion","releve_derive",
   actes=["BMS","contrats","notaires"], notes="Contrats de mariage, notaires ; relevés via GeneaBank."),
 S("CGHAV","Cercle généalogique et héraldique de l'Auvergne et du Velay","https://www.cghav.org/","cercle_departemental",["15","43","63"],"mixte","releve_derive"),
 S("GENEACAUX","Cercle généalogique du Pays de Caux","https://www.geneacaux.fr/","cercle_departemental",["76"],"adhesion","releve_derive",
   notes="Plus de 4 M d'actes."),
 S("CGPA64","Cercle généalogique des Pyrénées-Atlantiques","https://www.cgpa64.fr/","cercle_departemental",["64"],"a_determiner","releve_derive",
   protection="captcha", notes="reCAPTCHA au relevé."),
 S("CG-AVEYRON","Cercle généalogique de l'Aveyron","https://www.genealogie-aveyron.fr/","cercle_departemental",["12"],"a_determiner","releve_derive"),
 S("CG22","Centre généalogique des Côtes-d'Armor","https://www.genealogie22.com/","cercle_departemental",["22"],"a_determiner","releve_derive",
   protection="cloudflare", notes="Rôles d'équipage."),
 S("CGCSHB","Cercle généalogique de Conflans — batellerie","https://gw.geneanet.org/cgcshb","arbre_collaboratif",["78"],"libre","releve_derive",
   themes=["mariniers"], notes="Arbre commun (GeneWeb) ; aucune base de mariniers trouvée en ligne. Arbre = piste."),
 S("FICHIER-ORIGINE","Fichier Origine","https://www.fichierorigine.com/fr/","base_thematique",["FR","CA"],"libre","releve_derive",
   periode={"a":1865}, themes=["emigration"], notes="Émigrants de France vers le Québec avant 1865."),
 S("PRDH","Programme de recherche en démographie historique (PRDH)","https://www.prdh-igd.com/","base_thematique",["CA"],"mixte","releve_derive",
   themes=["emigration"], notes="Démographie canadienne-française ; détail payant."),
 S("REFUGE-HUGUENOT","Refuge huguenot","https://www.refuge-huguenot.fr/","base_thematique",FR,"libre","index",
   periode={"de":1685,"a":1700}, themes=["protestants"], notes="Refuge protestant 1685-~1700 (~135 000 notices)."),
 S("SHPF","Société de l'histoire du protestantisme français","https://www.shpf.fr/","base_thematique",FR,"a_determiner","notice",
   themes=["protestants"]),
 S("GENEALOJ","Cercle de généalogie juive","https://www.genealoj.org/fr","base_thematique",FR,"a_determiner","index",
   themes=["juifs"], notes="BECANE, BIKETTE, REGIE, dénombrement d'Alsace 1784."),
 S("GENAMI","GenAmi","https://www.genami.org/","base_thematique",FR,"mixte","notice",themes=["juifs"],notes="Guides de recherche."),
 S("FMD-LIVRE-MEMORIAL","Fondation pour la mémoire de la déportation — Livre-Mémorial","https://www.bddm.org/liv/recherche.php","base_thematique",FR,"libre","index",
   periode={"de":1940,"a":1945}, themes=["deportes","ww2"], notes="Déportés partis de France 1940-1945."),
 S("MEMORIAL-SHOAH","Mémorial de la Shoah — ressources","https://ressources.memorialdelashoah.org/","base_thematique",FR,"a_determiner","index",
   periode={"de":1939,"a":1945}, themes=["juifs","deportes","ww2"], notes="Victimes, documents."),
 S("MAITRON","Maitron","https://maitron.fr/","base_thematique",FR,"libre","notice",
   themes=["ww2","mouvement_ouvrier"], notes="~226 000 notices biographiques, dont les fusillés 1940-1944."),
 S("FRANCAIS-LIBRES","Français libres","https://www.francaislibres.net/","base_thematique",FR,"libre","notice",
   periode={"de":1940,"a":1945}, themes=["ww2","militaires"], notes="Forces françaises libres 1940-1945."),
 S("CICR-14-18","CICR — prisonniers de la Première Guerre mondiale","https://grandeguerre.icrc.org/fr","base_thematique",["FR","INT"],"libre","image",
   periode={"de":1914,"a":1918}, themes=["ww1","prisonniers"], notes="~5 M de fiches."),
 S("MEMORIALGENWEB","MemorialGenWeb","https://www.memorialgenweb.org/","cimetieres_monuments",FR,"libre","releve_derive",
   protection="captcha", themes=["monuments_aux_morts"], notes="Relevés et photos des monuments aux morts."),
 S("LANDRU","Landru Cimetières","https://www.landrucimetieres.fr/","cimetieres_monuments",FR,"libre","notice",
   recherche="https://www.landrucimetieres.fr/spip/spip.php?page=recherche&recherche={nom}",
   notes="Tombes de personnalités."),
 S("LIBRA-MEMORIA","Libra Memoria","https://www.libramemoria.com/","cimetieres_monuments",FR,"a_determiner","notice",
   protection="captcha", themes=["avis_deces"], notes="Avis de décès récents : personnes vivantes possibles dans l'entourage. Aucune recherche automatique ; consultation par l'utilisateur seulement."),
 S("ROGLO","Roglo","https://roglo.eu/roglo","arbre_collaboratif",FR,"libre","releve_derive",
   protection="cloudflare", notes="Arbre collaboratif : piste à confirmer par l'acte. Cloudflare Turnstile."),
 # Seconde Guerre mondiale, fonds étrangers et mémoriaux (#131, relevé HTTP du 2026-11-18)
 S("AROLSEN","Arolsen Archives — collections en ligne","https://collections.arolsen-archives.org/","base_thematique",["INT"],"libre","image",
   periode={"de":1933,"a":1950}, themes=["ww2","deportes","prisonniers","travail_force"], repond=R18,
   origine=f"relevé HTTP du {R18} (#131)",
   notes="Ex-Service international de recherches (ITS) : camps, persécutés, travailleurs forcés, personnes déplacées. Recherche nominative dans le navigateur ; demande de recherche gratuite possible auprès d'Arolsen. Aucune API publique documentée relevée."),
 S("BUNDESARCHIV-INVENIO","Bundesarchiv — invenio (recherche dans les fonds)","https://invenio.bundesarchiv.de/","base_thematique",["INT"],"inscription_gratuite","index",
   periode={"de":1933,"a":1945}, themes=["ww2","wehrmacht","nsdap"], repond=R18, origine=f"relevé HTTP du {R18} (#131)",
   notes="Inventaires des archives fédérales allemandes (dont fichier central du NSDAP, R 9361). Les dossiers de la Wehrmacht (ex-WASt, Deutsche Dienststelle) se demandent au Bundesarchiv par formulaire ; pas d'automatisation."),
 S("VOLKSBUND","Volksbund — recherche de sépultures","https://www.volksbund.de/erinnern-gedenken/graebersuche-online","cimetieres_monuments",["INT"],"libre","index",
   periode={"de":1914,"a":1945}, themes=["ww1","ww2","wehrmacht","sepultures"], repond=R18, origine=f"relevé HTTP du {R18} (#131)",
   notes="Sépultures de soldats allemands (dont incorporés de force d'Alsace-Moselle) ; graphies allemandes à essayer (variantes_noms)."),
 S("USHMM-HSV","USHMM — ressources sur les survivants et victimes de la Shoah","https://www.ushmm.org/remember/resources-holocaust-survivors-victims","base_thematique",["INT"],"libre","index",
   periode={"de":1933,"a":1950}, themes=["ww2","juifs","deportes"], repond=R18, origine=f"relevé HTTP du {R18} (#131)",
   notes="Base des survivants et victimes (HSV), listes et documents ; en anglais."),
 S("MUSEE-RESISTANCE","Musée de la Résistance en ligne","https://www.museedelaresistanceenligne.org/","base_thematique",FR,"libre","notice",
   periode={"de":1940,"a":1945}, themes=["ww2","resistants"], repond=R18, origine=f"relevé HTTP du {R18} (#131)",
   notes="Notices, documents et témoignages sur la Résistance ; contexte, pas une base nominative exhaustive."),
 S("DICOTOPO","DicoTopo (CTHS)","https://dicotopo.cths.fr/","lieux",FR,"libre","outil",
   notes="Dictionnaires topographiques, lieux-dits disparus ; application JavaScript, pas de recherche GET simple observée."),
 S("REMONTER-LE-TEMPS","Remonter le temps (IGN)","https://remonterletemps.ign.fr/","lieux",FR,"libre","outil",
   notes="Cartes de Cassini et d'état-major, photographies aériennes anciennes."),
 S("CASSINI-EHESS","Des villages de Cassini aux communes d'aujourd'hui (EHESS)","http://cassini.ehess.fr/","lieux",FR,"libre","outil",
   periode={"de":1801,"a":2001}, repond="", notes="Communes de 1801 à 2001. Délai dépassé au relevé du 2026-11-16 : à revoir."),
]
def host(u):
    return (urlsplit(u).hostname or "").removeprefix("www.")
seen = {host(e["url"]) for e in manuels} | {"cgf.bzh"}  # RECIF = site du CGF
ffg_entries = []
for a in ffg:
    if "regionales-et-departementales" not in a["ts"]:
        continue
    zone = []
    for d in a["d"]:
        c = d.split(" - ")[0].strip()
        zone += ["2A","2B"] if c == "Corse" else [c]
    if not zone:
        continue
    url = re.sub(r"^(https?):/(?!/)", r"\1://", a["s"]) or a["u"]  # « http:/cgpc06.org » dans l annuaire
    h = host(url)
    if a["s"] and h in seen:
        continue
    seen.add(h)
    note = "Département du siège selon l'annuaire FFG : la zone couverte peut être plus large ou plus étroite."
    if not a["s"]:
        note += " Aucun site propre dans l'annuaire : lien vers la fiche FFG."
    e = S(f"FFG-{a['id']}", a["n"].replace("’","'"), url, "cercle_departemental", zone, "a_determiner", "releve_derive",
          repond="", origine=f"annuaire FFG ({'fiche ' + a['u']}), relevé du {R18}", notes=note)
    e["fiche_annuaire"] = a["u"]
    ffg_entries.append(e)
ffg_entries.sort(key=lambda e: (e["zone"][0].zfill(3), e["nom"]))
doc = {"_description": (
  "Sites tiers de généalogie (associations, relevés bénévoles, bases thématiques, annuaires, lieux, fonds "
  "étrangers) : PAS les archives publiques françaises (voir archives_fr.json). Un relevé est une source dérivée : il donne une piste "
  "et oblige à remonter à l'acte original. verifie_le reste vide tant qu'aucun contrôle humain n'a eu lieu ; "
  "protection et site_repond_le valent pour un client automatisé à la date du relevé. Format : docs/sites-tiers.md (#181)."),
  "sites": manuels + ffg_entries}
open(OUT,"w",encoding="utf-8").write(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
print(len(manuels), len(ffg_entries))
