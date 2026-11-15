"""Check the selected DESNZ source rows without network access or extra packages."""

import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def verify(workbook: Path) -> int:
    reference = json.loads((ROOT / "data/emission_factors_2026.json").read_text())
    digest = hashlib.sha256(workbook.read_bytes()).hexdigest()
    if digest != reference["workbook_sha256"]:
        raise ValueError("Другой файл или версия DESNZ: контрольная сумма не совпадает.")
    with ZipFile(workbook) as archive:
        strings = [
            "".join(node.itertext())
            for node in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("s:si", NS)
        ]
        # Resolve the worksheet by its name rather than assuming its position.
        sheets = ET.fromstring(archive.read("xl/workbook.xml"))
        sheet = next(s for s in sheets.findall("s:sheets/s:sheet", NS)
                     if s.attrib["name"] == reference["worksheet"])
        rel_id = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = next(r.attrib["Target"] for r in rels if r.attrib["Id"] == rel_id)
        path = target.lstrip("/") if target.startswith("/") else "xl/" + target
        xml = ET.fromstring(archive.read(path))

    wanted = {r["id"]: r for r in reference["rows"]}
    found = set()
    for row in xml.findall("s:sheetData/s:row", NS):
        cells = {}
        for cell in row.findall("s:c", NS):
            column = "".join(c for c in cell.attrib["r"] if c.isalpha())
            value_node = cell.find("s:v", NS)
            value = value_node.text if value_node is not None else ""
            cells[column] = strings[int(value)] if cell.get("t") == "s" else value
        identifier = cells.get("A")
        if identifier not in wanted:
            continue
        if identifier in found:
            raise ValueError(f"Повторный идентификатор: {identifier}")
        expected = wanted[identifier]
        for column, key in [("C", "category"), ("E", "type"), ("G", "variant"),
                            ("H", "unit"), ("I", "ghg")]:
            if cells.get(column, "") != expected[key]:
                raise ValueError(f"{identifier}: не совпадает {key}")
        # XLSX stores decimal values with binary floating point artefacts.
        if abs(Decimal(cells["J"]) - Decimal(expected["value"])) > Decimal("1e-12"):
            raise ValueError(f"{identifier}: не совпадает коэффициент")
        found.add(identifier)
    if found != set(wanted):
        raise ValueError("Не найдены строки: " + ", ".join(sorted(set(wanted) - found)))
    return len(found)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Использование: python3 -B tools/verify_factors.py /path/to/factors.xlsx")
    try:
        count = verify(Path(sys.argv[1]))
    except (OSError, ValueError, KeyError, StopIteration) as error:
        sys.exit(f"Проверка не пройдена: {error}")
    print(f"Проверено {count} строк DESNZ 2026: значения, единицы и SHA256 совпадают.")
