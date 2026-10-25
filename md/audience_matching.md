# Audience matching ("Who is it for?")

> **Demo only.** The audience tags are produced by keyword rules and have not been checked by a person. Before
> they are used with clients, the labels need to be verified and the rules made more precise (see
> [Limitations](#limitations) and [Next steps](#next-steps)).

This explains how `scripts/audiences/audience_enrichment.ipynb` tags each resource with the people it serves, and
how the finder uses those tags. Column details are in [scripts/audiences/README.md](../scripts/audiences/README.md).

## How a resource gets its audiences

1. **The PDF is the base.** If the Connections Guide lists an organization in an audience chapter (Youth, Women,
   Veterans, …), it keeps that audience. These are `pdf_audiences`, unchanged.
2. **Three texts are searched:** the organization's name, its description and its PDF listing text. Each of the
   11 audiences has a keyword pattern: the 9 PDF chapters plus *Survivors of violence* and *People without
   homes*, which have no chapter.
3. **Confirmation.** A PDF audience is *confirmed* when one of the texts also mentions it. Unconfirmed ones stay,
   but are flagged for review.
4. **`Everyone` is the default.** Every resource that isn't explicitly restricted gets `Everyone`, in addition to
   its specific audiences.
5. **Restricted is strict.** A resource is restricted to a group only when the text says so explicitly:
   *only*, *exclusively*, *limited to* or *must be* next to the audience, or an age range in the first sentence
   (12–25 counts as Youth, 55+ as Older People). Restricted resources don't get `Everyone`.
6. **Focus is softer.** When the audience is in the organization's name ("Center for Women"), or follows *for* /
   *serves* in the first sentence ("programs for LGBTQIA+ youth"), the resource focuses on that group. It stays
   open to everyone, but ranks first for that group.
7. **No match, no restriction.** If no text confirms a resource's audiences, they are kept from wherever they came
   from, and the resource always gets `Everyone`.

Before matching, notes left in the descriptions by the PDF extraction ("[PARTIAL/POINTER ONLY …]") are removed,
because they name guide chapters, not who a resource serves.

| Result (759 resources) | Count |
|---|---|
| Tagged `Everyone` | 734 |
| Restricted to a specific group | 25 (mostly youth programs with an age range) |
| PDF audience confirmed by a text | 247 · not confirmed 92 · partly 13 |

## How the finder shows it

- **Tile counts** on "Who is the help for?" show two numbers: the resources tagged with that group (Youth **123**)
  and, below, the open-to-everyone resources that picking it adds (**+587 open to all**). Together they are the
  number of results. A resource tagged with the group is counted once, in the first number.
- **Result order** for a picked audience: (1) made for it (restricted to or focused on it), (2) tagged with it,
  (3) open to everyone. Within each group, nearest first.
- **Excluded:** only resources restricted to a *different* group. A youth-only program doesn't show for Veterans.
- **Cards** show "Made for Youth", the other audiences, and "Open to everyone".
- **Until the migration is applied**, the finder falls back to `pdf_audiences` and works as before.

To see it before an import: serve the repo (`npm run dev`, or `python3 -m http.server 5173 --bind 127.0.0.1`) and
open `http://localhost:5173/?preview=local`. The live rows are read from Supabase, and the local CSVs are laid over
them in the browser. Nothing is written.

## Limitations

- **Keywords, not language understanding.** Negations ("does not serve youth") and wording without the expected
  words are missed.
- **Not reviewed by a person.** `scripts/audiences/check_audiences.py` (36 checks) makes sure the data is
  consistent and loads correctly, not that each tag is right.
- **`Everyone` is mostly assumed.** For 666 resources there is simply no sign of a restriction; only 68 say they
  are open to all.
- **Other eligibility isn't captured:** income, residence, insurance or a referral. "Open to everyone" does not
  mean "no requirements".
- **92 PDF audiences aren't confirmed by any text.** They are kept because the PDF is the source, but they are
  uncertain.
- **Source text quality.** 49 descriptions still contain PDF extraction notes; matching ignores them, but they are
  not cleaned up.
- **New categories are proposals:** *Disability Services* (service type, from #17), *Survivors of violence* and
  *People without homes* (audiences), and the violence category in issue dssg-nyc/KAVI-datathon#18 still need the team's OK.

## Next steps

1. Review `data/review/audience_no_match.csv` (PDF audiences no text confirms) and a sample from
   `data/review/audience_review.csv`; record single-row decisions in `scripts/audiences/reviewed_audiences.csv`
   and fix systematic misses in the patterns.
2. Tighten restriction rules with a reviewed sample, e.g. eligibility phrases beyond age ranges.
3. Decide with the team whether the new categories stay.
4. Apply `supabase/migrations/*_add_audience_columns_to_resources.sql`, run `npm run import -- --dry-run`, then
   `npm run import -- --replace`.
