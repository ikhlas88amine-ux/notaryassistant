# Audit des règles de validation métier

## 1. Règles existantes détectées avant refonte

| Rule ID | Fichier / fonction | Types concernés | Déclenchement | Niveau | Tests existants | Exemple dossier |
|---|---|---|---|---|---|---|
| name_presence | `app/validation/rules.py` / `rule_name_cin_presence_in_documents` | Tous dossiers contenant des parties identifiées dans donnees | Nom d'une partie absent du texte extrait | medium | aucun test dédié | 16-2023-882-VENTE-SQALLI |
| cin_presence | `app/validation/rules.py` / `rule_name_cin_presence_in_documents` | Tous dossiers contenant un CIN structuré | CIN d'une partie absent du texte extrait | medium | aucun test dédié | 16-2023-882-VENTE-SQALLI |
| tf_multiple_declared | `app/validation/rules.py` / `rule_titre_foncier_consistency` | Dossiers avec plusieurs champs TF | Plusieurs TF distincts déclarés dans dossier_master.json | blocking | aucun test dédié | 1-2024-843-AMBIGU |
| tf_text_mismatch | `app/validation/rules.py` / `rule_titre_foncier_consistency` | Dossiers avec TF en données et dans le texte extrait | TF extrait du document absent des données structurées | high | aucun test dédié | 16-2023-882-VENTE-SQALLI |
| price_breakdown_mismatch | `app/validation/rules.py` / `rule_price_consistency` | Dossiers contenant à la fois prix total et composantes de prix | Somme des composantes de prix différente du total déclaré | high | aucun test dédié | 16-2023-882-VENTE-SQALLI |
| price_multiple_declared | `app/validation/rules.py` / `rule_price_consistency` | Dossiers contenant plusieurs champs de prix/montant | Plusieurs montants de prix distincts incompatibles | blocking | test_deterministic_rag.py, test_validation.py | 1-2024-843-AMBIGU |
| date_format_invalid | `app/validation/rules.py` / `rule_date_validity` | Tous dossiers avec champs *date* structurés | Date structurée non conforme au format ISO AAAA-MM-JJ | low | aucun test dédié | 16-2023-882-VENTE-SQALLI |
| expected_document_missing | `app/validation/rules.py` / `rule_expected_documents` | VENTE, VENTE-AUTO, DONATION, SUCCESSION, PROCURATION, HYPOTHEQUE | Document principal attendu non détecté via le nom de fichier | medium | aucun test dédié | 16-2023-882-VENTE-SQALLI |
| radiation_without_mainlevee | `app/validation/rules.py` / `rule_radiation_requires_mainlevee` | Dossiers avec fichier contenant 'radiation' | Réquisition de radiation détectée sans mainlevée correspondante | blocking | aucun test dédié | 16-2023-882-VENTE-SQALLI |
| company_identified_by_cin | `app/validation/rules.py` / `rule_company_identification` | Dossiers contenant une partie société avec gérant | Société repérée par un champ gérant sans RC/ICE | high | aucun test dédié | 16-2023-882-VENTE-SQALLI |

## 2. Types et variantes réellement détectés dans les dossiers

