"""场景 1.2：迁移和导入 CLI。"""
import argparse
from pathlib import Path
from app.config import ROOT
from app.db.init_db import initialize


def main() -> None:
    """场景 1.2：只导入明确指定的业务文件。"""
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', action='append', type=Path)
    parser.add_argument('--dataset', choices=['orders', 'production_log', 'workshops'])
    parser.add_argument('--seed-existing', action='store_true')
    parser.add_argument('--skip-migrate', action='store_true')
    args = parser.parse_args()
    if args.seed_existing and args.file:
        parser.error('--seed-existing and --file are mutually exclusive')
    files = [ROOT / 'data' / (name + '.csv') for name in ('orders', 'production_log', 'workshops')] if args.seed_existing else args.file
    if not files:
        default = ROOT / 'data/raw/source.xlsx'
        files = [default if default.exists() else ROOT / 'data/source.xlsx']
    initialize(files, migrate=not args.skip_migrate, dataset=args.dataset)


if __name__ == '__main__':
    main()
