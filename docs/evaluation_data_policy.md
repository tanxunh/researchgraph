# Evaluation data policy

## PUBLIC

Application/evaluation code, schemas, synthetic fixtures, methodology, frozen final configs and manifest with original hashes; aggregate metric JSON/CSV; query text and locator-only Gold metadata. The exact V2 allowlist is in .gitignore. Public query files retain document/version/chunk IDs and page/section metadata, not verbatim Gold passages. Paper titles and bibliographic metadata identify the corpus; they do not distribute its contents.

Curated G4 aggregates: final_summary.json, workflow_funnel.json and poc_closeout.json. These are saved results, not newly generated answers. Frozen config historical status fields remain unchanged; final_retrieval_manifest.json is the final TEST validation record.

## PRIVATE / NOT DISTRIBUTED

Original PDFs, copied PDF text, Gold verbatim spans/anchors, annotation review packets with Evidence text, complete LLM request/response records, runtime Evidence traces, corpus/vector/database snapshots and model caches are ignored. Local originals and rejection/annotation lineage are preserved. MIT covers project code, not third-party papers or models. Do not use git add -f to publish private artifacts.

## REPRODUCIBILITY LIMITATION

A public clone supports product regression, synthetic evaluation contract tests and inspection of frozen results. It does not contain the source evidence required to independently reproduce the quality numbers. Obtain papers lawfully, reconstruct the corpus and index in your own environment, and validate identities before running a separate experiment. No private download or real-corpus rebuild happens in CI.

Frozen manifests retain historical relative .tmp and artifact paths as provenance, not files promised in the public repository. Some private historical captures contain machine-specific paths; those captures are not distributed. Do not edit immutable files to make old paths look portable. Supply environment/configuration outside frozen records for any future independent reproduction and retain its separate run identity.

Semantic workflow review is MODEL_ASSISTED_SEMANTIC_REVIEW. It is not independent human evaluation. The workflow used RECONSTRUCTED_EVALUATION_RUNTIME, not a recovered production runtime.
