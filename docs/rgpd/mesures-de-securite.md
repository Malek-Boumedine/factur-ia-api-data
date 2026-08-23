# Synthèse des mesures de sécurité

Ce document liste les protections techniques concrètement implémentées dans notre code, ainsi que les limites assumées pour l'instant. Il sert de base pour la rubrique "sécurité" de notre registre RGPD.

## 1. Sécurité des comptes et connexions
*   **Mots de passe introuvables :** Ils sont hachés (via bcrypt) avec un "sel" unique par utilisateur. Même nous, nous ne pouvons pas les lire (`src/core/security.py`).
*   **Connexions limitées dans le temps :** L'authentification utilise des jetons JWT signés. S'ils sont volés, ils expirent rapidement.
*   **Récupération de compte sécurisée :** Les liens "mot de passe oublié" sont à usage unique, limités dans le temps, et stockés sous forme d'empreinte (hash SHA-256) pour éviter toute fraude.
*   **Garde-fou administrateur :** Le compte "racine" de la plateforme ne peut être ni bloqué ni supprimé par erreur.

## 2. Protection des données bancaires (IBAN)
*   **Chiffrement en base de données :** Les IBAN sont chiffrés (Fernet) au repos. Si quelqu'un vole la base de données, il ne verra qu'une suite de caractères illisibles. L'application refuse de démarrer si la clé de déchiffrement n'est pas configurée.
*   **Masquage à l'écran :** L'API ne renvoie jamais l'IBAN complet au navigateur, seulement les 4 premiers et 4 derniers caractères (ex: `FR76 •••• 0189`).
*   **Censure automatique de l'IA :** Quand l'OCR lit une facture, l'IBAN détecté est immédiatement masqué avant même d'être sauvegardé.

## 3. Cloisonnement des données (Multi-tenant)
*   **Isolement total :** Chaque requête vérifie à quelle entreprise appartient l'utilisateur. Il est techniquement impossible qu'une entreprise accède aux clients ou factures d'une autre entreprise.
*   **Gestion fine des droits :** L'accès aux actions sensibles est bloqué si l'utilisateur n'a pas le rôle "Administrateur d'entreprise".

## 4. Hygiène des données : Logs, Minimisation et Intégrité
*   **Logs propres :** Aucun mot de passe, IBAN ou donnée personnelle n'est écrit dans les journaux d'activité (logs). Les URL enregistrées sont automatiquement nettoyées de leurs paramètres sensibles.
*   **Collecte minimale :** On ne demande que le strict nécessaire. Par exemple, l'adresse postale de l'utilisateur est facultative.
*   **Inaltérabilité légale :** Une facture validée est verrouillée. Les données du client à l'instant T sont "figées" pour respecter la loi anti-fraude à la TVA.

## 5. Qualité du code
*   **Contrôle automatisé :** Le code est scanné automatiquement (`bandit`) pour détecter les failles.
*   **Zéro secret en ligne :** Un outil (`detect-secrets`) bloque les envois de code si un développeur laisse traîner un mot de passe ou une clé d'API dans les fichiers.

---

## Limites actuelles et axes d'amélioration
La sécurité parfaite n'existe pas. Voici ce qu'il faut encore améliorer :

*   **Le chiffrement des IBAN a ses limites :** Il protège contre le vol de la base de données, mais pas si le serveur entier (qui contient la clé) est piraté. *Évolution prévue : gérer la clé via un service externe sécurisé (KMS).*
*   **Résultats de l'IA en clair :** À part l'IBAN qui est masqué, le reste des données lues par l'IA (adresses, noms) est stocké en clair. *Solution actuelle : conservation limitée à 2 ans.*
*   **Adresses IP stockées en clair :** Nécessaire pour les audits de sécurité, mais elles devront être purgées régulièrement.
*   **Phase de développement :**
    *   Pas encore de double authentification (MFA).
    *   CORS (autorisations web) trop ouvert : à verrouiller avant la mise en production.
    *   Aucun email n'est réellement envoyé pour le moment (SMTP non configuré).
    *   L'IA utilisée (Groq) est hors Europe. Le passage sur une solution européenne est prévu avant la commercialisation.
    *   Les purges des vieilles données se font manuellement pour l'instant.
