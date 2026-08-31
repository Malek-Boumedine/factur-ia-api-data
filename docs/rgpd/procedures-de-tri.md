# Procédures de tri, purge et anonymisation

Ce document explique comment j'applique mes règles de conservation des données.
**Actuellement, je gère tout manuellement.** J'exécute les purges de façon documentée (ce qui est accepté par la CNIL et les certificateurs), mais la dernière section précise ce que je prévois d'automatiser à l'avenir.

## Règles générales d'exécution

*   **Sécurité d'abord :** Chaque purge SQL est encadrée par une transaction (`START TRANSACTION` ... `COMMIT`) et précédée d'un comptage (`SELECT COUNT`) pour m'éviter les mauvaises surprises.
*   **Traçabilité :** Chaque purge est notée dans un journal spécifique (date, procédure, volume supprimé). C'est ma preuve de conformité.
*   **Deux rythmes de ménage :**
    *   **Annuel :** pour la compta (factures, déclarations), les clients et les logs de sécurité.
    *   **Trimestriel :** pour les documents, les résultats de l'IA (OCR), les mots de passe oubliés et les comptes inactifs.

---

## 1. Purge à 10 ans : Factures et comptabilité (Rythme annuel)

**Règle :** Obligation légale de garder les pièces comptables pendant 10 ans. Je ne supprime aucune facture avant ce délai, même si le client le demande.
**Périmètre :** La facture et tout ce qui s'y rattache (lignes, paiements, relances).

*Note sur les avoirs : je ne supprime une facture que si tous les avoirs qui y sont liés ont aussi plus de 10 ans.*

```sql
START TRANSACTION;

-- Je liste les factures de plus de 10 ans, sans avoirs récents liés
CREATE TEMPORARY TABLE tmp_factures_a_purger AS
SELECT f.id FROM facture f
WHERE f.date_emission < DATE_SUB(CURDATE(), INTERVAL 10 YEAR)
  AND NOT EXISTS (
    SELECT 1 FROM facture a
    WHERE a.id_facture_origine = f.id
      AND a.date_emission >= DATE_SUB(CURDATE(), INTERVAL 10 YEAR)
  );

-- Comptage de vérification
SELECT COUNT(*) FROM tmp_factures_a_purger;

-- Nettoyage des liens et suppression
UPDATE extraction_ocr SET id_facture = NULL WHERE id_facture IN (SELECT id FROM tmp_factures_a_purger);
DELETE FROM facture_ligne WHERE id_facture IN (SELECT id FROM tmp_factures_a_purger);
DELETE FROM paiement      WHERE id_facture IN (SELECT id FROM tmp_factures_a_purger);
DELETE FROM evenement_pdp WHERE id_facture IN (SELECT id FROM tmp_factures_a_purger);
DELETE FROM relance       WHERE id_facture IN (SELECT id FROM tmp_factures_a_purger);
DELETE FROM facture       WHERE id        IN (SELECT id FROM tmp_factures_a_purger);

DROP TEMPORARY TABLE tmp_factures_a_purger;
COMMIT;
```

---

## 2. Purge à 2 ans : IA/OCR et Fichiers (Rythme trimestriel)

**Règle :** Les factures PDF uploadées et leur analyse brute par l'IA concentrent beaucoup de données personnelles. Je les supprime au bout de 2 ans. (C'est suffisant pour faire le lien en cas de contrôle comptable).

**Procédure (en 3 étapes) :**

**Étape 1 : Vider les résultats bruts de l'IA :**
```sql
START TRANSACTION;
UPDATE extraction_ocr SET contenu_brut = NULL
WHERE date_extraction < DATE_SUB(NOW(), INTERVAL 2 YEAR);
COMMIT;
```

**Étape 2 : Lister et supprimer les fichiers physiques :**
Je récupère la liste des fichiers vieux de plus de 2 ans.
```sql
SELECT id, nom_fichier FROM document WHERE date_chargement < DATE_SUB(NOW(), INTERVAL 2 YEAR);
```
Puis je supprime les PDF correspondants sur le serveur (`rm uploads/documents/<nom_fichier>`). **Important : je supprime les fichiers AVANT de nettoyer la base de données.**

**Étape 3 : Nettoyer la base de données :**
```sql
START TRANSACTION;
CREATE TEMPORARY TABLE tmp_documents AS
SELECT id FROM document WHERE date_chargement < DATE_SUB(NOW(), INTERVAL 2 YEAR);

UPDATE facture SET id_document = NULL WHERE id_document IN (SELECT id FROM tmp_documents);
DELETE FROM extraction_ocr WHERE id_document IN (SELECT id FROM tmp_documents);
DELETE FROM document WHERE id IN (SELECT id FROM tmp_documents);
DROP TEMPORARY TABLE tmp_documents;
COMMIT;
```

---

## 3. Anonymisation à 3 ans : Comptes inactifs (Rythme trimestriel)

