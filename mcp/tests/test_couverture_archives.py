"""Couvertures synthétiques : périmètre, exceptions, lacunes, dates et compatibilité (#93)."""

from datetime import date

import pytest

from genealogiste_mcp import archives, server

REF = 'https://archives.example/couverture'


def rule(etat='en_ligne', **kw):
    return {'etat': etat, 'reference': REF, **kw}


def service(*rules):
    return {'code': 'X', 'nom': 'Archives fictives', 'type': 'departementales', 'departement': '13',
            'couvertures': {'naissance': list(rules)}}


def test_legacy_range_does_not_prove_absence_outside():
    s = {'en_ligne': {'naissance': {'de': 1800, 'a': 1900}}}
    assert archives.online(s, 'naissance', 1850) is True
    assert archives.online(s, 'naissance', 1799) is None
    assert archives.online(s, 'naissance', 1901) is None


@pytest.mark.parametrize('year,expected', [(1799, None), (1800, True), (1900, True), (1901, None), (None, None)])
def test_precise_period(year, expected):
    assert archives.online(service(rule(de=1800, a=1900)), 'naissance', year) is expected


@pytest.mark.parametrize('etat,expected', [('en_ligne', True), ('hors_ligne', False), ('annoncee', None),
                                         ('partielle', None), ('lacune', None), ('autre_service', None)])
def test_distinct_states(etat, expected):
    assert archives.online(service(rule(etat, de=1800, a=1900)), 'naissance', 1850) is expected


@pytest.mark.parametrize('lieu,expected', [('Arles (13)', True), ('Marseille (13)', None), ('', None)])
def test_communal_exception(lieu, expected, monkeypatch):
    s = service(rule(de=1800, a=1925), rule('partielle', communes=['Marseille'], de=1800, a=1904),
                rule('autre_service', communes=['Marseille'], de=1905,
                     lien='https://municipales.example/registres'))
    monkeypatch.setattr(archives, 'by_code', lambda code: s)
    response = server.archives_service(code='X', lieu=lieu, document='naissance', annee=1920)
    assert response['en_ligne_pour_la_demande'] is expected
    assert response['couverture_pour_la_demande']['regles']
    if lieu.startswith('Marseille'):
        assert response['couverture_pour_la_demande']['regles'][0]['lien'].startswith('https://municipales')


@pytest.mark.parametrize('lieu,expected', [('Arles (13)', True), ('Marseille (13)', None), ('', None)])
def test_excluded_commune(lieu, expected):
    assert archives.online(service(rule(sauf_communes=['Marseille'])), 'naissance', 1850, lieu=lieu) is expected


def test_lacune_overrides_general_coverage():
    s = service(rule(de=1800, a=1900), rule('lacune', communes=['Arles'], de=1840, a=1850))
    assert archives.online(s, 'naissance', 1845, lieu='Arles (13)') is None
    assert archives.online(s, 'naissance', 1851, lieu='Arles (13)') is True


def test_conflicting_rules_remain_unknown():
    s = service(rule(de=1800), rule('hors_ligne', a=1900))
    assert archives.online(s, 'naissance', 1850) is None


@pytest.mark.parametrize('today,year,expected', [(date(2026, 11, 8), 1925, True),
                                              (date(2026, 11, 8), 1926, None),
                                              (date(2026, 11, 8), 1927, None),
                                              (date(2027, 1, 1), 1926, True)])
def test_rolling_boundary(today, year, expected):
    s = service(rule(anciennete_min=100))
    assert archives.online(s, 'naissance', year, today=today) is expected


def test_normalized_commune_and_department_conflict():
    s = service(rule(communes=['Saint-Rémy-de-Provence']))
    assert archives.online(s, 'naissance', 1850, lieu='St Remy de Provence (13)') is True
    assert archives.online(s, 'naissance', 1850, lieu='Saint-Rémy-de-Provence (26)') is None


@pytest.mark.parametrize('bad', [None, {}, [rule(etat='absent')], [rule(de='1800')],
                               [rule(de=1900, a=1800)], [rule(communes='Marseille')],
                               [rule(anciennete_min=True)], [rule(reference='javascript:alert(1)')],
                               [rule(sauf_communes=[])], [rule(inconnu=True)]])
def test_bad_coverage_is_reported_without_crash(monkeypatch, bad):
    s = service()
    s['couvertures']['naissance'] = bad
    monkeypatch.setattr(archives, 'services', lambda: [s])
    assert archives.validate()
    assert archives.online(s, 'naissance', 1850) is None


def test_document_without_rules_remains_unknown():
    assert archives.online(service(rule()), 'deces', 1850) is None


def test_missing_year_and_unknown_commune_expose_reason(monkeypatch):
    s = service(rule(communes=['Arles'], de=1800))
    monkeypatch.setattr(archives, 'by_code', lambda code: s)
    result = server.archives_service(code='X', document='naissance')
    assert result['en_ligne_pour_la_demande'] is None
    assert result['couverture_pour_la_demande']['motif']


@pytest.mark.parametrize('year,expected', [(1900, None), (1920, None)])
def test_real_marseille_redirect_and_partial_other_communes(year, expected):
    result = server.archives_service(code='AD13', lieu='Marseille (13)', document='naissance', annee=year)
    assert result['en_ligne_pour_la_demande'] is expected
    if year > 1904:
        assert result['couverture_pour_la_demande']['etat'] == 'autre_service'
        assert result['lien'] == 'https://archives.marseille.fr/n/etat-civil/n:161'


def test_real_romans_exception_and_known_offline():
    romans = server.archives_service(code='AD26', lieu='Romans-sur-Isère (26)', document='naissance', annee=1930)
    assert romans['en_ligne_pour_la_demande'] is None
    assert romans['lien'] == 'https://archives.valenceromansagglo.fr/'
    assert server.archives_service(code='AD26', lieu='Valence (26)', document='naissance',
                                   annee=1930)['en_ligne_pour_la_demande'] is False
    assert server.archives_service(code='AD26', document='naissance', annee=1930)['en_ligne_pour_la_demande'] is None


@pytest.mark.parametrize('lieu', ['13', 'Bouches-du-Rhône', 'France'])
def test_department_is_not_a_commune(lieu):
    s = service(rule(sauf_communes=['Marseille']))
    assert archives.online(s, 'naissance', 1850, lieu=lieu) is None


def test_foreign_country_is_not_a_matching_commune():
    assert archives.online(service(rule(communes=['Arles'])), 'naissance', 1850,
                           lieu='Arles, Québec, Canada') is None


def test_communicability_passes_place_and_uncertain_year():
    result = server.communicabilite('naissance', '1930', lieu='Romans-sur-Isère (26)')
    assert result['en_ligne'] is None
    assert result['service_archives']['couverture_pour_la_demande']['etat'] == 'autre_service'
    assert result['service_archives']['lien'] in result['si_pas_en_ligne']['conseil']
    result = server.communicabilite('naissance', 'BET 1800 AND 1950', lieu='Valence (26)')
    assert result['en_ligne'] is None
