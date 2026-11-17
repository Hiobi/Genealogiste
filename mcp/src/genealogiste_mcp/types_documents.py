"""Vocabulaire commun des documents français, aliases et règles indicatives (#129).

Les délais historiques sont conservés ; une règle indéterminée reste explicite.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class TypeDocument:
    libelle: str
    aliases: tuple[str, ...]
    serie: str
    regle: tuple[int | None, str, str]
    catalogue: bool = True


TYPES_DOCUMENTS = {
    'naissance': TypeDocument('naissance', (), 'série E / sous-série 4 E ou E-dépôt (collection du greffe) ; mairie pour la collection communale', (75, 'acte', 'Registres de naissance : 75 ans après la clôture du registre (art. L213-2 Code du patrimoine).'), True),
    'mariage': TypeDocument('mariage', (), 'série E / sous-série 4 E ou E-dépôt (collection du greffe) ; mairie pour la collection communale', (75, 'acte', 'Registres de mariage : 75 ans après la clôture du registre.'), True),
    'deces': TypeDocument('deces', (), 'série E / sous-série 4 E ou E-dépôt (collection du greffe) ; mairie pour la collection communale', (0, 'acte', 'Actes de décès : communicables immédiatement.'), True),
    'tables_decennales': TypeDocument('tables decennales', (), "série E / 4 E (souvent en ligne avec l'état civil), une table par commune et par décennie depuis 1792", (75, 'acte', "Suivent en pratique le régime des actes qu'elles indexent : vérifier auprès du service."), True),
    'recensement': TypeDocument('recensement', ('recensements',), 'série M, sous-série 6 M (listes nominatives quinquennales depuis 1836)', (75, 'acte', 'Listes nominatives : 75 ans (secret statistique).'), True),
    'notaire': TypeDocument('notaire', ('notaires',), "série E, sous-série 3 E (minutes notariales, par étude) — répertoires pour localiser l'acte", (75, 'acte', "Minutes et répertoires notariaux : 75 ans à compter de la date de l'acte."), True),
    'matricule': TypeDocument('matricule', ('matricules',), 'série R, sous-série 1 R (registres matricules, classes 1867 et suivantes ; bureau de recrutement)', (120, 'naissance', 'Registres matricules (données médicales) : 120 ans après la naissance ou 25 ans après le décès ; en pratique mis en ligne par classes anciennes.'), True),
    'cadastre': TypeDocument('cadastre', (), 'série P, sous-série 3 P (cadastre napoléonien : plans, états de sections, matrices)', (0, 'acte', 'Cadastre : communicable immédiatement.'), True),
    'paroissiaux': TypeDocument('paroissiaux', ('paroissial',), 'registres BMS : série E / 4 E (collection du greffe) ou G (clergé séculier), parfois GG en dépôt communal', (None, 'document', 'Préciser la période et le statut public ou privé du registre : les conditions des archives paroissiales ou diocésaines peuvent dépendre du déposant.'), True),
    'enregistrement': TypeDocument('enregistrement', (), "série Q, sous-série 3 Q (bureaux de l'enregistrement : tables des successions et absences, mutations par décès)", (None, 'document', 'Préciser le document : tables des successions et déclarations de succession ont des régimes distincts ; consulter le service.'), True),
    'hypotheques': TypeDocument('hypotheques', (), 'série Q, sous-série 4 Q (conservation des hypothèques : transcriptions, inscriptions)', (0, 'acte', 'Publicité foncière : en principe communicable ; vérifier les délais propres au service.'), True),
    'judiciaire': TypeDocument('judiciaire', ('justice',), 'série U (tribunaux civils, justices de paix : tutelles, émancipations, actes de notoriété)', (75, 'acte', 'Dossiers judiciaires : 75 ans (100 ans si mineurs concernés).'), True),
    'insinuation': TypeDocument('insinuation', ('insinuations',), 'série C (contrôle des actes, insinuations, centième denier — avant 1790)', (None, 'document', 'Préciser le fonds et les conditions de consultation auprès du service.'), True),
    'medical': TypeDocument('medical', (), '', (120, 'naissance', 'Secret médical : 120 ans après la naissance ou 25 ans après le décès.'), False),
    'vie_privee': TypeDocument('vie privee', (), '', (50, 'acte', 'Documents portant atteinte à la vie privée (ex. enregistrement, successions) : 50 ans.'), False),
    'etat_civil': TypeDocument('etat civil', (), 'série E / sous-série 4 E ou E-dépôt (collection du greffe) ; mairie pour la collection communale', (None, 'document', 'Préciser naissance, mariage ou deces : les délais diffèrent.'), False),
}

ALIASES = {alias: key for key, value in TYPES_DOCUMENTS.items() for alias in value.aliases}
DOCUMENTS = tuple(key for key, value in TYPES_DOCUMENTS.items() if value.catalogue)
RULES = {key: value.regle for key, value in TYPES_DOCUMENTS.items()}
SERIES = {key: value.serie for key, value in TYPES_DOCUMENTS.items() if value.serie}
SERIES.update({alias: SERIES[key] for alias, key in ALIASES.items() if key in SERIES})


def normaliser(document: str) -> str:
    texte = unicodedata.normalize("NFKD", document.strip().lower())
    key = "".join(c for c in texte if not unicodedata.combining(c)).replace(" ", "_")
    return ALIASES.get(key, key)