| type_dossier | variante | nombre de dossiers | règles actives observées | règles manquantes / non observées | exemple |
|---|---:|---:|---|---|---|
| AMBIGU | double_tf_double_prix | 1 | multiple_conflicting_values | document_source_missing, dossier_identity_missing, price_multiple_declared | 15-2024-824-AMBIGU |
| AMBIGU | prix_contradictoire_fr_ar | 1 | multiple_conflicting_values, price_multiple_declared | document_source_missing, dossier_identity_missing | 1-2024-843-AMBIGU |
| DONATION | standard | 3 | checklist_incomplete, donation_family_link_unproven | amount_invalid, date_order_incoherent, document_source_missing, donation_declared_value_missing, donation_parties_missing, donation_qualification_missing, donation_tax_rate_missing, donation_tf_missing, dossier_identity_missing, required_field_missing, source_fact_conflict | 11-2024-595-DONATION-AMRANI |
| HYPOTHEQUE | engagement_1er_rang | 1 | checklist_incomplete, mortgage_registration_not_proven | amount_invalid, document_source_missing, dossier_identity_missing, mortgage_beneficiary_missing, mortgage_credit_amount_missing, mortgage_deadline_missing, mortgage_rank_amount_confusion, mortgage_rank_missing, mortgage_tf_missing, required_field_missing, source_fact_conflict | 9-2024-191-HYPOTHEQUE-AMRANI |
| HYPOTHEQUE | engagement_avec_caution | 1 | checklist_incomplete, mortgage_registration_not_proven, mortgage_surety_detected | amount_invalid, document_source_missing, dossier_identity_missing, mortgage_beneficiary_missing, mortgage_credit_amount_missing, mortgage_deadline_missing, mortgage_rank_amount_confusion, mortgage_rank_missing, mortgage_tf_missing, required_field_missing, source_fact_conflict | 10-2024-542-HYPOTHEQUE-SQALLI |
| HYPOTHEQUE | mainlevee | 1 | checklist_incomplete | amount_invalid, document_source_missing, dossier_identity_missing, release_bank_conflict, release_bank_discharge_missing, release_reference_missing, release_requisition_missing, required_field_missing, source_fact_conflict | 12-2024-306-HYPOTHEQUE-TEMSAMANI |
| PROCURATION | standard | 2 | checklist_incomplete, power_duration_unclear | document_source_missing, dossier_identity_missing, power_agent_missing, power_foreign_formality_unverified, power_principal_missing, power_scope_missing, required_field_missing | 13-2025-709-PROCURATION-CHRAIBI |
| SUCCESSION | standard | 2 | checklist_incomplete | amount_invalid, document_source_missing, dossier_identity_missing, required_field_missing, source_fact_conflict, succession_death_missing, succession_deceased_missing, succession_heirs_missing, succession_property_missing, succession_representative_missing_power, succession_shares_incoherent | 20-2025-388-SUCCESSION-LAZRAK |
| VENTE | fonds_de_commerce | 1 | business_sale_encumbrances_unverified, business_sale_inventory_missing, business_sale_publicity_unverified, checklist_incomplete | amount_invalid, business_sale_lease_or_occupation_unclear, business_sale_parties_missing, business_sale_price_missing, business_sale_rc_missing, document_source_missing, dossier_identity_missing, required_field_missing, source_fact_conflict | 8-2025-687-VENTE-GHALI |
| VENTE | hors_comptabilite | 1 | checklist_incomplete | amount_invalid, document_source_missing, dossier_identity_missing, price_multiple_declared, required_field_missing, sale_parties_missing, sale_payment_route_unclear, sale_price_missing, sale_representative_missing_power, sale_tax_and_fees_clause_missing, sale_tf_missing, source_fact_conflict | 17-2025-967-VENTE-ALAOUI |
| VENTE | mixte_comptabilite | 1 | checklist_incomplete | amount_invalid, document_source_missing, dossier_identity_missing, price_multiple_declared, required_field_missing, sale_parties_missing, sale_payment_route_unclear, sale_price_missing, sale_representative_missing_power, sale_tax_and_fees_clause_missing, sale_tf_missing, source_fact_conflict | 6-2026-450-VENTE-TAZI |
| VENTE | paiement_differe | 1 | checklist_incomplete | amount_invalid, document_source_missing, dossier_identity_missing, price_multiple_declared, required_field_missing, sale_deferred_payment_missing_terms, sale_parties_missing, sale_payment_breakdown_incoherent, sale_payment_route_unclear, sale_price_missing, sale_representative_missing_power, sale_tax_and_fees_clause_missing, sale_tf_missing, source_fact_conflict | 5-2026-876-VENTE-TAZI |
| VENTE | simple | 2 | checklist_incomplete | amount_invalid, document_source_missing, dossier_identity_missing, price_multiple_declared, required_field_missing, sale_parties_missing, sale_payment_route_unclear, sale_price_missing, sale_representative_missing_power, sale_tax_and_fees_clause_missing, sale_tf_missing, source_fact_conflict | 19-2024-613-VENTE-ELFASSI |
| VENTE | terrain_nu_engagement_construire | 1 | checklist_incomplete, sale_payment_route_unclear | amount_invalid, document_source_missing, dossier_identity_missing, price_multiple_declared, required_field_missing, sale_deferred_payment_missing_terms, sale_parties_missing, sale_payment_breakdown_incoherent, sale_price_missing, sale_representative_missing_power, sale_tax_and_fees_clause_missing, sale_tf_missing, source_fact_conflict | 18-2024-754-VENTE-CHRAIBI |
| VENTE | tripartite_bancaire | 1 | checklist_incomplete, sale_tax_and_fees_clause_missing | amount_invalid, document_source_missing, dossier_identity_missing, price_multiple_declared, required_field_missing, sale_parties_missing, sale_payment_route_unclear, sale_price_missing, sale_representative_missing_power, sale_tf_missing, source_fact_conflict | 21-2026-549-VENTE-SMIRI |
| VENTE | vefa | 1 | checklist_incomplete, vefa_completion_documents_not_applicable | amount_invalid, document_source_missing, dossier_identity_missing, required_field_missing, source_fact_conflict, vefa_delivery_terms_missing, vefa_guarantee_unproven, vefa_payment_schedule_missing, vefa_plan_or_description_missing, vefa_program_or_tf_missing | 16-2023-882-VENTE-SQALLI |
| VENTE-AUTO | standard | 1 | aucune règle déclenchée | amount_invalid, auto_sale_vehicle_identification_missing, document_source_missing, dossier_identity_missing, required_field_missing, source_fact_conflict | 22-2026-999-VENTE-AUTO |

