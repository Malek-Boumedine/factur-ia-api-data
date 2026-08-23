# Registre des activités de traitement (RGPD)

Ce registre répertorie la façon dont l'application Factur-IA gère les données personnelles.

**Contexte :** Ce projet est réalisé dans le cadre d'une certification. Il n'y a pour le moment aucune structure juridique commerciale qui exploite l'application. Les prérequis légaux pour un passage en production réelle sont listés à la fin de ce document.

---

## 1. Vue d'ensemble et Partenaires

L'application est totalement cloisonnée : les données d'une entreprise ne sont visibles que par ses propres utilisateurs.
Je fais appel à des services tiers (sous-traitants) pour faire fonctionner l'application :
*   **Hébergement :** Google Cloud Platform (GCP).
*   **Intelligence Artificielle (OCR) :** Groq (fournisseur de l'API LLM).
*   **Autorités publiques :** Chorus Pro / Portail Public de Facturation pour l'envoi légal des factures.

**Note sur les transferts hors Europe :**
Actuellement, en phase de développement, GCP et Groq sont des fournisseurs américains (choisis pour leur accessibilité technique).
*La trajectoire pour la mise en production commerciale* prévoit une bascule stricte vers un hébergeur européen et une IA européenne (type Mistral) pour garantir un hébergement 100% UE. L'architecture du code a été pensée pour rendre ce remplacement très simple.

---

## 2. Traitements liés à l'application (Gestion interne)

Cette section couvre les données nécessaires au bon fonctionnement de la plateforme elle-même.

**A. Gestion des comptes utilisateurs**
*   **Données :** Noms, emails, mots de passe (hashés), rôles.
*   **Objectif :** Permettre la connexion et gérer les droits.
*   **Conservation :** Jusqu'à 3 ans après la dernière connexion, puis le compte est anonymisé. Les liens de mot de passe oublié sont supprimés 30 jours après expiration.

**B. Notifications**
*   **Données :** Messages d'alerte dans l'application (ex: facture traitée).
*   **Objectif :** Informer l'utilisateur des événements importants.
*   **Conservation :** 1 an après la lecture ou l'expiration.

**C. Traçabilité (Journal d'audit)**
*   **Données :** Adresses IP, identifiants des utilisateurs, traces exactes des modifications.
*   **Objectif :** Sécuriser la plateforme et prouver qui a modifié une pièce comptable.
*   **Conservation :** 2 ans.

---

## 3. Traitements métiers (Les données des clients)

Cette section couvre les données que les utilisateurs saisissent dans l'application pour gérer leur activité.

**A. Carnet d'adresses (Fiches clients)**
*   **Données :** SIRET, contacts, adresses des clients.
*   **Objectif :** Gérer la relation client et préparer la facturation.
*   **Conservation :**
    *   Si le client a des factures : 10 ans après la dernière facture.
    *   Si le client n'a aucune facture : 3 ans après désactivation de la fiche.

**B. Facturation et Envoi Chorus Pro**
*   **Données :** Montants, SIRET, IBAN (chiffré), statut de transmission.
*   **Objectif :** Créer des factures légales et les envoyer à l'État (Chorus Pro).
*   **Conservation :** 10 ans (C'est une obligation légale stricte du Code de commerce).

**C. Analyse IA des factures (OCR)**
*   **Données :** Les fichiers PDF uploadés et le texte brut extrait par l'IA (qui peut contenir n'importe quelle donnée personnelle présente sur la facture).
*   **Objectif :** Pré-remplir automatiquement les factures pour faire gagner du temps.
*   **Conservation :** 2 ans maximum pour le PDF et les données extraites. (L'IBAN détecté par l'IA est d'ailleurs masqué immédiatement).

**D. Relances des impayés**
*   **Données :** Historique des messages envoyés aux clients retardataires.
*   **Objectif :** Suivre le recouvrement.
*   **Conservation :** 3 ans.

**E. Déclarations fiscales**
*   **Données :** Chiffre d'affaires, montants de TVA. (Devient une donnée personnelle si l'utilisateur est auto-entrepreneur).
*   **Objectif :** Suivi légal et fiscal.
*   **Conservation :** 10 ans.

---

## 4. Prérequis avant mise en production (Checklist)

Étant un projet de certification, plusieurs étapes légales devront être franchies si l'application est commercialisée un jour :

1.  **Création de l'entreprise :** Fonder la structure juridique qui assumera le rôle de Responsable de Traitement.
2.  **Contrats clients :** Rédiger les Conditions Générales et un contrat de sous-traitance (Article 28 du RGPD) clair pour les utilisateurs.
3.  **Transparence :** Publier une véritable Politique de Confidentialité.
4.  **Souveraineté des données :** Finaliser la migration vers un modèle d'IA européen (Mistral) et un cloud souverain pour stopper les flux de données vers les États-Unis.
5.  **Audit des fournisseurs :** Vérifier précisément la politique de rétention de l'IA (s'assurer qu'ils n'entraînent pas leurs modèles sur nos factures).
