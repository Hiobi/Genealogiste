"""Disponibilité déclarée des fonds, sans inférer l'existence d'un acte ni une absence hors périmètre."""

from __future__ import annotations

from datetime import date
from urllib.parse import urlsplit

from .normalize.places import DEPARTEMENTS, normalize_place, place_key

ETATS = {'en_ligne', 'hors_ligne', 'annoncee', 'partielle', 'lacune', 'autre_service'}
CHAMPS = {'etat', 'de', 'a', 'anciennete_min', 'communes', 'sauf_communes', 'reference', 'note', 'lien'}


def _url(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme in {'http', 'https'} and bool(parsed.hostname) and not parsed.username
    except ValueError:
        return False


def valid_rule(rule) -> bool:
    if not isinstance(rule, dict) or not set(rule) <= CHAMPS:
        return False
    if not isinstance(rule.get('etat'), str) or rule['etat'] not in ETATS or not _url(rule.get('reference')):
        return False
    for field in ('de', 'a', 'anciennete_min'):
        if field in rule and (type(rule[field]) is not int or rule[field] < (0 if field == 'anciennete_min' else 1)
                              or rule[field] > 9999):
            return False
    if rule.get('de', 1) > rule.get('a', 9999):
        return False
    for field in ('communes', 'sauf_communes'):
        if field in rule and (not isinstance(rule[field], list) or not rule[field]
                              or any(not isinstance(x, str) or not place_key(x) for x in rule[field])):
            return False
    if 'note' in rule and not isinstance(rule['note'], str):
        return False
    return 'lien' not in rule or _url(rule['lien'])


def validate(data, documents: tuple[str, ...]) -> list[str]:
    if not isinstance(data, dict):
        return ['couvertures doit être un objet par type de document']
    errors = []
    for document, rules in data.items():
        if document not in documents or not isinstance(rules, list) or not rules:
            errors.append(f'couvertures.{document} : liste non vide de règles attendue')
        elif any(not valid_rule(rule) for rule in rules):
            errors.append(f'couvertures.{document} : règle invalide (état, période, communes ou référence)')
    return errors


def valid_legacy(value) -> bool:
    if not isinstance(value, dict) or not set(value) <= {'de', 'a', 'note'}:
        return False
    if any(type(value[k]) is not int or not 1 <= value[k] <= 9999 for k in ('de', 'a') if k in value):
        return False
    return value.get('de', 1) <= value.get('a', 9999) and ('note' not in value or isinstance(value['note'], str))


def _location(service: dict, lieu: str) -> tuple[str, str]:
    place = normalize_place(lieu)
    commune = place_key(place.get('commune', ''))
    department = service.get('departement')
    if not department:
        return commune, ''  # ne pas inventer une restriction territoriale pour un service national/autre
    departments = {place_key(name): code for code, name in DEPARTEMENTS.items()}
    raw_commune = place.get('commune', '').strip().upper()
    identified = raw_commune if raw_commune in DEPARTEMENTS else departments.get(commune)
    explicit = place.get('departement_code')
    if (identified and identified != department) or (explicit and explicit != department):
        return '', 'Le lieu et le département du service sont incohérents.'
    if place.get('pays') and place['pays'] != 'France':
        return '', 'Le pays du lieu est hors du périmètre du service départemental.'
    parts = [part.strip() for part in lieu.split(',') if part.strip()]
    if len(parts) == 2:
        tail = place_key(parts[1])
        raw_tail = parts[1].upper()
        tail_department = raw_tail if raw_tail in DEPARTEMENTS else departments.get(tail)
        if tail_department and tail_department != department:
            return '', 'Le lieu et le département du service sont incohérents.'
        if not tail_department and tail not in {'france', 'fr'}:
            return '', 'Précision géographique non reconnue : disponibilité inconnue.'
    if identified or commune in {'france', 'fr'}:
        commune = ''
    return commune, ''


def _period(rule: dict, year: int, today: date) -> bool | None:
    if year < rule.get('de', 1) or year > rule.get('a', 9999):
        return False
    if 'anciennete_min' in rule:
        boundary = today.year - rule['anciennete_min']
        if year > boundary:
            return False
        if year == boundary:
            return None  # jour du registre inconnu : ne pas conclure sur toute l'année frontière
    return True


def _scope(rule: dict, commune: str) -> bool | None:
    if not commune and ('communes' in rule or 'sauf_communes' in rule):
        return None
    if 'communes' in rule and commune not in {place_key(x) for x in rule['communes']}:
        return False
    if commune in {place_key(x) for x in rule.get('sauf_communes', [])}:
        return False
    return True


def evaluate(service: dict | None, document: str, year: int | None, lieu: str = '',
             today: date | None = None) -> dict:
    result = {'en_ligne': None, 'motif': 'Couverture inconnue pour cette demande.', 'regles': [],
              'portee': 'Disponibilité déclarée du fonds ; ne prouve pas l’existence de l’acte recherché.'}
    if not service:
        return result
    if year is None:
        result['motif'] = 'Année non précisée : disponibilité inconnue.'
        return result
    if type(year) is not int or not 1 <= year <= 9999:
        result['motif'] = 'Année invalide : disponibilité inconnue.'
        return result
    commune, location_error = _location(service, lieu)
    if location_error:
        result['motif'] = location_error
        return result
    coverage = service.get('couvertures', {})
    if not isinstance(coverage, dict):
        result['motif'] = 'Couverture invalide : disponibilité inconnue.'
        return result
    if document not in coverage:
        # Anciennes plages : conserver les positifs, ne plus déduire une absence hors de la plage.
        legacy_data = service.get('en_ligne') or {}
        legacy = legacy_data.get(document) if isinstance(legacy_data, dict) else None
        if valid_legacy(legacy) and any(k in legacy for k in ('de', 'a')):
            if legacy.get('de', 1) <= year <= legacy.get('a', 9999):
                result.update(en_ligne=True, motif='Période déclarée par une entrée au format historique.')
        return result
    rules = coverage[document]
    if not isinstance(rules, list) or not rules or any(not valid_rule(r) for r in rules):
        result['motif'] = 'Couverture invalide : disponibilité inconnue.'
        return result
    candidates = []
    uncertain = []
    for rule in rules:
        period = _period(rule, year, today or date.today())
        scope = _scope(rule, commune)
        if period is False or scope is False:
            continue
        priority = 1 if 'communes' in rule else 0
        if period is None or scope is None:
            uncertain.append((priority, rule))
        else:
            candidates.append((priority, rule))
    priority = max((p for p, _ in candidates), default=-1)
    selected = [r for p, r in candidates if p == priority]
    possible = [r for p, r in uncertain if p >= priority]
    result['regles'] = selected + possible
    if possible:
        result['motif'] = 'Commune non précisée ou année à la limite du seuil glissant : disponibilité inconnue.'
        return result
    if not selected:
        return result
    states = {r['etat'] for r in selected}
    if len(states) != 1:
        result['motif'] = 'Règles de couverture contradictoires : disponibilité inconnue.'
        return result
    state = next(iter(states))
    result['etat'] = state
    result['en_ligne'] = {'en_ligne': True, 'hors_ligne': False}.get(state)
    result['motif'] = {
        'en_ligne': 'Accès en ligne déclaré pour ce périmètre.',
        'hors_ligne': 'Indisponibilité en ligne explicitement déclarée pour ce périmètre.',
        'annoncee': 'Période annoncée ; accès précis restant à confirmer.',
        'partielle': 'Couverture partielle : vérifier les collections de la commune.',
        'lacune': 'Lacune signalée : disponibilité de la demande inconnue.',
        'autre_service': 'Consulter le service indiqué : disponibilité locale non établie.',
    }[state]
    return result