## 3. Règles versionnées actives après refonte

| Rule ID | Gravité | Titre | Types / variantes | Tests existants | Exemple dossier |
|---|---|---|---|---|---|
| amount_invalid | warning | Montant invalide | HYPOTHEQUE | couvert indirectement | 10-2024-542-HYPOTHEQUE-SQALLI |
| auto_sale_vehicle_identification_missing | warning | Identification du véhicule incomplète | VENTE-AUTO:standard | couvert indirectement | 22-2026-999-VENTE-AUTO |
| business_sale_encumbrances_unverified | info | Charges du fonds non entièrement vérifiées | VENTE:fonds_de_commerce | couvert indirectement | 8-2025-687-VENTE-GHALI |
| business_sale_inventory_missing | warning | Inventaire des éléments cédés non détecté | VENTE:fonds_de_commerce | couvert indirectement | 8-2025-687-VENTE-GHALI |
| business_sale_lease_or_occupation_unclear | warning | Bail ou occupation à confirmer | VENTE:fonds_de_commerce | couvert indirectement | 8-2025-687-VENTE-GHALI |
| business_sale_parties_missing | warning | Parties de la cession de fonds absentes | VENTE:fonds_de_commerce | couvert indirectement | 8-2025-687-VENTE-GHALI |
| business_sale_price_missing | warning | Prix de cession absent | VENTE:fonds_de_commerce | couvert indirectement | 8-2025-687-VENTE-GHALI |
| business_sale_publicity_unverified | info | Publicité légale à confirmer | VENTE:fonds_de_commerce | couvert indirectement | 8-2025-687-VENTE-GHALI |
| business_sale_rc_missing | warning | Référence RC manquante | VENTE:fonds_de_commerce | couvert indirectement | 8-2025-687-VENTE-GHALI |
| checklist_incomplete | info | Checklist documentaire incomplète | HYPOTHEQUE | test_validation.py | 10-2024-542-HYPOTHEQUE-SQALLI |
| date_order_incoherent | warning | Ordre chronologique incohérent | DONATION | couvert indirectement | 11-2024-595-DONATION-AMRANI |
| document_source_missing | warning | Document source non détecté | AMBIGU | couvert indirectement | 1-2024-843-AMBIGU |
| donation_declared_value_missing | warning | Valeur déclarée absente | DONATION:standard | couvert indirectement | 11-2024-595-DONATION-AMRANI |
| donation_family_link_unproven | warning | Lien familial non justifié | DONATION:standard | couvert indirectement | 11-2024-595-DONATION-AMRANI |
| donation_parties_missing | warning | Parties de la donation absentes | DONATION:standard | couvert indirectement | 11-2024-595-DONATION-AMRANI |
| donation_qualification_missing | info | Qualification de la donation à confirmer | DONATION:standard | couvert indirectement | 11-2024-595-DONATION-AMRANI |
| donation_tax_rate_missing | info | Taux de droits à confirmer | DONATION:standard | couvert indirectement | 11-2024-595-DONATION-AMRANI |
| donation_tf_missing | warning | Titre foncier absent | DONATION:standard | couvert indirectement | 11-2024-595-DONATION-AMRANI |
| dossier_identity_missing | warning | Identité du dossier incomplète | AMBIGU | couvert indirectement | 1-2024-843-AMBIGU |
| mortgage_beneficiary_missing | warning | Banque bénéficiaire absente | HYPOTHEQUE:engagement_1er_rang/engagement_avec_caution | couvert indirectement | 10-2024-542-HYPOTHEQUE-SQALLI |
| mortgage_credit_amount_missing | warning | Montant du crédit absent | HYPOTHEQUE:engagement_1er_rang/engagement_avec_caution | couvert indirectement | 10-2024-542-HYPOTHEQUE-SQALLI |
| mortgage_deadline_missing | info | Délai d'inscription absent | HYPOTHEQUE:engagement_1er_rang/engagement_avec_caution | couvert indirectement | 10-2024-542-HYPOTHEQUE-SQALLI |
| mortgage_rank_amount_confusion | blocking | Rang et montant contradictoires | HYPOTHEQUE:engagement_1er_rang/engagement_avec_caution | test_validation.py | 10-2024-542-HYPOTHEQUE-SQALLI |
| mortgage_rank_missing | warning | Rang hypothécaire absent | HYPOTHEQUE:engagement_1er_rang/engagement_avec_caution | couvert indirectement | 10-2024-542-HYPOTHEQUE-SQALLI |
| mortgage_registration_not_proven | info | Inscription définitive non établie | HYPOTHEQUE:engagement_1er_rang/engagement_avec_caution | test_validation.py | 10-2024-542-HYPOTHEQUE-SQALLI |
| mortgage_surety_detected | info | Cautionnement hypothécaire détecté | HYPOTHEQUE:engagement_avec_caution | test_validation.py | 10-2024-542-HYPOTHEQUE-SQALLI |
| mortgage_tf_missing | warning | Titre foncier non identifié | HYPOTHEQUE:engagement_1er_rang/engagement_avec_caution | couvert indirectement | 10-2024-542-HYPOTHEQUE-SQALLI |
| multiple_conflicting_values | blocking | Valeurs critiques contradictoires | AMBIGU | couvert indirectement | 1-2024-843-AMBIGU |
| power_agent_missing | warning | Mandataire absent | PROCURATION:standard | couvert indirectement | 13-2025-709-PROCURATION-CHRAIBI |
| power_duration_unclear | info | Durée ou révocabilité à confirmer | PROCURATION:standard | couvert indirectement | 13-2025-709-PROCURATION-CHRAIBI |
| power_foreign_formality_unverified | warning | Formalisme étranger non vérifié | PROCURATION:standard | couvert indirectement | 13-2025-709-PROCURATION-CHRAIBI |
| power_principal_missing | warning | Mandant absent | PROCURATION:standard | couvert indirectement | 13-2025-709-PROCURATION-CHRAIBI |
| power_scope_missing | warning | Étendue des pouvoirs non établie | PROCURATION:standard | couvert indirectement | 13-2025-709-PROCURATION-CHRAIBI |
| price_multiple_declared | blocking | Plusieurs prix déclarés incompatibles | AMBIGU | test_deterministic_rag.py, test_validation.py | 1-2024-843-AMBIGU |
| release_bank_conflict | blocking | Banques contradictoires dans la mainlevée | HYPOTHEQUE:mainlevee | couvert indirectement | 12-2024-306-HYPOTHEQUE-TEMSAMANI |
| release_bank_discharge_missing | warning | Décharge bancaire non détectée | HYPOTHEQUE:mainlevee | couvert indirectement | 12-2024-306-HYPOTHEQUE-TEMSAMANI |
| release_reference_missing | warning | Référence de l'inscription à radier non établie | HYPOTHEQUE:mainlevee | couvert indirectement | 12-2024-306-HYPOTHEQUE-TEMSAMANI |
| release_requisition_missing | warning | Réquisition de radiation non détectée | HYPOTHEQUE:mainlevee | couvert indirectement | 12-2024-306-HYPOTHEQUE-TEMSAMANI |
| required_field_missing | warning | Champ structuré manquant | HYPOTHEQUE | couvert indirectement | 10-2024-542-HYPOTHEQUE-SQALLI |
| sale_deferred_payment_missing_terms | warning | Solde différé insuffisamment décrit | VENTE:paiement_differe/terrain_nu_engagement_construire | couvert indirectement | 18-2024-754-VENTE-CHRAIBI |
| sale_parties_missing | warning | Parties de la vente non établies | VENTE:hors_comptabilite/mixte_comptabilite/paiement_differe/simple/terrain_nu_engagement_construire/tripartite_bancaire | couvert indirectement | 17-2025-967-VENTE-ALAOUI |
| sale_payment_breakdown_incoherent | blocking | Décomposition du paiement incohérente | VENTE:paiement_differe/terrain_nu_engagement_construire | test_validation.py | 18-2024-754-VENTE-CHRAIBI |
| sale_payment_route_unclear | warning | Circuit de paiement non établi | VENTE:hors_comptabilite/mixte_comptabilite/paiement_differe/simple/terrain_nu_engagement_construire/tripartite_bancaire | couvert indirectement | 17-2025-967-VENTE-ALAOUI |
| sale_price_missing | warning | Prix de vente absent | VENTE:hors_comptabilite/mixte_comptabilite/paiement_differe/simple/terrain_nu_engagement_construire/tripartite_bancaire | couvert indirectement | 17-2025-967-VENTE-ALAOUI |
| sale_representative_missing_power | warning | Représentation sans procuration détectée | VENTE:hors_comptabilite/mixte_comptabilite/paiement_differe/simple/terrain_nu_engagement_construire/tripartite_bancaire | couvert indirectement | 17-2025-967-VENTE-ALAOUI |
| sale_tax_and_fees_clause_missing | info | Clause frais et charges non retrouvée | VENTE:hors_comptabilite/mixte_comptabilite/paiement_differe/simple/terrain_nu_engagement_construire/tripartite_bancaire | couvert indirectement | 17-2025-967-VENTE-ALAOUI |
| sale_tf_missing | warning | Titre foncier non identifié | VENTE:hors_comptabilite/mixte_comptabilite/paiement_differe/simple/terrain_nu_engagement_construire/tripartite_bancaire | couvert indirectement | 17-2025-967-VENTE-ALAOUI |
| source_fact_conflict | blocking | Incompatibilité entre données et document | HYPOTHEQUE | couvert indirectement | 10-2024-542-HYPOTHEQUE-SQALLI |
| succession_death_missing | warning | Décès non établi | SUCCESSION:standard | couvert indirectement | 20-2025-388-SUCCESSION-LAZRAK |
| succession_deceased_missing | warning | Défunt non identifié | SUCCESSION:standard | couvert indirectement | 20-2025-388-SUCCESSION-LAZRAK |
| succession_heirs_missing | warning | Héritiers non identifiés | SUCCESSION:standard | couvert indirectement | 20-2025-388-SUCCESSION-LAZRAK |
| succession_property_missing | info | Bien successoral non identifié | SUCCESSION:standard | couvert indirectement | 20-2025-388-SUCCESSION-LAZRAK |
| succession_representative_missing_power | warning | Héritier représenté sans procuration détectée | SUCCESSION:standard | couvert indirectement | 20-2025-388-SUCCESSION-LAZRAK |
| succession_shares_incoherent | blocking | Quotes-parts incohérentes | SUCCESSION:standard | test_validation.py | 20-2025-388-SUCCESSION-LAZRAK |
| vefa_completion_documents_not_applicable | info | Pièces d'achèvement non applicables à ce stade | VENTE:vefa | couvert indirectement | 16-2023-882-VENTE-SQALLI |
| vefa_delivery_terms_missing | info | Conditions d'achèvement ou de livraison à confirmer | VENTE:vefa | couvert indirectement | 16-2023-882-VENTE-SQALLI |
| vefa_guarantee_unproven | info | Garantie VEFA à confirmer | VENTE:vefa | couvert indirectement | 16-2023-882-VENTE-SQALLI |
| vefa_payment_schedule_missing | warning | Échéancier de paiement absent | VENTE:vefa | couvert indirectement | 16-2023-882-VENTE-SQALLI |
| vefa_plan_or_description_missing | warning | Description VEFA incomplète | VENTE:vefa | couvert indirectement | 16-2023-882-VENTE-SQALLI |
| vefa_program_or_tf_missing | warning | Programme ou TF d'origine non établi | VENTE:vefa | couvert indirectement | 16-2023-882-VENTE-SQALLI |

