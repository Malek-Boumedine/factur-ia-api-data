# Modèle de données — inventaire des tables

Document généré à partir du code réel (modèles SQLModel `src/**/models.py` et migrations Alembic `migrations/versions/`), qui fait foi.
Base cible : MySQL 8.0. Les colonnes `ENUM(...)` listent les valeurs stockées en base (noms des membres Python).
**28 tables implémentées.** incluant les tables de l'ancienne référence `liste_tables.md`.

## 1. Utilisateurs & accès - ***11 TABLES***

### <u>***utilisateur***</u>
Personne physique sur la plateforme. Un utilisateur peut appartenir à plusieurs entreprises (espaces de travail).
| colonne                 | type         | contrainte              | description                                                        |
| ----------------------- | ------------ | ----------------------- | ------------------------------------------------------------------ |
| id                      | INT          | PK, AUTO_INCREMENT      | Identifiant technique auto-incrémenté                              |
| nom                     | VARCHAR(255) | NOT NULL                | Nom de famille                                                     |
| prenom                  | VARCHAR(255) | NOT NULL                | Prénom                                                             |
| adresse                 | VARCHAR(255) | NULLABLE                | Adresse principale                                                 |
| adresse_complement      | VARCHAR(255) | NULLABLE                | Complément d'adresse                                               |
| code_postal             | VARCHAR(10)  | NULLABLE, INDEX         | Code postal                                                        |
| ville                   | VARCHAR(150) | NULLABLE, INDEX         | Nom de la ville                                                    |
| email                   | VARCHAR(255) | UNIQUE, NOT NULL, INDEX | Adresse email (identifiant de connexion)                           |
| telephone               | VARCHAR(20)  | NULLABLE                | Numéro de téléphone                                                |
| hash_mot_de_passe       | VARCHAR(255) | NOT NULL                | Hash bcrypt du mot de passe                                        |
| date_creation           | DATETIME     | NOT NULL, DEFAULT NOW() | Date de création du compte                                         |
| date_modification       | DATETIME     | NOT NULL, DEFAULT NOW() | Date de dernière modification (onupdate)                           |
| date_derniere_connexion | DATETIME     | NULLABLE                | Date de dernière connexion                                         |
| est_actif               | BOOLEAN      | NOT NULL, DEFAULT TRUE  | Indique si le compte est actif                                     |
| admin_plateforme        | BOOLEAN      | NOT NULL, DEFAULT FALSE, INDEX | Administrateur au niveau plateforme (distinct de l'admin d'entreprise) |
| compte_protege          | BOOLEAN      | NOT NULL, DEFAULT FALSE | Compte racine protégé : ni révocable ni supprimable                |

