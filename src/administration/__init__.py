"""
Administration de la plateforme : gestion des entreprises abonnées et de leurs
utilisateurs par un administrateur de plateforme.

Périmètre distinct des routes métier : ces endpoints transcendent l'isolation
tenant (aucun header `x-entreprise-id`) et sont strictement réservés aux
comptes portant `admin_plateforme`.
"""
