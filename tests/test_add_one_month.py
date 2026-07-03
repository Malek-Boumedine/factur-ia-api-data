"""Correctness du calcul « +1 mois » (``add_one_month``).

Vérifie le bornage au dernier jour du mois cible (mois de longueurs
différentes, années bissextiles) et le passage d'année. Fonction pure, pas de
base de données.

Les cas sont itérés dans un unique test (plutôt que ``pytest.mark.parametrize``)
pour rester compatible avec mypy strict sans décorateur non typé.
"""

from datetime import date

from src.abonnements.services import add_one_month

# (date de départ, date attendue à +1 mois)
_CAS: list[tuple[date, date]] = [
    # Bornage au dernier jour du mois cible (31 -> 28/29).
    (date(2025, 1, 31), date(2025, 2, 28)),
    (date(2024, 1, 31), date(2024, 2, 29)),  # année bissextile
    (date(2025, 3, 31), date(2025, 4, 30)),
    # Cas simples, même quantième.
    (date(2025, 1, 15), date(2025, 2, 15)),
    (date(2025, 4, 30), date(2025, 5, 30)),
    # Passage d'année.
    (date(2025, 12, 1), date(2026, 1, 1)),
    (date(2024, 12, 31), date(2025, 1, 31)),
    # 29 février -> 29 mars (pas de bornage nécessaire).
    (date(2024, 2, 29), date(2024, 3, 29)),
]


def test_add_one_month() -> None:
    for depart, attendu in _CAS:
        assert add_one_month(depart) == attendu, f"échec pour {depart}"
