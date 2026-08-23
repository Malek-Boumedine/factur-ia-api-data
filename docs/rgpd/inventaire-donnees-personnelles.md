# Inventaire des données à caractère personnel

Base de travail pour le registre des traitements (article 30 RGPD).
Inventaire établi à partir des tables **réellement implémentées** (modèles SQLModel du code, voir `docs/modele-de-donnees.md`) — pas de l'ancienne référence `liste_tables.md`.
Une donnée à caractère personnel est toute information se rapportant à une personne physique identifiée ou identifiable (article 4.1 RGPD).

## Rappel : personne physique vs personne morale

Le RGPD ne protège que les personnes physiques. La distinction traverse tout cet inventaire :

- Les données de la table `utilisateur` concernent **toujours** des personnes physiques : ce sont des données personnelles sans ambiguïté.
- Les données des tables `entreprise` et `client` sont **ambivalentes** : la raison sociale, le SIRET ou l'adresse d'une SAS ne sont pas des données personnelles ; mais pour un **entrepreneur individuel** (auto-entrepreneur, EI, profession libérale), la « raison sociale » est le nom de la personne, le SIRET l'identifie directement (position CNIL constante) et l'adresse professionnelle est souvent son domicile.
- Le schéma **ne permet pas de distinguer** en base un client personne morale d'un client entrepreneur individuel (pas de champ forme juridique sur `client` ; `entreprise.id_forme_juridique` existe mais est nullable). En pratique, le registre doit donc traiter les colonnes concernées comme **potentiellement personnelles** et appliquer les mêmes garanties à tous les enregistrements.

## Catégories utilisées

- **Nature** : identification, contact, bancaire, connexion/technique, sécurité (credentials), vie professionnelle, contenu libre.
- **Sensibilité** : aucune donnée dite « sensible » au sens de l'article 9 (santé, opinions…) n'est traitée ; en revanche l'**IBAN** (donnée bancaire) et l'**adresse IP** (donnée de connexion) appellent une vigilance particulière (risque en cas de fuite, encadrement CNIL).

# ------------------------------------------------------------------------------------------

## 1. `utilisateur` — comptes de la plateforme

**Traitement de rattachement** : gestion des comptes utilisateurs et authentification.
**Personnes concernées** : utilisateurs de la plateforme (toujours des personnes physiques).

| colonne                 | nature                  | sensibilité / remarque                                                              |
| ----------------------- | ----------------------- | ----------------------------------------------------------------------------------- |
| nom, prenom             | identification          | Données identifiantes directes                                                      |
| adresse, adresse_complement, code_postal, ville | contact | Adresse postale personnelle (colonnes devenues facultatives : minimisation effective) |
| email                   | identification, contact | Identifiant de connexion — donnée pivot du compte                                   |
| telephone               | contact                 | Facultatif                                                                          |
| hash_mot_de_passe       | sécurité                | **Protégé : hash bcrypt avec sel**, jamais le mot de passe en clair                 |
| date_derniere_connexion | connexion               | Donnée de traçabilité du comportement de connexion                                  |
| date_creation, date_modification | technique      | Métadonnées de cycle de vie du compte                                               |
| est_actif, admin_plateforme, compte_protege | vie du compte | Statut et privilèges du compte (donnée personnelle car rattachée à la personne) |

## 2. `reinitialisation_mot_de_passe` — tokens de réinitialisation

**Traitement de rattachement** : gestion des comptes (procédure de mot de passe oublié).
**Personnes concernées** : utilisateurs.

| colonne          | nature   | sensibilité / remarque                                                                  |
| ---------------- | -------- | --------------------------------------------------------------------------------------- |
| id_utilisateur   | identification indirecte | Rattache le token à une personne                                         |
| token_hash       | sécurité | **Protégé : seul le hash SHA-256 du token est stocké**, jamais le token en clair         |
| date_expiration, date_utilisation, date_creation | connexion | Traçabilité de la procédure (usage unique, durée de vie limitée) |

## 3. `utilisateur_entreprise` et `utilisateur_role` — appartenances et rôles

