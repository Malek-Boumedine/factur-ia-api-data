# CHANGELOG

<!-- version list -->

## v1.10.0 (2026-07-30)

### Features

- **choruspro**: Transmission des factures Factur-X à Chorus Pro (sandbox)
  ([`add96dc`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/add96dc38d2278313d0cbf7bdeada3870c7d14b6))

- **documents**: Réception de la date d'échéance extraite par l'OCR
  ([`f5f6a23`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/f5f6a23e4b9f9060e13a83282b0885a669959a6c))

- **facturx**: Génération du fichier Factur-X pour les factures validées
  ([`36c774e`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/36c774e42bf89d77f3144cde1a9ef668376aa23b))

- **facturx**: Validation de conformité préalable au profil MINIMUM
  ([`476d18d`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/476d18df215c90f66c928cd6ebc90b0c4e20ba91))

- **formes-juridiques**: Exposition du référentiel des formes juridiques
  ([`97902bd`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/97902bdfb575bbf26c44a5ae51175c7659fcf84c))


## v1.9.0 (2026-07-28)

### Bug Fixes

- **clients**: Unicité du SIRET et du numéro de TVA par entreprise
  ([`cc7c452`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/cc7c4522c5d43046c29a23b85b068a1d1575c19d))

- **factures**: Unicité du numéro de facture par entreprise et non plus globale
  ([`aff5cc4`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/aff5cc4b4b39c1d21a890a205fa90a758e31d1e4))

### Features

- **administration**: Gestion des utilisateurs, entreprises et abonnements par l'admin plateforme
  ([`5ca5f96`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/5ca5f968227185a37f734d5ca24a12c60b082991))

- **documents**: Liste paginée des documents et consultation du fichier original
  ([`3f7cfd7`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/3f7cfd76a2d790f671d5be6a98d1f05eb1696e30))

- **documents**: Réception et exposition du score par champ et du type de document OCR
  ([`2e8795c`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/2e8795c7ee7dc949c426bec9679843317c588698))

- **documents**: Suppression d'un document uploadé avec protection des factures liées
  ([`8c77cce`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/8c77cceb493301cc5a615df39377c3c373390db3))

- **factures**: Exposition du libellé de statut et filtre par famille sur la liste
  ([`5f45bbd`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/5f45bbd2205164323cc2b0a218818b707eb19f64))

- **factures**: Retry sur collision de numérotation lors de validations simultanées
  ([`af01ac5`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/af01ac5f44476dde55dec24f255ac64a1b961527))

- **factures**: Route d'agrégation des statistiques calculées en SQL
  ([`18a0d49`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/18a0d493c97030ebe2c17eca98231a9adb9da04b))


## v1.8.0 (2026-07-27)

### Bug Fixes

- **factures**: Corrige la suppression d'un brouillon bloquée par une contrainte de clé étrangère
  ([`afb1700`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/afb17007c62b4a40a6ea96b29d4a36d969440052))

- **factures**: Recopie les snapshots SIRET et client sur l'avoir généré
  ([`bf6d793`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/bf6d7939cd530f92232d67886c12b08e807c696f))

- **factures**: Transmet les SIRET extraits jusqu'au brouillon OCR
  ([`2666d75`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/2666d75ed3424db3bc39f16f6197577ea9225839))

### Features

- **documents**: Déclenche l'extraction IA après l'upload d'un document
  ([`b08990a`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/b08990a874290428ada63f0c03cd23dcca67e68b))

- **documents**: Route de suivi de l'état d'un document
  ([`f1eef4a`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/f1eef4a62b33cda7f6e33597ef266097a928d8c6))

- **documents**: Réconcilie le SIRET émetteur à la création du brouillon OCR
  ([`11264a9`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/11264a99d6431bcc67dd31176239a4b0ba7c25ea))

- **entreprises**: Route de lecture de l'entreprise active
  ([`c3ee756`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/c3ee7567b332e32820670b4b4e5df07ad868d158))

- **factures**: Numérotation distincte des avoirs (série AV-)
  ([`72f8480`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/72f84803ef7d2ed0c9cd7083fa4363d1f8a12ec2))

- **factures**: Route de détail d'une facture avec ses lignes
  ([`79143f7`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/79143f79c1be70d81f6e2f73ab949aa526d98edf))

- **factures**: Route de liste avec recherche, filtres et pagination
  ([`306a716`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/306a7165ba196b1bd98d701a8e2985923894c46c))

- **factures**: SIRET émetteur et destinataire éditables sur un brouillon
  ([`cbdfc29`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/cbdfc298d109623b15537bcf0e3cbf63dc9ea1fb))

- **factures**: Suppression d'un brouillon de facture
  ([`af51ec6`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/af51ec6b49d02a45acf06e32a6a55ad103dd91bd))

- **factures**: Édition d'un brouillon et contrôle de complétude à la validation
  ([`d8d8595`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/d8d8595032df4bc722b11a34b55c8d1b149f395e))


## v1.7.0 (2026-07-03)

### Features

