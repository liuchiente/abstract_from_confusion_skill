#!/usr/bin/env python3
"""Generate the gold source documents, deterministically.

The fixtures are generated from this script rather than checked in as binary
.docx/.xlsx files: a binary fixture cannot be reviewed in a diff, and this
repository is public, so every byte of source material has to be something a
reader can see the provenance of. Nothing here comes from a real specification
or from third-party training material.

The content is synthetic but carries the shapes extraction actually has to
survive: a nested table, a Vietnamese UI message beside its code and length, a
merged Excel header, a formula cell with no cached value, and prose sections
whose claims cross a heading.

  python3 make_sources.py --out <dir>

Run twice into the same directory and the bytes are identical, so a gold run is
reproducible.
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse

# A fixed timestamp keeps the document properties stable between runs. The zip
# container still records per-entry mtimes, so the bytes are not identical
# across runs -- what matters for a gold set is that the extracted content is,
# and that is what the Step 0 expectations assert.
FIXED_CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def write_docx(path):
    import docx
    from docx.shared import Pt

    document = docx.Document()
    document.core_properties.title = 'CB 加買規則說明'
    document.core_properties.created = FIXED_CREATED
    document.core_properties.modified = FIXED_CREATED

    document.add_heading('CB 商品加買規則', level=1)
    document.add_paragraph(
        'CB 保單在生效日之前可以加買乘客險。生效之後是否仍可加買，依加買期限判定；'
        '超過加買期限時系統不允許加買。')

    document.add_heading('UI 訊息與欄位', level=2)
    table = document.add_table(rows=3, cols=4)
    headers = ('欄位名稱', 'Error Message', 'Code', 'Max Length')
    for index, text in enumerate(headers):
        table.cell(0, index).text = text
    row = ('上傳檔案', 'Tải lên thất bại', 'E102', '100')
    for index, text in enumerate(row):
        table.cell(1, index).text = text
    row = ('保單號碼', 'Số hợp đồng không hợp lệ', 'E205', '20')
    for index, text in enumerate(row):
        table.cell(2, index).text = text

    document.add_heading('例外情形', level=2)
    outer = document.add_table(rows=2, cols=2)
    outer.cell(0, 0).text = '情境'
    outer.cell(0, 1).text = '處理方式'
    outer.cell(1, 0).text = '批次作業期間'
    nested_holder = outer.cell(1, 1)
    nested = nested_holder.add_table(rows=2, cols=2)
    nested.cell(0, 0).text = '子情境'
    nested.cell(0, 1).text = '結果'
    nested.cell(1, 0).text = '日結進行中'
    nested.cell(1, 1).text = '加買請求退回，顯示 E102'

    document.add_heading('名詞', level=2)
    paragraph = document.add_paragraph()
    run = paragraph.add_run('加買期限：保單生效後仍允許加買的期間，由商品設定決定。')
    run.font.size = Pt(11)

    document.save(str(path))
    return path


def write_xlsx(path):
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = '欄位定義'

    # A merged header that governs the two columns beneath it.
    sheet['A1'] = 'CB 乘客險欄位'
    sheet.merge_cells('A1:C1')
    sheet['A2'] = '欄位'
    sheet['B2'] = '必填'
    sheet['C2'] = 'Max Length'
    sheet['A3'] = '被保人姓名'
    sheet['B3'] = 'Y'
    sheet['C3'] = 60
    sheet['A4'] = '被保人證號'
    sheet['B4'] = 'Y'
    sheet['C4'] = 10

    totals = workbook.create_sheet('統計')
    totals['A1'] = '欄位總數'
    # Written as a formula with no cached value: openpyxl does not calculate, so
    # value_status is NO_CACHED_VALUE and the formula itself is the fact.
    totals['B1'] = '=COUNTA(欄位定義!A3:A4)'

    workbook.save(str(path))
    return path


def write_article(path):
    path.write_text('''# 加買作業說明

## 1. 適用範圍

本說明適用於 CB 商品的乘客險加買作業。車體損失險不在本文範圍內。

## 2. 作業流程

1. 業務員於系統查詢保單狀態。
2. 系統檢查是否仍在加買期限內。
3. 在期限內者建立加買申請；超過期限者退回。

申請建立後需由核保人員覆核，覆核不通過時退回業務員補件。

## 3. 錯誤處理

上傳失敗時系統顯示原始訊息 Tải lên thất bại，並記錄代碼 E102。
重複上傳同一檔案不會產生第二筆申請。
''', encoding='utf-8')
    return path


def write_out_of_scope(path):
    """A source in the same folder whose product is not the run's Scope.

    It exists so the gold set states what the boundary does instead of leaving
    it implicit: none of these units may be selected for a CB run, and its
    claims must not appear in CB Cards.
    """
    path.write_text("""# 傷害險加買說明

本說明適用於傷害險商品。

傷害險的加買期限為保單生效後 45 天。上傳失敗時顯示 Lỗi tải lên khác，代碼 X999。
""", encoding='utf-8')
    return path


def write_negation(path):
    """A source that mentions the active Scope only to deny applicability.

    Scope detection matches the product token anywhere in the text, so this file
    is currently selected for a CB run even though it says it does not apply.
    The gold set records that as a known limitation rather than hiding it: if
    the expectation ever flips to unselected, detection improved and the
    expectation should be updated deliberately.
    """
    path.write_text("""# 車體險免責說明

本說明適用於車體損失險，與 CB 乘客險無關。

車體險的自負額為 3000 元，與乘客險加買期限無關。
""", encoding='utf-8')
    return path


def write_scope(path):
    path.write_text('''# AFC scope for this directory

Gold fixture sources. The scope is the synthetic product `CB`.

## 預設 Scope

- `CB`

## 排除 Scope

- 無。
''', encoding='utf-8')
    return path


def main():
    ap = argparse.ArgumentParser(description='Generate the AFC gold source documents.')
    ap.add_argument('--out', required=True, help='Directory to write the sources into')
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    written = [
        write_docx(out / 'cb_spec.docx'),
        write_xlsx(out / 'cb_fields.xlsx'),
        write_article(out / 'cb_process.md'),
        write_out_of_scope(out / 'other_product.md'),
        write_negation(out / 'cb_negation.md'),
        write_scope(out / 'afc-scope.md'),
    ]
    for path in written:
        print(f'{path.name}\t{path.stat().st_size} bytes')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
