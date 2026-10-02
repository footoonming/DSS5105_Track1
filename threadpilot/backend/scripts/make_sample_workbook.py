"""场景 1.2：将随仓库的正式三表打包为导入示例。"""
import pandas as pd
from app.config import ROOT


def main() -> None:
    """场景 1.2：只创建新文件，保护已有原始表格。"""
    path = ROOT / 'data/raw/source.xlsx'
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError('source.xlsx already exists; original source was preserved')
    with pd.ExcelWriter(path, engine='openpyxl') as writer:
        for name in ('orders', 'production_log', 'workshops'):
            pd.read_csv(ROOT / 'data' / (name + '.csv')).to_excel(writer, sheet_name=name, index=False)
    print(path)


if __name__ == '__main__':
    main()
