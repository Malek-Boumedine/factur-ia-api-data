from typing import Any

import httpx


async def get_company_by_identifier(identifier: str) -> dict[str, Any] | None:
    """
    Recherche une entreprise sur l'API publique via SIREN ou SIRET.
    Extrait les données du siège social pour la facturation.
    """
    url = "https://recherche-entreprises.api.gouv.fr/search"
    params = {"q": identifier}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params, timeout=5.0)
            response.raise_for_status()
            data = response.json()

            if data.get("results") and len(data["results"]) > 0:
                company = data["results"][0]
                headquarters = company.get("siege", {})

                # 1. Vérification légale : l'entreprise doit être active
                if (
                    company.get("etat_administratif") != "A"
                    or headquarters.get("etat_administratif") != "A"
                ):
                    return {
                        "erreur": "Cette entreprise ou cet établissement est fermé(e)."
                    }

                # 2. Raison sociale
                company_name = company.get("nom_raison_sociale") or company.get(
                    "nom_complet"
                )

                # 3. Reconstruction de l'adresse
                street_num = headquarters.get("numero_voie") or ""
                street_type = headquarters.get("type_voie") or ""
                street_name = headquarters.get("libelle_voie") or ""
                clean_address: str | None = (
                    f"{street_num} {street_type} {street_name}".strip()
                )

                if not clean_address or "NON-DIFFUSIBLE" in clean_address:
                    clean_address = None

                return {
                    # L'API renvoie toujours le SIRET du siège,
                    # même si on a cherché par SIREN
                    "siret": headquarters.get("siret"),
                    "sirene": company.get("siren"),
                    "raison_sociale": company_name,
                    "adresse": clean_address,
                    "code_postal": headquarters.get("code_postal")
                    if headquarters.get("code_postal") != "[NON-DIFFUSIBLE]"
                    else None,
                    "ville": headquarters.get("libelle_commune"),
                    "numero_tva": company.get("numero_tva_intracommunautaire"),
                    "activite_principale": headquarters.get("activite_principale"),
                    "nom_dirigeant": company.get("dirigeants")[0].get("nom"),
                    "prenom_dirigeant": company.get("dirigeants")[0].get("prenoms"),
                    "type_dirigeant": company.get("dirigeants")[0].get(
                        "type_dirigeant"
                    ),
                }

            return None

        except httpx.HTTPError:
            return None