**Règle :** Après 3 ans sans connexion, j'anonymise le compte. **Je ne le supprime pas**, car j'ai besoin de conserver l'identifiant pour garder la cohérence des factures que cette personne a créées.

**Attention :** Cette procédure nécessite ma revue humaine. Je ne dois pas anonymiser le dernier administrateur d'une entreprise encore active.

```sql
START TRANSACTION;

-- Pour chaque compte retenu (id) :
UPDATE utilisateur SET
  nom = 'Anonymisé', prenom = '',
  email = CONCAT('anonyme-', id, '@invalide.local'),
  telephone = NULL, adresse = NULL, adresse_complement = NULL, code_postal = NULL, ville = NULL,
  hash_mot_de_passe = '$2b$12$anonymisation.hash.invalide.sans.preimage.connue000000',
  est_actif = FALSE
WHERE id = :id;

-- Nettoyage des historiques liés
DELETE FROM reinitialisation_mot_de_passe WHERE id_utilisateur = :id;
DELETE FROM notification WHERE id_utilisateur = :id;
DELETE FROM journal_audit WHERE entite = 'utilisateur' AND id_entite = :id;

COMMIT;
```

---

## 4. Purge à 2 ans : Journal d'audit (Rythme annuel)

**Règle :** L'historique des actions de sécurité (qui stocke les adresses IP et les anciennes valeurs) est supprimé après 2 ans. C'est une durée volontairement plus longue qu'un simple log de connexion, car cela me sert de traçabilité comptable.

```sql
START TRANSACTION;
DELETE FROM journal_audit WHERE date_action < DATE_SUB(NOW(), INTERVAL 2 YEAR);
COMMIT;
```

---

## 5. Purge à 30 jours : Mots de passe oubliés (Rythme trimestriel)

**Règle :** Je supprime les tokens de réinitialisation de mot de passe 30 jours après leur date d'expiration.
*(Même si les tokens expirés sont inactifs et hashés, je préfère supprimer ce résidu).*

```sql
START TRANSACTION;
DELETE FROM reinitialisation_mot_de_passe WHERE date_expiration < DATE_SUB(NOW(), INTERVAL 30 DAY);
COMMIT;
```

---

## 6. Purge à 1 an : Notifications (Rythme trimestriel)

**Règle :** Je supprime les alertes et messages systèmes de plus d'un an, qu'ils soient lus ou expirés.

```sql
START TRANSACTION;
DELETE FROM notification
WHERE (est_lu = TRUE AND date_lecture < DATE_SUB(NOW(), INTERVAL 1 YEAR))
   OR (date_expiration IS NOT NULL AND date_expiration < DATE_SUB(NOW(), INTERVAL 1 YEAR));
COMMIT;
```

---

## 7. Purge mixte : Fiches clients (Rythme annuel)

**Règle :**
*   Si le client a **des factures** : Je garde sa fiche 10 ans après sa *dernière* facture.
*   Si le client n'a **aucune facture** : Je supprime sa fiche 3 ans après sa désactivation.

L'astuce consiste à faire tourner cette purge **juste après celle des factures (Procédure 1)**.

```sql
START TRANSACTION;
DELETE FROM client
WHERE est_actif = FALSE
  AND date_desactivation < DATE_SUB(NOW(), INTERVAL 3 YEAR)
  AND NOT EXISTS (SELECT 1 FROM facture f WHERE f.id_client = client.id);
COMMIT;
```

---

## 8. Purge à 10 ans : Déclarations (Rythme annuel)

**Règle :** Sur la même logique que la comptabilité, je conserve les déclarations (TVA, etc.) pendant 10 ans.

```sql
START TRANSACTION;
DELETE FROM declaration WHERE periode_fin < DATE_SUB(CURDATE(), INTERVAL 10 YEAR);
COMMIT;
```

---

## 9. Purge à 3 ans : Relances (Rythme annuel)

**Règle :** Les historiques d'envoi de mails de relance sont purgés au bout de 3 ans. (À noter que si une facture est purgée via la procédure 1, ses relances partent automatiquement avec).

```sql
START TRANSACTION;
DELETE FROM relance WHERE date_relance < DATE_SUB(NOW(), INTERVAL 3 YEAR);
COMMIT;
```

---

## Trajectoire d'automatisation (Plan de route)

Pour l'instant manuelles, voici mon ordre de priorité pour l'automatisation de ces procédures :

1.  **En priorité absolue (Scripts planifiés ou cron) :**
    *   La **procédure 2 (OCR et PDF)** : pour être certain de bien effacer les fichiers physiques.
    *   La **procédure 4 (Journal d'audit)** : pour purger les IPs plus fréquemment.
2.  **Facile et rapide :** La procédure 5 (tokens) et les procédures 6 et 9 (notifications/relances).
3.  **À garder sous supervision (Semi-automatique) :** La procédure 3 (Anonymisation des comptes) devra toujours inclure une validation de ma part pour éviter de casser la gestion d'une entreprise active.
4.  **Non prioritaire (Horizon 2035+) :** Les purges à 10 ans (Factures, Déclarations, Clients).