**Traitement de rattachement** : gestion des comptes et des habilitations.
**Personnes concernées** : utilisateurs.
Ces pivots ne contiennent que des identifiants techniques, mais ils révèlent des informations rattachées à une personne : à quelles entreprises elle appartient, avec quels rôles et privilèges (`est_admin`, rôle global ou local). Ce sont des données personnelles **indirectes** (vie professionnelle / habilitations), à mentionner dans le registre au titre du traitement de gestion des accès.

## 4. `entreprise` — espaces de travail (tenants)

**Traitement de rattachement** : gestion des comptes et des espaces entreprise.
**Personnes concernées** : entrepreneurs individuels uniquement (une personne morale n'est pas concernée par le RGPD).

| colonne          | nature                        | sensibilité / remarque                                                                   |
| ---------------- | ----------------------------- | ----------------------------------------------------------------------------------------- |
| nom_entreprise   | identification (si EI)        | Pour un entrepreneur individuel, contient typiquement le nom de la personne               |
| siret            | identification (si EI)        | Le SIRET d'un entrepreneur individuel identifie directement la personne physique          |
| motif_suspension | contenu libre                 | Champ texte saisi par un admin : peut mentionner des faits relatifs à une personne — à rédiger de façon factuelle et minimale |

## 5. `client` — référentiel client de chaque entreprise

**Traitement de rattachement** : gestion de la relation client et facturation.
**Personnes concernées** : clients entrepreneurs individuels, et contacts personnes physiques chez les clients personnes morales (un email ou un téléphone nominatif reste une donnée personnelle même chez une SAS).

| colonne                | nature                    | sensibilité / remarque                                                                 |
| ---------------------- | ------------------------- | --------------------------------------------------------------------------------------- |
| raison_sociale         | identification (si EI)    | Nom de la personne pour un entrepreneur individuel                                       |
| siret, numero_tva      | identification (si EI)    | Identifient directement un entrepreneur individuel                                       |
| adresse, adresse_complement, code_postal, ville | contact | Souvent le domicile pour un entrepreneur individuel                     |
| email                  | contact                   | Peut être nominatif (prenom.nom@…) même chez une personne morale                         |
| telephone              | contact                   | Idem : ligne directe potentiellement personnelle                                         |
| id_createur, id_modificateur | traçabilité         | Rattachent des actions à des utilisateurs (personnes physiques)                          |

## 6. `document` — fichiers uploadés

**Traitement de rattachement** : extraction OCR (import de factures).
**Personnes concernées** : utilisateurs (auteur de l'upload) et, indirectement, personnes mentionnées dans le fichier.

| colonne        | nature         | sensibilité / remarque                                                                          |
| -------------- | -------------- | ------------------------------------------------------------------------------------------------ |
| id_utilisateur | traçabilité    | Auteur de l'upload                                                                               |
| nom_original   | contenu libre  | Nom de fichier choisi par l'utilisateur : peut contenir un nom de personne (« facture_dupont.pdf ») |
| nom_fichier    | technique      | Nom de stockage interne                                                                          |

Le fichier lui-même (PDF/image d'une facture) est stocké hors base ; son contenu relève des mêmes considérations que `extraction_ocr.contenu_brut` ci-dessous et doit être couvert par le registre au titre du même traitement.

## 7. `extraction_ocr` — résultats OCR

**Traitement de rattachement** : extraction OCR de factures par l'API IA.
**Personnes concernées** : toute personne mentionnée sur la facture analysée (émetteur, client, contacts).

| colonne       | nature        | sensibilité / remarque                                                                                       |
| ------------- | ------------- | ------------------------------------------------------------------------------------------------------------ |
| contenu_brut  | **concentration de données personnelles** | JSON brut retourné par l'IA : peut contenir nom, adresse, email, téléphone, SIRET, IBAN de toutes les parties de la facture. C'est la colonne la plus délicate de la base. **Protection partielle : l'IBAN y est masqué dès l'ingestion** (`src/documents/service.py`) et l'a été rétroactivement (migration `f4b8c2d91e07`) ; les autres champs y restent en clair |
| par_champ     | technique     | Scores de confiance par champ : les **clés** énumèrent les champs extraits mais les valeurs sont des scores, pas des données personnelles |
| type_document | technique     | Type détecté, non personnel                                                                                   |

À signaler dans le registre : cette table matérialise aussi un **transfert vers un sous-traitant** (l'API IA/OCR reçoit le document complet) — à documenter au titre des destinataires.

## 8. `facture` — factures et avoirs

**Traitement de rattachement** : facturation, et transmission Chorus Pro pour les colonnes de dépôt.
**Personnes concernées** : clients entrepreneurs individuels (et émetteur EI via son SIRET).

| colonne                  | nature                 | sensibilité / remarque                                                                           |
| ------------------------ | ---------------------- | ------------------------------------------------------------------------------------------------- |
| iban                     | **bancaire — vigilance particulière** | **Protégé : chiffré au repos (Fernet, clé `IBAN_ENCRYPTION_KEY`)** — token illisible en cas de dump SQL ; **masqué à l'affichage** dans les réponses API (`FR76 •••• … 0189`, 8 caractères réels visibles au plus) |
| snapshot_client          | identification, contact (si EI) | JSON figé à la validation : raison_sociale, adresse, code_postal, ville du client. Données client dupliquées et **immuables** (inaltérabilité comptable) : elles survivent à la modification ou suppression de la fiche client — à prendre en compte pour les durées de conservation et le droit à l'effacement (la base légale « obligation comptable/fiscale » prime) |
| siret_emetteur, siret_destinataire | identification (si EI) | Snapshots de SIRET : identifient un entrepreneur individuel                              |
| numero_flux_depot_chorus, date_transmission_chorus | technique | Métadonnées du dépôt Chorus Pro : matérialisent la **transmission des données de facture à un tiers** (PPF/PDP) — destinataire à documenter au registre |
| notes, reference_commande | contenu libre         | Champs libres : peuvent contenir des mentions nominatives                                         |
| id_createur              | traçabilité            | Utilisateur auteur de la facture                                                                  |

## 9. `facture_ligne` — lignes de facture

**Traitement de rattachement** : facturation.
La colonne `designation` (contenu libre) peut mentionner une personne (ex : « prestation de M. X ») ; les autres colonnes sont purement comptables. Donnée personnelle marginale, à couvrir par le traitement facturation.

## 10. `paiement` — règlements reçus

**Traitement de rattachement** : suivi des paiements.

| colonne     | nature        | sensibilité / remarque                                                            |
| ----------- | ------------- | ---------------------------------------------------------------------------------- |
| reference   | bancaire (indirect) | Référence de virement ou n° de chèque : rattachable au payeur                |
| notes       | contenu libre | Peut contenir des mentions nominatives                                             |
| id_createur | traçabilité   | Utilisateur ayant enregistré le paiement                                           |

## 11. `journal_audit` — traçabilité

**Traitement de rattachement** : audit et traçabilité des actions (intérêt légitime / obligations de sécurité).
**Personnes concernées** : utilisateurs, et toute personne dont les données figurent dans les entités tracées.

| colonne                              | nature                    | sensibilité / remarque                                                                     |
| ------------------------------------ | ------------------------- | ------------------------------------------------------------------------------------------- |
| adresse_ip                           | **connexion — vigilance particulière** | L'adresse IP est une donnée personnelle au sens RGPD (CJUE, Breyer) ; stockée en clair, VARCHAR(45) (IPv4/IPv6) |
| id_utilisateur                       | identification indirecte  | Auteur de l'action                                                                          |
| anciennes_valeurs, nouvelles_valeurs | **concentration de données personnelles** | JSON avant/après : **répliquent les données personnelles des entités modifiées** (fiche client, utilisateur…), y compris des valeurs depuis supprimées de la table d'origine. Effet mémoire à traiter dans les durées de conservation et le droit à l'effacement |
| date_action, entite, id_entite       | traçabilité               | Contexte de l'action                                                                        |

## 12. `notification` — messages aux utilisateurs

**Traitement de rattachement** : notifications applicatives et courriel.

| colonne                  | nature        | sensibilité / remarque                                              |
| ------------------------ | ------------- | -------------------------------------------------------------------- |
| id_utilisateur           | identification indirecte | Destinataire                                              |
| message                  | contenu libre | Peut citer des noms (client, facture concernée…)                     |
| est_lu, date_lecture     | comportement  | Traçabilité de lecture, rattachée à la personne                      |
| lien_action, date_expiration | technique | Non personnels en eux-mêmes                                          |

## 13. `relance` — relances de paiement

**Traitement de rattachement** : relance des factures impayées.

| colonne        | nature        | sensibilité / remarque                                                          |
| -------------- | ------------- | -------------------------------------------------------------------------------- |
| message_envoye | contenu libre | Message réellement envoyé : contient typiquement le nom et les coordonnées du client relancé |
| erreur         | technique/contenu libre | Motif d'échec : peut contenir un email (« Email non renseigné », adresse invalide…) |
| id_utilisateur | traçabilité   | Déclencheur humain d'une relance manuelle                                        |

## 14. `evenement_pdp` — cycle de vie fiscal

**Traitement de rattachement** : transmission PDP/Chorus Pro.
La colonne `message` (texte libre retourné par la plateforme) peut mentionner des données de la facture (SIRET, raison sociale d'un EI). Donnée personnelle marginale, à couvrir par le traitement de transmission.

## 15. `catalogue_produits`

Seule la colonne `id_utilisateur` (créateur de l'entrée) constitue une donnée personnelle indirecte (traçabilité). Le reste est purement métier.

# ------------------------------------------------------------------------------------------

## Tables sans donnée personnelle

Référentiels purs, sans lien avec une personne physique : `ref_forme_juridique`, `role`, `permission`, `permission_role`, `abonnement`, `taux_tva`, `statut_facture`, `statut_declaration`, `type_notification`.
`entreprise_abonnement` et `declaration` ne portent que des données financières agrégées rattachées à une entreprise ; elles ne deviennent indirectement personnelles que si l'entreprise est un entrepreneur individuel (le CA déclaré d'un auto-entrepreneur est une information sur la personne).

## Synthèse des données appelant une vigilance particulière

1. **`facture.iban`** — donnée bancaire. Protégée : chiffrement Fernet au repos + masquage systématique à l'affichage.
2. **`extraction_ocr.contenu_brut`** — concentration de données personnelles issues de l'OCR (nom, adresse, SIRET, coordonnées de toutes les parties). Protection partielle : seul l'IBAN y est masqué ; le reste est en clair.
3. **`journal_audit.adresse_ip`** — donnée de connexion, en clair.
4. **`journal_audit.anciennes_valeurs` / `nouvelles_valeurs`** — réplication historique des données personnelles des entités modifiées, y compris supprimées.
5. **`facture.snapshot_client`** — données client figées et immuables (inaltérabilité comptable) : base légale et durée de conservation spécifiques à documenter.

## Mesures de protection déjà en place (pour la partie « mesures de sécurité » du registre)

- **Mots de passe** : hash bcrypt avec sel (`src/core/security.py`) ; jamais de stockage en clair.
- **IBAN de facture** : chiffrement au repos Fernet (`src/core/crypto.py`, type `EncryptedStr`) — un dump SQL ne révèle que des tokens ; clé symétrique en variable d'environnement `IBAN_ENCRYPTION_KEY` (limite documentée : ne protège pas contre une compromission du serveur applicatif ; évolution prévue vers un KMS).
- **IBAN à l'affichage** : masquage systématique dans les réponses API (`mask_iban`, au plus 8 caractères réels visibles).
- **IBAN dans l'OCR** : masqué dans `extraction_ocr.contenu_brut` dès l'ingestion, et rétroactivement sur l'existant par la migration `f4b8c2d91e07`.
- **Tokens de réinitialisation** : seul le hash SHA-256 est persisté, usage unique, durée de vie limitée, suppression en cascade avec l'utilisateur.
- **Convention de code** : interdiction de logger `facture.iban` et le payload OCR brut (documentée dans `src/core/crypto.py`).
- **Cloisonnement multi-tenant** : toutes les données métier sont isolées par `id_entreprise` (contrôle d'accès par entreprise sur chaque requête).
- **Minimisation** : l'adresse postale de l'utilisateur est devenue facultative (migration `eb848f5a63ad`).