### <u>***entreprise***</u>
Entité centrale du SaaS (le tenant). Toutes les données métier sont isolées par `id_entreprise`.
| colonne            | type         | contrainte                            | description                                                          |
| ------------------ | ------------ | ------------------------------------- | -------------------------------------------------------------------- |
| id                 | INT          | PK, AUTO_INCREMENT                    | Identifiant technique auto-incrémenté                                 |
| nom_entreprise     | VARCHAR(255) | NOT NULL, INDEX                       | Nom de la société ou de l'espace de travail                           |
| siret              | VARCHAR(14)  | UNIQUE, NULLABLE, INDEX               | Numéro SIRET de l'entreprise                                          |
| id_forme_juridique | INT          | FK → ref_forme_juridique.id, NULLABLE | Référence vers la forme juridique                                     |
| date_creation      | DATETIME     | NOT NULL, DEFAULT NOW()               | Date de création de l'espace entreprise                               |
| date_modification  | DATETIME     | NULLABLE, DEFAULT NOW()               | Date de dernière modification (onupdate, renseignée par l'application) |
| est_actif          | BOOLEAN      | NOT NULL, DEFAULT TRUE                | État d'accès : FALSE = entreprise suspendue (403 sur toutes les routes tenant) |
| date_suspension    | DATETIME     | NULLABLE                              | Date de suspension par un administrateur de plateforme                |
| motif_suspension   | VARCHAR(255) | NULLABLE                              | Motif de la suspension                                                |

### <u>***utilisateur_entreprise***</u>
Table pivot : lie un utilisateur à une ou plusieurs entreprises (multi-tenancy).
| colonne        | type    | contrainte                                  | description                                        |
| -------------- | ------- | ------------------------------------------- | -------------------------------------------------- |
| id_utilisateur | INT     | PK, FK → utilisateur.id, ON DELETE CASCADE  | Référence vers l'utilisateur                       |
| id_entreprise  | INT     | PK, FK → entreprise.id                      | Référence vers l'entreprise                        |
| est_admin      | BOOLEAN | NOT NULL, DEFAULT FALSE                     | Admin métier de cette entreprise (droits de gestion) |

Contrainte d'unicité `unique_utilisateur_entreprise` sur (id_utilisateur, id_entreprise), en plus de la clé primaire composite.

### <u>***ref_forme_juridique***</u>
Référentiel des formes juridiques (SAS, SARL, auto-entreprise...).
| colonne            | type         | contrainte              | description                                       |
| ------------------ | ------------ | ----------------------- | ------------------------------------------------- |
| id                 | INT          | PK, AUTO_INCREMENT      | Identifiant technique auto-incrémenté             |
| code               | VARCHAR(20)  | UNIQUE, NOT NULL, INDEX | Code court (ex : SAS, AE)                         |
| libelle            | VARCHAR(100) | NOT NULL                | Nom complet (ex : Société par Actions Simplifiée) |
| mention_tva_defaut | VARCHAR(255) | NULLABLE                | Mention légale TVA par défaut sur la facture      |
| est_actif          | BOOLEAN      | NOT NULL, DEFAULT TRUE  | Indique si la forme juridique est utilisable      |

### <u>***role***</u>
Référentiel des rôles disponibles (ex : admin, comptable, gestionnaire).
| colonne     | type         | contrainte              | description                           |
| ----------- | ------------ | ----------------------- | ------------------------------------- |
| id          | INT          | PK, AUTO_INCREMENT      | Identifiant technique auto-incrémenté |
| libelle     | VARCHAR(100) | UNIQUE, NOT NULL, INDEX | Nom du rôle (ex : admin, comptable)   |
| description | TEXT         | NULLABLE                | Description du rôle                   |

### <u>***permission***</u>
Référentiel des actions possibles dans l'API (ex : facture:create).
| colonne     | type         | contrainte              | description                                 |
| ----------- | ------------ | ----------------------- | ------------------------------------------- |
| id          | INT          | PK, AUTO_INCREMENT      | Identifiant technique auto-incrémenté       |
| libelle     | VARCHAR(100) | UNIQUE, NOT NULL, INDEX | Code de la permission (ex : facture:create) |
| description | TEXT         | NULLABLE                | Description de l'action autorisée           |

### <u>***permission_role***</u>
Table pivot : associe un rôle à une ou plusieurs permissions.
| colonne       | type | contrainte             | description                  |
| ------------- | ---- | ---------------------- | ---------------------------- |
| id_role       | INT  | PK, FK → role.id       | Référence vers le rôle       |
| id_permission | INT  | PK, FK → permission.id | Référence vers la permission |

### <u>***utilisateur_role***</u>
Table pivot : associe un utilisateur à un rôle, globalement ou dans le contexte d'une entreprise.
| colonne        | type | contrainte                                            | description                                           |
| -------------- | ---- | ----------------------------------------------------- | ----------------------------------------------------- |
| id             | INT  | PK, AUTO_INCREMENT                                    | Identifiant technique (clé primaire simple)           |
| id_utilisateur | INT  | FK → utilisateur.id, NOT NULL, INDEX, ON DELETE CASCADE | Référence vers l'utilisateur                        |
| id_role        | INT  | FK → role.id, NOT NULL, INDEX                         | Référence vers le rôle                                |
| id_entreprise  | INT  | FK → entreprise.id, NULLABLE, INDEX                   | Entreprise concernée (NULL si rôle global plateforme) |

### <u>***reinitialisation_mot_de_passe***</u>
Token de réinitialisation de mot de passe, à usage unique et à durée de vie limitée. Le token en clair n'est jamais stocké : seul son hash SHA-256 est persisté.
| colonne          | type        | contrainte                                            | description                                          |
| ---------------- | ----------- | ----------------------------------------------------- | ---------------------------------------------------- |
| id               | INT         | PK, AUTO_INCREMENT                                    | Identifiant technique auto-incrémenté                |
| id_utilisateur   | INT         | FK → utilisateur.id, NOT NULL, INDEX, ON DELETE CASCADE | Utilisateur concerné                               |
| token_hash       | VARCHAR(64) | UNIQUE, NOT NULL, INDEX                               | Hash SHA-256 hexadécimal du token (jamais le clair)  |
| date_expiration  | DATETIME    | NOT NULL                                              | Date limite de validité du token                     |
| date_utilisation | DATETIME    | NULLABLE                                              | NULL tant que le token n'a pas servi ; horodaté à la consommation |
| date_creation    | DATETIME    | NOT NULL, DEFAULT NOW()                               | Date de création du token                            |

### <u>***abonnement***</u>
Les formules/plans disponibles avec leurs limites et tarifs.
| colonne                  | type          | contrainte              | description                                 |
| ------------------------ | ------------- | ----------------------- | ------------------------------------------- |
| id                       | INT           | PK, AUTO_INCREMENT      | Identifiant technique auto-incrémenté       |
| libelle                  | VARCHAR(100)  | UNIQUE, NOT NULL, INDEX | Nom du plan (ex : Gratuit, Pro, Enterprise) |
| description              | TEXT          | NULLABLE                | Description du plan                         |
| tarif                    | DECIMAL(10,2) | NOT NULL, DEFAULT 0     | Tarif mensuel en euros                      |
| nombre_max_utilisateurs  | INT           | NOT NULL, DEFAULT 1     | Nombre maximum d'utilisateurs sur ce plan   |
| nombre_max_factures_mois | INT           | NOT NULL, DEFAULT 10    | Nombre maximum de factures émises par mois  |

### <u>***entreprise_abonnement***</u>
Table de souscription : associe un abonnement à une entreprise, avec dates et statut.
| colonne       | type                                            | contrainte                   | description                           |
| ------------- | ----------------------------------------------- | ---------------------------- | ------------------------------------- |
| id            | INT                                             | PK, AUTO_INCREMENT           | Identifiant technique auto-incrémenté |
| id_entreprise | INT                                             | FK → entreprise.id, NOT NULL, INDEX | Référence vers l'entreprise    |
| id_abonnement | INT                                             | FK → abonnement.id, NOT NULL | Référence vers l'abonnement           |
| date_debut    | DATE                                            | NOT NULL, DEFAULT aujourd'hui | Date de début de la souscription     |
| date_fin      | DATE                                            | NULLABLE                     | Date de fin (NULL si non définie)     |
| statut        | ENUM('ACTIF', 'EXPIRE', 'SUSPENDU', 'ANNULE')   | NOT NULL, DEFAULT 'ACTIF'    | Statut de la souscription             |
| date_creation | DATETIME                                        | NOT NULL, DEFAULT NOW()      | Date de création de la ligne          |

# ------------------------------------------------------------------------------------------

## 2. Documents & facturation - ***8 TABLES***

### <u>***client***</u>
Référentiel client de chaque entreprise. L'unicité du SIRET et du numéro de TVA ne vaut qu'au sein d'une entreprise : deux entreprises peuvent facturer le même client.
| colonne            | type         | contrainte                    | description                                         |
| ------------------ | ------------ | ----------------------------- | --------------------------------------------------- |
| id                 | INT          | PK, AUTO_INCREMENT            | Identifiant technique auto-incrémenté               |
| id_entreprise      | INT          | FK → entreprise.id, NOT NULL, INDEX | Entreprise propriétaire du client             |
| id_createur        | INT          | FK → utilisateur.id, NOT NULL | Utilisateur qui a créé la fiche client              |
| id_modificateur    | INT          | FK → utilisateur.id, NULLABLE | Utilisateur ayant effectué la dernière modification |
| raison_sociale     | VARCHAR(255) | NOT NULL, INDEX               | Nom ou raison sociale du client                     |
| siret              | VARCHAR(14)  | NULLABLE, INDEX               | Numéro SIRET (unique par entreprise)                |
| numero_tva         | VARCHAR(20)  | NULLABLE                      | Numéro TVA intracommunautaire (unique par entreprise) |
| adresse            | VARCHAR(255) | NULLABLE                      | Adresse du client                                   |
| adresse_complement | VARCHAR(255) | NULLABLE                      | Complément d'adresse                                |
| code_postal        | VARCHAR(10)  | NOT NULL, INDEX               | Code postal du client                               |
| ville              | VARCHAR(150) | NOT NULL, INDEX               | Ville du client                                     |
| email              | VARCHAR(255) | NULLABLE, INDEX               | Email de contact                                    |
| telephone          | VARCHAR(20)  | NULLABLE                      | Téléphone de contact                                |
| est_actif          | BOOLEAN      | NOT NULL, DEFAULT TRUE        | Indique si le client est actif                      |
| date_creation      | DATETIME     | NOT NULL, DEFAULT NOW()       | Date de création                                    |
| date_modification  | DATETIME     | NULLABLE, DEFAULT NOW()       | Date de dernière modification (onupdate, renseignée par l'application) |
| date_desactivation | DATETIME     | NULLABLE                      | Date de désactivation du client                     |

Contraintes d'unicité composites : `unique_entreprise_siret` (id_entreprise, siret) et `unique_entreprise_numero_tva` (id_entreprise, numero_tva).

### <u>***document***</u>
Fichier brut (PDF, image...) uploadé par l'utilisateur avant traitement OCR.
| colonne         | type                                              | contrainte                    | description                                     |
| --------------- | ------------------------------------------------- | ----------------------------- | ----------------------------------------------- |
| id              | INT                                               | PK, AUTO_INCREMENT            | Identifiant technique auto-incrémenté           |
| id_entreprise   | INT                                               | FK → entreprise.id, NOT NULL, INDEX | Entreprise propriétaire du document       |
| id_utilisateur  | INT                                               | FK → utilisateur.id, NOT NULL | Utilisateur ayant uploadé le fichier            |
| nom_fichier     | VARCHAR(255)                                      | NOT NULL                      | Nom de stockage du fichier                      |
| nom_original    | VARCHAR(255)                                      | NOT NULL                      | Nom original du fichier tel qu'uploadé          |
| date_chargement | DATETIME                                          | NOT NULL, DEFAULT NOW()       | Date d'upload du fichier                        |
| statut          | ENUM('EN_ATTENTE', 'EN_COURS', 'TRAITE', 'ERREUR') | NOT NULL, DEFAULT 'EN_ATTENTE' | Statut du traitement                          |

### <u>***extraction_ocr***</u>
Résultat brut retourné par l'IA après analyse du document.
| colonne         | type                     | contrainte                 | description                                                             |
| --------------- | ------------------------ | -------------------------- | ----------------------------------------------------------------------- |
| id              | INT                      | PK, AUTO_INCREMENT         | Identifiant technique auto-incrémenté                                   |
| id_document     | INT                      | FK → document.id, NOT NULL | Document source analysé                                                 |
| contenu_brut    | JSON                     | NULLABLE                   | Données brutes extraites par l'IA (IBAN masqué à l'ingestion)           |
| score_confiance | DECIMAL(5,2)             | NULLABLE                   | Score de confiance global de l'extraction (0-100)                       |
| date_extraction | DATETIME                 | NOT NULL, DEFAULT NOW()    | Date de l'extraction                                                    |
| statut          | ENUM('SUCCES', 'ECHEC')  | NOT NULL, DEFAULT 'ECHEC'  | Résultat du traitement OCR/IA                                           |
| type_document   | VARCHAR(20)              | NULLABLE                   | Type de document détecté par l'API IA                                   |
| par_champ       | JSON                     | NULLABLE                   | Scores de confiance par champ extrait (chaînes, précision préservée)    |
| id_facture      | INT                      | FK → facture.id, NULLABLE  | Facture générée depuis cette extraction (si succès)                     |

### <u>***facture***</u>
Entité comptable principale : facture classique ou avoir (`type_facture`). Les avoirs sont des lignes de cette table (montants négatifs, `id_facture_origine` renseigné) — il n'existe pas de table `avoir` séparée.
| colonne                  | type                       | contrainte                       | description                                                              |
| ------------------------ | -------------------------- | -------------------------------- | ------------------------------------------------------------------------ |
| id                       | INT                        | PK, AUTO_INCREMENT               | Identifiant technique auto-incrémenté                                     |
| id_entreprise            | INT                        | FK → entreprise.id, NOT NULL, INDEX | Entreprise propriétaire de la facture                                 |
| id_createur              | INT                        | FK → utilisateur.id, NOT NULL    | Utilisateur ayant créé la facture                                         |
| id_client                | INT                        | FK → client.id, NULLABLE         | Client destinataire                                                       |
| id_document              | INT                        | FK → document.id, NULLABLE       | Document source (si issue d'un upload)                                    |
| id_facture_origine       | INT                        | FK → facture.id, NULLABLE, INDEX | Facture d'origine (renseigné uniquement pour un avoir)                    |
| numero_facture           | VARCHAR(50)                | NOT NULL, INDEX                  | Numéro de facture (unique par entreprise, séquentiel à la validation)     |
| date_emission            | DATE                       | NOT NULL, DEFAULT aujourd'hui    | Date d'émission                                                           |
| date_echeance            | DATE                       | NULLABLE                         | Date d'échéance du paiement                                               |
| devise                   | VARCHAR(3)                 | NOT NULL, DEFAULT 'EUR'          | Devise (ISO 4217)                                                         |
| type_facture             | ENUM('FACTURE', 'AVOIR')   | NOT NULL, DEFAULT 'FACTURE'      | Distingue une facture classique d'un avoir                                |
| id_statut                | INT                        | FK → statut_facture.id, NOT NULL | Statut de la facture                                                      |
| siret_emetteur           | VARCHAR(14)                | NULLABLE                         | SIRET émetteur (snapshot figé à la validation)                            |
| siret_destinataire       | VARCHAR(14)                | NULLABLE                         | SIRET destinataire (snapshot figé à la validation)                        |
| snapshot_client          | JSON                       | NULLABLE                         | Coordonnées client figées à la validation (raison_sociale, adresse, code_postal, ville) |
| total_ht                 | DECIMAL(12,2)              | NOT NULL                         | Total hors taxe (négatif pour un avoir)                                   |
| total_tva                | DECIMAL(12,2)              | NOT NULL                         | Total TVA (négatif pour un avoir)                                         |
| total_ttc                | DECIMAL(12,2)              | NOT NULL                         | Total toutes taxes comprises (négatif pour un avoir)                      |
| numero_flux_depot_chorus | VARCHAR(50)                | NULLABLE                         | Numéro de flux Chorus Pro, renseigné après un dépôt accepté               |
| date_transmission_chorus | DATETIME                   | NULLABLE                         | Date de transmission à Chorus Pro                                         |
| mode_paiement            | VARCHAR(50)                | NULLABLE                         | Mode de paiement prévu (virement, chèque…)                                |
| iban                     | VARCHAR(255)               | NULLABLE                         | IBAN de paiement, **chiffré au repos (Fernet)** : token en base, clair côté application |
| reference_commande       | VARCHAR(100)               | NULLABLE                         | Référence bon de commande                                                 |
| date_creation            | DATETIME                   | NOT NULL, DEFAULT NOW()          | Date de création                                                          |
| date_modification        | DATETIME                   | NULLABLE                         | Date de dernière modification (onupdate)                                  |
| notes                    | TEXT                       | NULLABLE                         | Notes internes sur la facture                                             |

Contrainte d'unicité composite `unique_entreprise_numero_facture` (id_entreprise, numero_facture). Index composite `ix_facture_entreprise_date_emission` (id_entreprise, date_emission) pour les statistiques et listes filtrées par période.

### <u>***facture_ligne***</u>
Lignes de détail de la facture.
| colonne          | type          | contrainte                 | description                              |
| ---------------- | ------------- | -------------------------- | ---------------------------------------- |
| id               | INT           | PK, AUTO_INCREMENT         | Identifiant technique auto-incrémenté    |
| id_facture       | INT           | FK → facture.id, NOT NULL  | Facture parente                          |
| ordre            | INT           | NOT NULL, DEFAULT 0        | Ordre d'affichage de la ligne            |
| designation      | VARCHAR(255)  | NOT NULL                   | Désignation du produit ou service        |
| quantite         | DECIMAL(10,3) | NOT NULL                   | Quantité (négative pour un avoir)        |
| unite            | VARCHAR(50)   | NULLABLE                   | Unité (ex : heure, kg, pièce)            |
| prix_unitaire_ht | DECIMAL(12,2) | NOT NULL                   | Prix unitaire hors taxe                  |
| id_taux_tva      | INT           | FK → taux_tva.id, NOT NULL | Taux de TVA applicable                   |
| montant_ht       | DECIMAL(12,2) | NOT NULL                   | Montant HT (quantite × prix_unitaire_ht) |
| montant_tva      | DECIMAL(12,2) | NOT NULL                   | Montant TVA calculé                      |
| montant_ttc      | DECIMAL(12,2) | NOT NULL                   | Montant TTC calculé                      |

### <u>***paiement***</u>
Enregistrement des paiements reçus sur une facture.
| colonne       | type          | contrainte                    | description                                  |
| ------------- | ------------- | ----------------------------- | -------------------------------------------- |
| id            | INT           | PK, AUTO_INCREMENT            | Identifiant technique auto-incrémenté        |
| id_facture    | INT           | FK → facture.id, NOT NULL     | Facture concernée par le paiement            |
| id_createur   | INT           | FK → utilisateur.id, NOT NULL | Utilisateur ayant enregistré le paiement     |
| montant       | DECIMAL(12,2) | NOT NULL                      | Montant du paiement                          |
| date_paiement | DATE          | NOT NULL, DEFAULT aujourd'hui | Date effective du paiement                   |
| mode_paiement | VARCHAR(50)   | NOT NULL                      | Mode de paiement (virement, chèque…)         |
| reference     | VARCHAR(100)  | NULLABLE                      | Référence du paiement (n° chèque, virement…) |
| notes         | TEXT          | NULLABLE                      | Notes internes sur le paiement               |
| date_creation | DATETIME      | NOT NULL, DEFAULT NOW()       | Date de création de l'enregistrement         |

### <u>***taux_tva***</u>
Référentiel des taux de TVA applicables.
| colonne        | type         | contrainte             | description                                |
| -------------- | ------------ | ---------------------- | ------------------------------------------ |
| id             | INT          | PK, AUTO_INCREMENT     | Identifiant technique auto-incrémenté      |
| taux           | DECIMAL(5,2) | UNIQUE, NOT NULL       | Valeur du taux (ex : 0, 5.50, 10, 20)      |
| libelle        | VARCHAR(100) | NOT NULL               | Libellé (ex : TVA normale, TVA réduite)    |
| code_comptable | VARCHAR(50)  | NULLABLE               | Code de compte pour l'export (ex : 445711) |
| est_actif      | BOOLEAN      | NOT NULL, DEFAULT TRUE | Indique si le taux est utilisable          |

### <u>***catalogue_produits***</u>
Catalogue des articles et prestations proposées par l'entreprise.
| colonne           | type                                        | contrainte                    | description                                                    |
| ----------------- | ------------------------------------------- | ----------------------------- | -------------------------------------------------------------- |
| id                | INT                                         | PK, AUTO_INCREMENT            | Identifiant technique auto-incrémenté                          |
| id_entreprise     | INT                                         | FK → entreprise.id, NOT NULL, INDEX | Entreprise propriétaire                                  |
| id_utilisateur    | INT                                         | FK → utilisateur.id, NOT NULL | Utilisateur ayant créé l'entrée                                |
| id_taux_tva       | INT                                         | FK → taux_tva.id, NOT NULL    | Taux de TVA applicable                                         |
| type_produit      | ENUM('PRODUIT', 'PRESTATION', 'SERVICE')    | NOT NULL, DEFAULT 'PRODUIT'   | Type URSSAF : produit, prestation de services, autre service   |
| reference         | VARCHAR(100)                                | NULLABLE, INDEX               | Référence interne                                              |
| designation       | VARCHAR(255)                                | NOT NULL                      | Désignation de l'article ou prestation                         |
| prix_unitaire_ht  | DECIMAL(12,2)                               | NOT NULL                      | Prix unitaire hors taxe                                        |
| unite             | VARCHAR(50)                                 | NULLABLE, DEFAULT 'unité'     | Unité (ex : heure, jour, pièce)                                |
| est_actif         | BOOLEAN                                     | NOT NULL, DEFAULT TRUE        | Indique si l'entrée est active                                 |
| date_creation     | DATETIME                                    | NOT NULL, DEFAULT NOW()       | Date de création                                               |
| date_modification | DATETIME                                    | NULLABLE, DEFAULT NOW()       | Date de dernière modification (onupdate, renseignée par l'application) |

# ------------------------------------------------------------------------------------------

## 3. PDP & statuts - ***4 TABLES***

### <u>***statut_facture***</u>
Référentiel des statuts de cycle de vie d'une facture.
| colonne     | type        | contrainte       | description                                                                                          |
| ----------- | ----------- | ---------------- | ---------------------------------------------------------------------------------------------------- |
| id          | INT         | PK, AUTO_INCREMENT | Identifiant technique auto-incrémenté                                                              |
| libelle     | VARCHAR(50) | UNIQUE, NOT NULL | Libellé du statut (ex : brouillon, validée, deposee_pdp, payée, en_retard, contestée, annulée)       |
| description | TEXT        | NULLABLE         | Description du statut                                                                                |

### <u>***evenement_pdp***</u>
Journal des événements provenant de la PDP ou du PPF (Chorus Pro) : trace les changements de statut fiscal d'une facture.
| colonne         | type         | contrainte                       | description                                             |
| --------------- | ------------ | -------------------------------- | ------------------------------------------------------- |
| id              | INT          | PK, AUTO_INCREMENT               | Identifiant technique auto-incrémenté                   |
| id_facture      | INT          | FK → facture.id, NOT NULL        | Facture concernée                                       |
| id_statut_avant | INT          | FK → statut_facture.id, NULLABLE | Statut source avant la transition (NULL si 1er statut)  |
| id_statut_apres | INT          | FK → statut_facture.id, NOT NULL | Statut cible atteint (émise, reçue, acceptée, rejetée…) |
| source          | VARCHAR(100) | NULLABLE                         | Source de l'événement (PDP, Chorus Pro, manuel…)        |
| message         | TEXT         | NULLABLE                         | Commentaire ou message retourné par le PDP              |
| date_evenement  | DATETIME     | NOT NULL, DEFAULT NOW()          | Date et heure de l'événement                            |

### <u>***statut_declaration***</u>
Référentiel des statuts de déclaration.
| colonne     | type        | contrainte       | description                                |
| ----------- | ----------- | ---------------- | ------------------------------------------ |
| id          | INT         | PK, AUTO_INCREMENT | Identifiant technique auto-incrémenté    |
| libelle     | VARCHAR(50) | UNIQUE, NOT NULL | ex : en_attente, envoyée, validée, rejetée |
| description | TEXT        | NULLABLE         | Description du statut                      |

### <u>***declaration***</u>
Déclarations récapitulatives de TVA / e-reporting envoyées à l'administration fiscale.
| colonne               | type          | contrainte                           | description                                    |
| --------------------- | ------------- | ------------------------------------ | ---------------------------------------------- |
| id                    | INT           | PK, AUTO_INCREMENT                   | Identifiant technique auto-incrémenté          |
| id_entreprise         | INT           | FK → entreprise.id, NOT NULL, INDEX  | Entreprise concernée                           |
| periode_debut         | DATE          | NOT NULL                             | Début de la période déclarée                   |
| periode_fin           | DATE          | NOT NULL                             | Fin de la période déclarée                     |
| montant_ht            | DECIMAL(12,2) | NOT NULL                             | Chiffre d'affaires HT de la période            |
| montant_tva           | DECIMAL(12,2) | NOT NULL                             | TVA collectée sur la période                   |
| montant_ttc           | DECIMAL(12,2) | NOT NULL                             | Montant TTC (contrôle de cohérence HT + TVA)   |
| id_statut_declaration | INT           | FK → statut_declaration.id, NOT NULL | Statut de la déclaration                       |
| reference_envoi       | VARCHAR(100)  | NULLABLE                             | Référence accusé de réception PDP/PPF          |
| date_envoi            | DATETIME      | NULLABLE                             | Date d'envoi au PDP                            |
| date_creation         | DATETIME      | NOT NULL, DEFAULT NOW()              | Date de création de la déclaration             |

# ------------------------------------------------------------------------------------------

## 4. Relances - ***2 TABLES***

### <u>***modele_relance***</u>
Modèle de relance paramétrable par entreprise.
| colonne         | type                              | contrainte                          | description                                    |
| --------------- | --------------------------------- | ----------------------------------- | ---------------------------------------------- |
| id              | INT                               | PK, AUTO_INCREMENT                  | Identifiant technique auto-incrémenté          |
| id_entreprise   | INT                               | FK → entreprise.id, NOT NULL, INDEX | Entreprise propriétaire du scénario            |
| libelle         | VARCHAR(100)                      | NOT NULL                            | Nom du scénario (ex : Relance standard)        |
| delai_jours     | INT                               | NOT NULL                            | Nombre de jours après échéance pour déclencher (> 0 validé côté application, pas de CHECK en base) |
| type_relance    | ENUM('AUTOMATIQUE', 'MANUELLE')   | NOT NULL, DEFAULT 'AUTOMATIQUE'     | Type de déclenchement                          |
| contenu_message | TEXT                              | NULLABLE                            | Gabarit de message personnalisable             |
| canal           | ENUM('DANS_APP', 'COURRIEL')      | NOT NULL, DEFAULT 'COURRIEL'        | Canal d'envoi                                  |

### <u>***relance***</u>
Historique des relances effectuées.
| colonne           | type                              | contrainte                          | description                                       |
| ----------------- | --------------------------------- | ----------------------------------- | ------------------------------------------------- |
| id                | INT                               | PK, AUTO_INCREMENT                  | Identifiant technique auto-incrémenté             |
| id_entreprise     | INT                               | FK → entreprise.id, NOT NULL, INDEX | Le tenant (isolation)                             |
| id_facture        | INT                               | FK → facture.id, NOT NULL, INDEX    | Facture concernée                                 |
| id_modele_relance | INT                               | FK → modele_relance.id, NULLABLE    | Modèle utilisé (NULL si manuelle ad hoc)          |
| id_utilisateur    | INT                               | FK → utilisateur.id, NULLABLE       | Utilisateur déclencheur (NULL si automatique)     |
| type_relance      | ENUM('AUTOMATIQUE', 'MANUELLE')   | NOT NULL                            | Type de déclenchement                             |
| date_relance      | DATETIME                          | NOT NULL, DEFAULT NOW()             | Date et heure de la relance                       |
| statut            | ENUM('ENVOYEE', 'ECHOUEE')        | NOT NULL, DEFAULT 'ENVOYEE'         | Résultat de l'envoi                               |
| message_envoye    | TEXT                              | NULLABLE                            | Message réel envoyé après substitution du gabarit |
| erreur            | VARCHAR(255)                      | NULLABLE                            | Motif d'échec si statut = échouée                 |

# ------------------------------------------------------------------------------------------

## 5. Audit & notifications - ***3 TABLES***

### <u>***journal_audit***</u>
Trace immuable de toutes les actions (création, modification, suppression) sur les entités, isolée par entreprise.
| colonne           | type                                          | contrainte                          | description                                           |
| ----------------- | --------------------------------------------- | ----------------------------------- | ----------------------------------------------------- |
| id                | INT                                           | PK, AUTO_INCREMENT                  | Identifiant technique auto-incrémenté                 |
| id_entreprise     | INT                                           | FK → entreprise.id, NULLABLE, INDEX | Entreprise concernée (NULL si action système globale) |
| id_utilisateur    | INT                                           | FK → utilisateur.id, NULLABLE       | Utilisateur ayant effectué l'action (NULL si système) |
| entite            | VARCHAR(50)                                   | NOT NULL                            | Table concernée (ex : facture, client, utilisateur)   |
| id_entite         | INT                                           | NOT NULL                            | Identifiant de l'enregistrement concerné              |
| action            | ENUM('CREATION', 'MODIFICATION', 'SUPPRESSION') | NOT NULL                          | Type d'action tracée                                  |
| anciennes_valeurs | JSON                                          | NULLABLE                            | Données avant modification                            |
| nouvelles_valeurs | JSON                                          | NULLABLE                            | Données après modification                            |
| adresse_ip        | VARCHAR(45)                                   | NULLABLE                            | Adresse IP de l'utilisateur                           |
| date_action       | DATETIME                                      | NOT NULL, DEFAULT NOW()             | Date et heure de l'action                             |

### <u>***notification***</u>
Instance d'une notification adressée à un utilisateur, généralement dans le contexte d'une entreprise.
| colonne         | type                          | contrainte                          | description                                         |
| --------------- | ----------------------------- | ----------------------------------- | --------------------------------------------------- |
| id              | INT                           | PK, AUTO_INCREMENT                  | Identifiant technique auto-incrémenté               |
| id_utilisateur  | INT                           | FK → utilisateur.id, NOT NULL, INDEX | Utilisateur destinataire                           |
| id_entreprise   | INT                           | FK → entreprise.id, NULLABLE, INDEX | Entreprise concernée (contexte de la notification)  |
| id_type         | INT                           | FK → type_notification.id, NOT NULL | Type de la notification                             |
| message         | TEXT                          | NOT NULL                            | Contenu de la notification                          |
| canal           | ENUM('DANS_APP', 'COURRIEL')  | NOT NULL, DEFAULT 'DANS_APP'        | Canal de diffusion                                  |
| est_lu          | BOOLEAN                       | NOT NULL, DEFAULT FALSE             | Indique si la notification a été lue                |
| date_creation   | DATETIME                      | NOT NULL, DEFAULT NOW()             | Date de création                                    |
| date_lecture    | DATETIME                      | NULLABLE                            | Date à laquelle la notification a été lue           |
| lien_action     | VARCHAR(255)                  | NULLABLE                            | Lien vers la ressource concernée (ex : /factures/42) |
| date_expiration | DATETIME                      | NULLABLE                            | Date d'expiration de la notification                |

### <u>***type_notification***</u>
Référentiel des types de notifications.
| colonne     | type        | contrainte             | description                                               |
| ----------- | ----------- | ---------------------- | --------------------------------------------------------- |
| id          | INT         | PK, AUTO_INCREMENT     | Identifiant technique auto-incrémenté                     |
| libelle     | VARCHAR(50) | UNIQUE, NOT NULL       | Ex : facture_acceptee, relance_echouee, abonnement_expire |
| description | TEXT        | NULLABLE               | Description du type de notification                       |
| est_actif   | BOOLEAN     | NOT NULL, DEFAULT TRUE | Indique si le type est utilisable                         |