- **abonnements**: Rend GET /abonnements/ public pour l'affichage des tarifs
  ([`f256401`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/f2564010f988615fe1f31e3780b89d38ffe08cc5))

- **utilisateurs**: Endpoint de changement d'email (utilisateur connecté)
  ([`1c56cd2`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/1c56cd220c927e5927be727f04835e19c02f5149))

- **utilisateurs**: Endpoint de changement de mot de passe (utilisateur connecté)
  ([`6f0c406`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/6f0c4063b4b2ed9dcdf08c7c74825b222d324c1a))

### Refactoring

- **utilisateurs**: Restreint les champs modifiables via PATCH /me
  ([`5b3940a`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/5b3940a8ac5bd05bc08a330fc97b7fcf247aae7e))


## v1.6.0 (2026-07-03)

### Bug Fixes

- **abonnements**: Renvoie 409 au lieu de supprimer un plan encore souscrit
  ([`26fbef2`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/26fbef203f505287e422feb971ff3cba5f303588))

- **auth**: Scope la vérification RBAC à l'entreprise active
  ([`0f26e4e`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/0f26e4e1feb9987ef66050eaf51520d391797a8d))

- **clients**: Désactivation autorisée et 409 sur doublon SIRET/TVA
  ([`6d1a4f2`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/6d1a4f20bb30e4e522ee23e516a0b5f3e8410cde))

- **seeds**: Modification du script de seed pour insérer uniquement les données manquantes et éviter
  les erreurs
  ([`3ce386c`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/3ce386cdb72956dcbc6c2533e300b8b910ff2ace))

### Features

- **abonnements**: Changement de plan de l'entreprise active
  ([`36d6105`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/36d6105808b9141c99eaf01f596bbc84a7a38148))

- **abonnements**: Expiration paresseuse et prolongation des abonnements
  ([`c3844d3`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/c3844d3c237daa348bb30014237580b88df0c267))

- **auth**: Administrateur de plateforme et compte racine protégé
  ([`31f97aa`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/31f97aaba33c747392ad9830fb820b4f69db2787))

- **taux-tva**: CRUD du référentiel des taux de TVA
  ([`e7d99f2`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/e7d99f2e2eeef882e3380bb1b66e414bdcc87c34))

- **utilisateurs**: Bloque l'ajout d'utilisateurs au-delà de la limite du plan
  ([`b710b21`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/b710b210020cf92205da5194f51a3b8a68f2251f))

- **utilisateurs**: Expose compte_protege dans UtilisateurRead
  ([`a6cb440`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/a6cb4408fb6683a51614be818882a68bda9e2389))

- **utilisateurs**: Expose est_admin de l'entreprise active sur GET /me
  ([`848858b`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/848858bad01c8b7be1f53bfedb69d035c91596aa))

- **utilisateurs**: Recherche d'utilisateur par email et exposition du statut admin plateforme
  ([`943b7e8`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/943b7e87ea2e0510716f431b125b8fd605c414e2))

### Testing

- **ci**: Fournit une config de test factice pour la collecte pytest
  ([`913dfae`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/913dfaef9fd721e43bb3b47f02f66806181ca755))


## v1.5.0 (2026-07-02)

### Bug Fixes

- **clients**: Peuple date_modification à l'insert pour clients et catalogue
  ([`93490ba`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/93490ba305eab9b61985e76fdd658492c9ff6fb1))

### Features

- **api**: Recherche, filtres et pagination sur les endpoints de liste
  ([`c5ecf60`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/c5ecf60ef7ae5f9a3a04bea3bf3bf019e51343bf))

- **auth**: Flux de réinitialisation de mot de passe
  ([`a5bd3e8`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/a5bd3e82b73df87b125ee1d70313a1b66907a28b))

- **entreprises**: Endpoint d'onboarding pour créer son premier espace de travail
  ([`d5bb0b5`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/d5bb0b55ea2236856be4392771f596af3f37884f))


## v1.4.0 (2026-06-30)

### Bug Fixes

- Adaptation de plusieurs modèles à ceux du schema de la bdd
  ([`9515b83`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/9515b83f8f0469a7ccf12385228a559475a52340))

- **utilisateurs**: Expose est_admin en lecture et assouplit les champs d'adresse
  ([`1eb4404`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/1eb4404efc5bbdaaf89fe7d176e580cd42681ef7))

### Chores

- **contracts**: Ajoute l'export OpenAPI et le contrat versionné contracts/openapi.json
  ([`570207d`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/570207df7265a58328be44967e49f21697787358))

### Features

- **factures**: Lien FK avoir->facture d'origine, montants négatifs et callback OCR auto
  ([`d329cc3`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/d329cc363c7c38def57aefd750c7e8c54300313f))


## v1.3.0 (2026-06-04)

### Features

- **clients**: Création de l'endpoint de recherche SIRENE/SIRET
  ([`83b5af6`](https://github.com/Malek-Boumedine/factur-ia-api-data/commit/83b5af6597ff9484b534281b2b783cd488c1868d))


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
