Character JSON Normalized Schema

Overview: A uniform, GPT-friendly structure for character data. Keys are consistent across all characters, and long text is cleaned of mojibake and normalized for readability.

Top-level fields
- id: URL-safe identifier derived from name.
- name: Display name.
- titles: List of honorifics/epithets.
- species: Species or lineage label.
- gender: Gender description.
- age: Age as text (supports ancient beings).
- realm: Primary realm association.
- court: Court/faction within realm.
- affiliations: Other groups/factions.
- domains: Conceptual domains (e.g., Unity, Balance).
- role: Short role description or cosmic function.
- appearance: Structured description (see below).
- personality: Structured traits (see below).
- lineage: Family/essence details (see below).
- prophecy: Prophecy details (optional).
- abilities: List of abilities with description/application.
- relationships: Map of relationship label → description.
- notes: List of extra notes (optional).
- source: { file, category, group } provenance fields.

appearance
- height, build, skin, hair, eyes, wings, attire, distinctive_features: Strings
- notes: List of extra keyed descriptions that didn’t fit the standard keys.

personality
- traits: List of trait lines.
- temperament: One-paragraph temperament summary.
- virtues: List of strengths/virtues.
- flaws: List of weaknesses/flaws.

lineage
- father, mother: Strings
- siblings, consorts: Lists
- essence: String
- primordial: { type, origin, status, role }
- notes: List for additional lineage info.

prophecy
- name: Title of prophecy.
- description: Overview.
- lore_fragment: Quoted verse/excerpt.
- powers_foretold: List of foretold capabilities.

abilities (list items)
- name: Ability name.
- description: What it does.
- application: Typical use/context (optional).

Index shape (derived)
- id, name, titles[], realm, court, domains[]