## 4. Doublons, règles mortes et dépendances de données

- `app/validation/rules.py` est désormais **héritée** : les anciennes fonctions existent encore pour audit mais ne pilotent plus la validation métier active.
- Les anciennes sévérités `high/medium/low` ne sont plus utilisées par la validation dossier active ; elles subsistent dans l'audit d'intégrité RAG, qui est un sous-système distinct.
- `price_multiple_declared` a été **conservée** comme identifiant stable pour ne pas casser les tests historiques, tout en étant normalisée dans l'architecture YAML + service déterministe.
- `checklist_incomplete` reste une information documentaire et ne conclut jamais à une invalidité juridique automatique.
- Les familles suivantes n'ont pas été implémentées faute de dossiers réels correspondants dans ce projet :
  - MAINLEVEE comme type autonome (modélisé dans ce projet comme variante HYPOTHEQUE/mainlevee)
  - CREATION_SOCIETE / SARL : aucun dossier réel détecté dans data/dossiers
  - GERANCE_LIBRE : aucun dossier réel détecté dans data/dossiers
  - DEMANDES_ADMINISTRATIVES : aucun dossier réel détecté dans data/dossiers
- `VENTE-AUTO` est présent dans les données ; une couverture minimale spécifique a été ajoutée (identification véhicule), distincte des ventes immobilières.

## 5. Distribution actuelle observée sur les dossiers réels

- Dossiers `valid` : 15
- Dossiers `warnings` : 5
- Dossiers `invalid` : 2
- Seuls les dossiers AMBIGU restent invalides après refonte : `1-2024-843-AMBIGU`, `15-2024-824-AMBIGU`.
