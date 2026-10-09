"""One-time deterministic correction for the V2 raw-union diagnostic."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from app.services.evaluation.metrics import score_ranking
from app.services.evaluation.v2_benchmark import DIAGNOSTIC_K, raw_union


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recompute(report: dict) -> None:
    for track in report['tracks'].values():
        diagnostics = track['candidate_diagnostics']
        rows = diagnostics['per_query']
        at_k = {}
        for k in DIAGNOSTIC_K:
            values = {'BM25 Recall': [], 'Dense Recall': [], 'UNION Recall': [], 'RRF Recall': []}
            for row in rows:
                gold = row['gold']
                union = raw_union(row['bm25'], row['dense'], k)
                values['BM25 Recall'].append(score_ranking(row['bm25'], gold, k)['Recall'])
                values['Dense Recall'].append(score_ranking(row['dense'], gold, k)['Recall'])
                values['UNION Recall'].append(score_ranking(union, gold, len(union) or 1)['Recall'])
                values['RRF Recall'].append(score_ranking(row['rrf'], gold, k)['Recall'])
            at_k[str(k)] = {
                name: round(sum(metric_values) / len(metric_values), 4)
                for name, metric_values in values.items()
            }
        diagnostics['union_definition'] = 'deduplicated BM25[:K] union Dense[:K]; pool size <= 2K'
        diagnostics['at_k'] = at_k


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--result', default='../benchmarks/real_research/v2/results/baseline.json')
    parser.add_argument('--archive', default='../benchmarks/real_research/v2/results/baseline_metric_bug.json')
    args = parser.parse_args()
    result = Path(args.result).resolve()
    archive = Path(args.archive).resolve()
    if archive.exists():
        raise FileExistsError(f'bug_archive_is_immutable: {archive}')
    before_sha256 = digest(result)
    shutil.copy2(result, archive)
    report = json.loads(result.read_text(encoding='utf-8'))
    recompute(report)
    report['integrity']['bug_fix_rerun'] = {
        'kind': 'METRIC_ONLY_RECOMPUTE',
        'reason': 'Raw union was incorrectly truncated to K after interleaving.',
        'retrieval_rerun': False,
        'model_rerun': False,
        'ranking_metrics_changed': False,
        'archived_result': archive.name,
        'archived_result_sha256': before_sha256,
    }
    temporary = result.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(result)
    print(json.dumps({
        'status': 'BUG_FIX_RERUN',
        'kind': 'METRIC_ONLY_RECOMPUTE',
        'archived_sha256': before_sha256,
        'corrected_sha256': digest(result),
    }))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
