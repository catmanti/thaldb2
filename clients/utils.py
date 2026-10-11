"""
Utility functions for Sri Lankan EMR text search and transliteration expansion.
"""
from django.db import models


def expand_phonetic_variants(query: str) -> list[str]:
    """
    Expands a search query into common Sri Lankan English transliteration variants.
    Handles Sinhala/Tamil romanization equivalences:
    - w <-> v  (e.g., Nawa / Nava, Wasantha / Vasantha, Nawanjana / Navanjana)
    - th <-> t (e.g., Nawarathna / Navaratna, Wathsala / Watsala)
    - ee <-> i (e.g., Kumari / Kumaree)
    - oo <-> u (e.g., Bandara / Bandoora)
    """
    raw = query.strip().lower()
    if not raw:
        return []

    variants = {raw}

    # 1. Sinhala 'ව' duality: w <-> v
    for q in list(variants):
        if "w" in q:
            variants.add(q.replace("w", "v"))
        if "v" in q:
            variants.add(q.replace("v", "w"))

    # 2. Sinhala 'ත' duality: th <-> t
    for q in list(variants):
        if "th" in q:
            variants.add(q.replace("th", "t"))
        elif "t" in q:
            variants.add(q.replace("t", "th"))

    # 3. ee <-> i
    for q in list(variants):
        if "ee" in q:
            variants.add(q.replace("ee", "i"))
        elif "i" in q and len(q) > 3:
            variants.add(q.replace("i", "ee"))

    # 4. oo <-> u
    for q in list(variants):
        if "oo" in q:
            variants.add(q.replace("oo", "u"))
        elif "u" in q and len(q) > 3:
            variants.add(q.replace("u", "oo"))

    return list(variants)[:12]


def build_client_search_query(q: str, extra_fields: list[str] | None = None) -> models.Q:
    """
    Constructs a comprehensive Q object for client search.
    Applies Sri Lankan phonetic expansion to name fields (full_name, common_name)
    and exact substring matching to identifiers (registration_number, nic_number, contact_number).
    """
    q_clean = q.strip()
    if not q_clean:
        return models.Q()

    # Base identifier matches (reg number, NIC, contact)
    condition = (
        models.Q(registration_number__icontains=q_clean)
        | models.Q(nic_number__icontains=q_clean)
        | models.Q(contact_number__icontains=q_clean)
    )

    # Phonetic variations across name fields
    variants = expand_phonetic_variants(q_clean)
    for variant in variants:
        condition |= models.Q(full_name__icontains=variant)
        condition |= models.Q(common_name__icontains=variant)

    # Extra model fields (e.g. death_record__cause_of_death, bmt_records__institution_name)
    if extra_fields:
        for field in extra_fields:
            condition |= models.Q(**{f"{field}__icontains": q_clean})

    return condition
