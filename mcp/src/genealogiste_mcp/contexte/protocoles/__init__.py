"""Analyseurs de protocole des services de contexte (#286), partagés entre services et entre outils.

Un analyseur lit le **format de transport** d'une réponse réellement reçue et ne sait rien d'un service
particulier : ``solr`` (réponse JSON Solr), ``sru`` (searchRetrieveResponse : Dublin Core, UNIMARC), ``oai``
(OAI-PMH, oai_dc), ``rest`` (JSON quelconque : chemins, textes, listes). Un service se décrit par son entrée du
référentiel (``referentiels/sources_contexte.json``) et un gabarit de requête (``contexte/gabarits.py`` pour la
bibliographie) qui construit les paramètres et transforme les enregistrements en champs de ``Reference``.

Aucun réseau ici ; aucune donnée de personne. Une réponse dont la forme n'est pas celle attendue lève
``ReponseInvalide`` (jamais de résultat partiel deviné).
"""

from __future__ import annotations


class ReponseInvalide(ValueError):
    """Réponse d'un service illisible ou de forme inattendue (diagnostic SRU, OAI error, JSON sans la clé…)."""


def refuser_dtd(xml_text: str) -> None:
    """Refuse un document XML portant une DTD (DOCTYPE, ENTITY) : aucune réponse attendue n'en a, et une DTD
    permet l'expansion d'entités."""
    debut = xml_text[:4096].upper()
    if "<!DOCTYPE" in debut or "<!ENTITY" in xml_text.upper():
        raise ReponseInvalide("réponse XML refusée : DTD ou entité déclarée")


__all__ = ["ReponseInvalide", "refuser_dtd"]
