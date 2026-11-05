"""Catalogue unique des statuts de preuve : libellés, icônes et ordres de classement.

Toute table de statuts vient d'ici (fiche, notes, exports GeneWeb et Gramps) : ajouter ou renommer un statut ne
se fait qu'à un endroit, et test_statuts vérifie que chaque table couvre tous les statuts."""

from __future__ import annotations

STATUTS = ("confirme", "probable", "hypothese", "contradictoire", "non_source", "refute")

LABELS = {
    "confirme": "confirmé", "probable": "probable", "hypothese": "hypothèse",
    "contradictoire": "contradictoire", "refute": "réfuté", "non_source": "non sourcé",
}

ICONS = {"confirme": "✅", "probable": "🟢", "hypothese": "🟡", "contradictoire": "⚠️", "refute": "❌",
         "non_source": "⛔"}

# Choix de la version à retenir (export GeneWeb, Gramps) : 0 = la mieux prouvée. Une version contradictoire
# reste préférable à une version sans source ; une version réfutée n'est retenue qu'en dernier recours.
RANG_VERSION = {s: i for i, s in enumerate(STATUTS)}

# Gravité pour résumer un ensemble de faits (notes) : 0 = le plus préoccupant.
GRAVITE = {"refute": 0, "contradictoire": 1, "non_source": 2, "hypothese": 3, "probable": 4, "confirme": 5}

# Couleurs des étiquettes Gramps Web ; l'ordre fixe la priorité des étiquettes (ne pas réordonner).
COULEURS = {"confirme": "#2e7d32", "probable": "#689f38", "hypothese": "#f9a825",
            "contradictoire": "#ef6c00", "refute": "#c62828", "non_source": "#757575"}
