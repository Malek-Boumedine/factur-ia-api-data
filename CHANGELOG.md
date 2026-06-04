# CHANGELOG

<!-- version list -->

## v1.2.0 (2026-06-03)

### Features

- **documents**: Création du webhook de retour OCR
  ([`eaf2c87`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/eaf2c872d5bcf0b00ae0843f5850204dcfab1ebd))

- **documents**: Implémentation de l'upload de fichiers
  ([`22667cc`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/22667cc5b70869973783f7db3875af387af8d734))


## v1.1.0 (2026-06-03)

### Bug Fixes

- **auth**: Mise à jour de la table utilisateur_role (clé primaire et multi-tenant)
  ([`bee9193`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/bee9193235b43ebc8dbfbbb5cb273745ec58b0a6))

- **security**: Retrait des cast redondants pour mypy
  ([`e179969`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/e179969a7d07105c85f6a99faad43ef35727f133))

### Features

- **abonnements**: Implémentation des schémas Pydantic et du router CRUD
  ([`c8f64a6`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/c8f64a65fd4813d0774215d407f8734af49567c9))

- **auth**: Ajout des dépendances RBAC et d'isolation par abonnement
  ([`e234dcc`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/e234dccb8aafe6867c7927b6f7013fb1694d57ef))

- **auth**: Implémentation de l'authentification JWT et de la sécurité des mots de passe
  ([`62dbf27`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/62dbf270643ff61c2daabdc333e731a6443288f6))

- **catalogue_produits**: Implémentation du CRUD catalogue et mise à jour TVA
  ([`a4bfca4`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/a4bfca45641d70fa0dd7e05daa133aaf5654dce5))

- **clients**: Implémentation des schémas Pydantic et du router CRUD
  ([`ae0e8ce`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/ae0e8cecad297bdad5e3e670166f29a0db25fa9b))

- **core**: Ajout du seed pour les tables de référence
  ([`251a833`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/251a83363a0df89ecfdf941955246f5513ab48ad))

- **db**: Initialisation Alembic async et migration initiale
  ([`7d0f547`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/7d0f5473c1e16e8e6b8dfba90945a0a2fc857511))

- **factures**: Implémentation de la création de facture (brouillon) et logique de calcul métier
  ([`8fa15a0`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/8fa15a0c396092d9552985b3a974fd399c3615df))

- **factures**: Implémentation de la génération des avoirs
  ([`20540e3`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/20540e36819f148c1c34b18346d21ab000a26149))

- **factures**: Implémentation de la validation de facture avec inaltérabilité (snapshot) et
  numérotation
  ([`b4df02b`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/b4df02b5ac7b0aba2434f2ed93de5a9e9c4983e7))

- **relances**: Ajout de la clé id_entreprise pour l'isolation multi-tenant
  ([`bc693ab`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/bc693ab6b165fb09d3e2fc5deb0da541c5790b66))

- **utilisateurs**: Inscription publique, CRUD et refonte adresses
  ([`8714d2b`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/8714d2bc361362cc3471e2c7e2f90cc774505d78))

### Refactoring

- **core**: Migration vers une architecture multi-tenant par entreprise
  ([`b2e1ce0`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/b2e1ce0d6042708bd327d95d9117b89d4672543a))


## v1.0.1 (2026-04-10)

### Bug Fixes

- Test du pipeline de release avec PAT
  ([`933633a`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/933633a6bc99f582fc483d7a64a263d938dcf6b6))


## v1.0.0 (2026-04-10)

- Initial Release
